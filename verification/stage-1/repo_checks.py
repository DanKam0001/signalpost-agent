#!/usr/bin/env python3
"""Packaging, docs, tests, replay, self-score, snapshot and Docker checks (R-1.1, 1.2, 1.11, 1.12, 1.29, 1.46a,
1.47 docs, 1.57, 1.59-1.66).  usage: repo_checks.py --repo CLONE --tag TAG [--docker] [--only a,b]"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time, traceback, gzip
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
from brreg import jget, ENH  # noqa

R = {}
def chk(rid, name, ok, detail=None):
    R.setdefault(rid, {"pass": True, "items": []})
    R[rid]["items"].append({"check": name, "pass": bool(ok), "detail": detail})
    if not ok: R[rid]["pass"] = False


def read(repo, *names):
    for n in names:
        p = os.path.join(repo, n)
        if os.path.exists(p): return open(p, encoding="utf-8", errors="replace").read()
    return ""


def sh(cmd, cwd, timeout=1800, env=None):
    e = dict(os.environ); e.update(env or {})
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BRAVE_API_KEY"): e.pop(k, None)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=e, shell=isinstance(cmd, str))
    return p.returncode, (p.stdout + p.stderr)


def docs(repo, out):
    req = read(repo, "requirements.txt")
    lines = [l.strip() for l in req.splitlines() if l.strip() and not l.strip().startswith("#")]
    chk("R-1.57", "requirements.txt exists", bool(req))
    chk("R-1.57", "every dependency pinned with ==", all("==" in l or l.startswith("-") for l in lines), [l for l in lines if "==" not in l])
    alldocs = "\n".join(read(repo, n) for n in ("README.md", "RUN.md", "pyproject.toml", "Dockerfile", ".python-version"))
    chk("R-1.57", "python >=3.11 declared", re.search(r"3\.1[1-9]|>=\s*3\.1[1-9]|python_requires|requires-python", alldocs) is not None)
    readme, run = read(repo, "README.md"), read(repo, "RUN.md")
    chk("R-1.1", "README/RUN give one run command", "python -m signalpost run" in readme + run)
    chk("R-1.59", "Dockerfile exists", os.path.exists(os.path.join(repo, "Dockerfile")))
    for w in ("install", "run", "serve", "pytest", "resume", "replay"):
        chk("R-1.59", f"RUN.md covers {w}", w in run.lower())
    lic = read(repo, "LICENSE", "LICENSE.md")
    chk("R-1.63", "LICENSE is MIT", "MIT License" in lic or "Permission is hereby granted, free of charge" in lic)
    d = (readme + run + "\n".join(open(p, encoding="utf-8", errors="replace").read() for p in glob.glob(os.path.join(repo, "docs", "*.md")))).lower()
    for w, pat in (("setup", r"install"), ("screenshot", r"!\[.*\]\(.*\.(png|jpg|gif|webp)\)"), ("live-link status", r"live (link|demo|url)"),
                   ("limitations", r"limitation"), ("schema", r"schema"), ("robots", r"robots"), ("rate limit", r"rate.limit"),
                   ("url safety", r"private|loopback|ssrf"), ("secrets via env", r"environment variable|env var"),
                   ("identity/abstention", r"ambiguous|abstain|abstention"), ("refresh model", r"refresh|idempot")):
        chk("R-1.63", f"docs mention {w}", re.search(pat, d) is not None)
    chk("R-1.66", "README has screenshot image that exists",
        any(os.path.exists(os.path.join(repo, m)) for m in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)))
    chk("R-1.66", "README has honest self-score vs rubric", re.search(r"self.?score", readme, re.I) is not None and re.search(r"\b50\b.*\b30\b|recall", readme, re.I) is not None)
    chk("R-1.64", "declares models/APIs/licences/cost", all(re.search(p, d) for p in (r"model|llm", r"api", r"licen[cs]e", r"cost|\$0|usd")))
    chk("R-1.47", "docs name the optional env vars or state that no key/LLM is used",
        re.search(r"ANTHROPIC_API_KEY|OPENAI_API_KEY|BRAVE_API_KEY|no api key|reads no api key|no llm", readme + run + d, re.I) is not None)
    em = read(repo, "SUBMIT/email.md")
    for w, pat in (("to submit@builderr.ai", r"submit@builderr\.ai"), ("subject", r"Signalpost Round 1 submission"), ("agent name", r"agent name"),
                   ("repository URL", r"repositor"), ("commit hash", r"commit"), ("smoke test", r"smoke"), ("run command", r"python -m signalpost run"),
                   ("models/APIs/licences", r"licen[cs]"), ("cost", r"cost"), ("contact placeholder", r"contact")):
        chk("R-1.65", f"email has {w}", re.search(pat, em, re.I) is not None)


def pytest_offline(repo, out):
    rc, o = sh(".venv/bin/pip install -q -r requirements-dev.txt", repo)
    chk("R-1.60", "dev requirements install", rc == 0, o[-500:])
    dead = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    rc, o = sh(".venv/bin/python -m pytest -q", repo, env=dead)
    open(os.path.join(out, "pytest.log"), "w").write(o)
    chk("R-1.60", "pytest passes offline", rc == 0, o[-600:])


def only_input(repo, out):
    d = os.path.join(out, "onlyinput"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    open(os.path.join(d, "b.txt"), "w").write("923609016\n982463718\n")
    rc, o = sh([".venv/bin/python", "-m", "signalpost", "run", "--input", os.path.join(d, "b.txt"), "--output", os.path.join(d, "e.jsonl"),
                "--report", os.path.join(d, "r.json"), "--no-web"], repo)
    envs = [json.loads(l) for l in open(os.path.join(d, "e.jsonl"))] if os.path.exists(os.path.join(d, "e.jsonl")) else []
    chk("R-1.1", "single command, exit 0", rc == 0, o[-400:])
    chk("R-1.2", "processes exactly the supplied companies", [e["organisation_number"] for e in envs] == ["923609016", "982463718"])
    rep = json.load(open(os.path.join(d, "r.json"))) if os.path.exists(os.path.join(d, "r.json")) else {}
    flat = json.dumps(rep).lower()
    for w in ("p50", "p95", "request", "bytes", "cost", "runtime"):
        chk("R-1.12", f"report has {w}", w in flat)
    chk("R-1.12", "per-source request counts", "brreg" in flat or "data.brreg.no" in flat)
    chk("R-1.12", "peak memory reported", "mem" in flat or "rss" in flat)
    rc, h = sh([".venv/bin/python", "-m", "signalpost", "run", "--help"], repo)
    for f in ("--workers", "--per-company-timeout", "--time-budget-seconds", "--resume", "--state-dir", "--expected-count", "--registry-snapshot", "--no-web"):
        chk("R-1.11" if f in ("--workers", "--per-company-timeout") else "R-1.1", f"run --help lists {f}", f in h)
    chk("R-1.11", "per-host rate limit documented", re.search(r"rate|per.host|delay", h + read(repo, "RUN.md") + read(repo, "README.md"), re.I) is not None)


def replay(repo, out):
    d = os.path.join(out, "replay"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    rc, h = sh([".venv/bin/python", "-m", "signalpost", "replay", "--help"], repo)
    cands = [p for p in [os.path.join(repo, "tests", "fixtures", "replay")] if os.path.isdir(p)]
    chk("R-1.46a", "replay fixtures directory shipped", bool(cands), cands[:3])
    if not cands: return
    rc, o = sh([".venv/bin/python", "-m", "signalpost", "replay", "--fixtures", cands[0], "--output", os.path.join(d, "replay.json")], repo)
    chk("R-1.46a", "replay exits 0", rc == 0, o[-500:])
    try:
        rj = json.load(open(os.path.join(d, "replay.json")))
    except Exception as e:
        chk("R-1.46a", "replay output JSON", False, str(e)); return
    s = json.dumps(rj)
    passes = rj if isinstance(rj, list) else rj.get("passes") or rj.get("replays") or []
    chk("R-1.46a", "replay output has >= 3 passes", len(passes) >= 3, len(passes))
    allch = [ch for p_ in passes for ch in (p_.get("changes") or [])]
    chk("R-1.46a", "some pass reports expected changes", len(allch) > 0)
    chk("R-1.46a", "each change has type/claim_key/previous/current/evidence/materiality",
        all(all(k in ch for k in ("type", "claim_key", "previous", "current", "evidence", "materiality")) for ch in allch),
        [ch for ch in allch if not all(k in ch for k in ("type", "claim_key", "previous", "current", "evidence", "materiality"))][:2])
    chk("R-1.46a", "no duplicate change within a pass", all(len({json.dumps(c, sort_keys=True) for c in p_.get("changes") or []}) == len(p_.get("changes") or []) for p_ in passes))
    if passes: chk("R-1.46a", "last (identical) pass has changes == []", passes[-1].get("changes") == [], passes[-1].get("changes"))
    shutil.copy(os.path.join(d, "replay.json"), os.path.join(out, "replay-output.json"))


def snapshot(repo, out):
    d = os.path.join(out, "snapshot"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    ents = [jget(ENH.format(o))[1] for o in ("923609016", "982463718")]
    p = os.path.join(d, "enheter_snapshot.json.gz")
    with gzip.open(p, "wt", encoding="utf-8") as f: json.dump(ents, f, ensure_ascii=False)
    open(os.path.join(d, "b.txt"), "w").write("923609016\n982463718\n")
    rc, o = sh([".venv/bin/python", "-m", "signalpost", "run", "--input", os.path.join(d, "b.txt"), "--output", os.path.join(d, "e.jsonl"),
                "--report", os.path.join(d, "r.json"), "--no-web", "--registry-snapshot", p], repo)
    chk("R-1.29", "run with --registry-snapshot exits 0", rc == 0, o[-400:])
    s = open(os.path.join(d, "e.jsonl")).read() if os.path.exists(os.path.join(d, "e.jsonl")) else ""
    chk("R-1.29", "evidence cites snapshot identity", "enheter_snapshot" in s or "snapshot" in s.lower() and "sha256" in s)
    chk("R-1.29", "evidence still carries the API URL", "data.brreg.no/enhetsregisteret/api/enheter/923609016" in s)


def selfscore(repo, out):
    d = os.path.join(out, "selfscore"); shutil.rmtree(d, ignore_errors=True)
    sys.path.insert(0, HERE); from sample import universe
    rc, o = sh([".venv/bin/python", "-m", "signalpost", "selfscore", "--universe", universe(), "--count", "20", "--seed", "90210", "--out", d], repo, timeout=3600)
    open(os.path.join(out, "selfscore.log"), "w").write(o)
    chk("R-1.61", "selfscore exits 0", rc == 0, o[-500:])
    blob = ""
    for p in glob.glob(os.path.join(d, "**", "*"), recursive=True):
        if os.path.isfile(p) and p.endswith((".json", ".md", ".txt")): blob += open(p, errors="replace").read().lower()
    blob += o.lower()
    for w, pat in (("envelope vs input count", r"envelope"), ("state distribution", r"not_available|state"), ("per-field coverage", r"coverage"),
                   ("per-section coverage", r"section"), ("evidence completeness", r"evidence"), ("idempotency", r"idempot"),
                   ("p50/p95", r"p95"), ("requests", r"request"), ("rubric estimate", r"rubric|recall"), ("seed", r"90210")):
        chk("R-1.61", f"selfscore reports {w}", re.search(pat, blob) is not None)


def smoke_committed(repo, out):
    cands = [p for p in glob.glob(os.path.join(repo, "**", "*envelope*.jsonl"), recursive=True) if ".venv" not in p and "verification" not in p
             and sum(1 for _ in open(p)) == 100]
    chk("R-1.62", "committed 100-line envelopes JSONL", bool(cands), cands[:3])
    if not cands: return
    p = cands[0]; dd = os.path.dirname(p)
    reps = [q for q in glob.glob(os.path.join(dd, "*.json")) if "report" in os.path.basename(q)]
    chk("R-1.62", "run report next to it", bool(reps), dd)
    txt = "".join(open(q, errors="replace").read() for q in glob.glob(os.path.join(dd, "*")) if os.path.isfile(q) and not q.endswith(".jsonl"))
    chk("R-1.62", "seed recorded", re.search(r"seed", txt, re.I) is not None)
    batch = os.path.join(out, "smoke-batch.txt")
    open(batch, "w").write("\n".join(json.loads(l)["organisation_number"] for l in open(p)) + "\n")
    rc = subprocess.call([sys.executable, os.path.join(HERE, "check_envelopes.py"), "--input", batch, "--output", p,
                          "--out", os.path.join(out, "smoke-committed-checks.json")], stdout=open(os.path.join(out, "smoke-committed-checks.txt"), "w"))
    chk("R-1.62", "committed smoke result passes envelope checks", rc == 0)
    # universe membership: the committed smoke should be a random 100 from the public universe
    sys.path.insert(0, HERE); from sample import universe
    uni = {json.loads(l)["organisation_number"] for l in gzip.open(universe(), "rt")}
    chk("R-1.62", "all 100 org numbers are in the public universe", all(json.loads(l)["organisation_number"] in uni for l in open(p)))


def docker(repo, out):
    tag = "signalpost-verify:" + os.path.basename(out)
    rc, o = sh(["docker", "build", "-t", tag, "."], repo, timeout=1800)
    open(os.path.join(out, "docker-build.log"), "w").write(o)
    chk("R-1.59", "docker build", rc == 0, o[-500:])
    if rc: return
    d = os.path.join(out, "docker"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d); os.chmod(d, 0o777)
    open(os.path.join(d, "b.txt"), "w").write("923609016\n982463718\n908660242\n")
    rc, o = sh(["docker", "run", "--rm", "--cpus", "2", "--memory", "2g", "-v", f"{d}:/data", tag, "run",
                "--input", "/data/b.txt", "--output", "/data/e.jsonl", "--report", "/data/r.json"], repo, timeout=1200)
    open(os.path.join(out, "docker-run.log"), "w").write(o)
    n = sum(1 for _ in open(os.path.join(d, "e.jsonl"))) if os.path.exists(os.path.join(d, "e.jsonl")) else 0
    chk("R-1.59", "docker run (2 CPU, 2 GB) same command -> 3 envelopes", rc == 0 and n == 3, (rc, n, o[-300:]))
    # dependencies baked in: install nothing at runtime -> run with --network none still produces envelopes (blocked/failed)
    rc, o = sh(["docker", "run", "--rm", "--network", "none", "-v", f"{d}:/data", tag, "run",
                "--input", "/data/b.txt", "--output", "/data/e2.jsonl", "--report", "/data/r2.json", "--per-company-timeout", "20"], repo, timeout=1200)
    n = sum(1 for _ in open(os.path.join(d, "e2.jsonl"))) if os.path.exists(os.path.join(d, "e2.jsonl")) else 0
    st = [json.loads(l).get("status") for l in open(os.path.join(d, "e2.jsonl"))] if n else []
    chk("R-1.59", "docker --network none: starts (deps baked in) and still emits 3 envelopes", n == 3, (rc, st, o[-300:]))


STEPS = {"docs": docs, "only_input": only_input, "replay": replay, "snapshot": snapshot, "pytest": pytest_offline,
         "smoke_committed": smoke_committed, "selfscore": selfscore, "docker": docker}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--only"); ap.add_argument("--docker", action="store_true"); a = ap.parse_args()
    out = os.path.join(HERE, "logs", a.tag); os.makedirs(out, exist_ok=True)
    names = a.only.split(",") if a.only else [n for n in STEPS if n != "docker" or a.docker]
    for n in names:
        try: STEPS[n](os.path.abspath(a.repo), out)
        except Exception: chk("ERROR", n, False, traceback.format_exc()[-1500:])
    prev = {}
    p = os.path.join(out, "repo_checks.json")
    if os.path.exists(p) and a.only: prev = json.load(open(p))
    prev.update(R); json.dump(prev, open(p, "w"), indent=1, default=str)
    for k, v in sorted(R.items()):
        print(k, "PASS" if v["pass"] else "FAIL", [i["check"] for i in v["items"] if not i["pass"]])
