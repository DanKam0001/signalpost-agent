#!/usr/bin/env python3
"""Failure-condition, hard-rule, idempotency and website-layer scenarios, run against a prepared clone
(the acceptance clone, with its .venv installed by the declared install step).

usage: scenarios.py --repo /tmp/sp-accept-.../repo --tag <commit10> [--only name,name] [--big]
Writes logs/<tag>/scenarios.json (+ per-scenario work dirs under runs/). Each scenario lists the
ledger ids it covers. A scenario that errors counts as FAIL.
"""
import argparse, json, os, re, signal, shutil, subprocess, sys, time, traceback, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
from inputs import read_batch  # noqa

EQUINOR = "923609016"      # large ASA, roles, subunits, accounts in USD
INVALID_CD = "923609017"   # bad mod-11 check digit
UNKNOWN = "908660242"      # valid check digit, Brreg 404 (probed 2026-09-29)
DELETED = "921326904"      # Brreg 410, slettedato 2019-06-18 (probed 2026-09-29)
SECRET = "sk-ant-VERIFIERBOGUSKEY0000000000"


class Ctx:
    def __init__(s, repo, tag):
        s.repo = repo; s.tag = tag
        s.work = os.path.join(HERE, "runs", tag); os.makedirs(s.work, exist_ok=True)
        s.py = os.path.join(repo, ".venv", "bin", "python")

    def run(s, name, batch_lines, extra=(), env=None, timeout=3600, kill_after=None, fmt="jsonl", fresh=True):
        d = os.path.join(s.work, name)
        if fresh and os.path.exists(d): shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)
        inp = os.path.join(d, "batch." + ("txt" if fmt == "text" else fmt))
        if batch_lines is not None:
            with open(inp, "w", encoding="utf-8") as f:
                if fmt == "json": json.dump(batch_lines, f)
                else: f.write("\n".join(batch_lines) + "\n")
        cmd = [s.py, "-m", "signalpost", "run", "--input", inp, "--output", os.path.join(d, "envelopes.jsonl"),
               "--report", os.path.join(d, "report.json"), *extra]
        e = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BRAVE_API_KEY")}
        e.update(env or {})
        t = time.time()
        with open(os.path.join(d, "stdout.log"), "a") as lo:
            lo.write(f"\n$ {' '.join(cmd)}\n"); lo.flush()
            p = subprocess.Popen(cmd, cwd=s.repo, stdout=lo, stderr=subprocess.STDOUT, env=e, start_new_session=True)
            try:
                rc = p.wait(timeout=kill_after or timeout)
            except subprocess.TimeoutExpired:
                if kill_after:
                    os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = "killed"
                else:
                    os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = "timeout"
        return {"dir": d, "input": inp, "rc": rc, "wall_s": round(time.time() - t, 2),
                "envs": load(os.path.join(d, "envelopes.jsonl")), "report": loadj(os.path.join(d, "report.json"))}

    def check(s, r, oracle=True):
        cmd = [sys.executable, os.path.join(HERE, "check_envelopes.py"), "--input", r["input"], "--output",
               os.path.join(r["dir"], "envelopes.jsonl"), "--report", os.path.join(r["dir"], "report.json"),
               "--out", os.path.join(r["dir"], "checks.json")] + (["--oracle"] if oracle else [])
        p = subprocess.run(cmd, capture_output=True, text=True)
        open(os.path.join(r["dir"], "checks.txt"), "w").write(p.stdout + p.stderr)
        return p.returncode == 0, p.stdout[-3000:]


def load(p):
    out = []
    if os.path.exists(p):
        for l in open(p, encoding="utf-8", errors="replace"):
            if l.strip():
                try: out.append(json.loads(l))
                except Exception: out.append({"_unparseable": l[:200]})
    return out


def loadj(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None


def universe_sample(n, seed):
    import random, gzip
    sys.path.insert(0, HERE); from sample import universe
    rows = [l.strip() for l in gzip.open(universe(), "rt", encoding="utf-8") if l.strip()]
    return random.Random(seed).sample(rows, n)


def orgs(envs): return [str(e.get("organisation_number")) for e in envs]
def statemap(envs): return {str(e.get("organisation_number")): e.get("status") for e in envs}
def claimset(e): return sorted((c.get("claim_key"), json.dumps(c.get("value"), sort_keys=True), c.get("availability")) for c in e.get("claims") or [])
def files_in(d):
    n = 0
    for _, _, fs in os.walk(d): n += len(fs)
    return n
def sec(e, name): return ((e.get("sections") or {}).get(name) or {})


SCEN = {}
def scenario(*rids):
    def w(f): SCEN[f.__name__] = (rids, f); return f
    return w


@scenario("R-1.3")
def input_formats(c):
    nums = [EQUINOR, UNKNOWN, INVALID_CD]
    runs = {
        "jsonl_org": [json.dumps({"organisation_number": n, "name": "x", "website": ""}) for n in nums],
        "jsonl_altkeys": [json.dumps({"orgnr": nums[0]}), json.dumps({"organization_number": nums[1]}), json.dumps({"organisasjonsnummer": nums[2]})],
        "text_spaces": ["", "923 609 016", "  908660242  ", "", "923609017", ""],
    }
    res = {}; ok = True
    for k, lines in runs.items():
        r = c.run("fmt_" + k, lines, ["--no-web"], fmt="text" if k.startswith("text") else "jsonl"); res[k] = (r["rc"], orgs(r["envs"]), [e.get("status") for e in r["envs"]])
    for k, arr in (("json_strings", nums), ("json_objects", [{"organisation_number": n} for n in nums])):
        r = c.run("fmt_" + k, arr, ["--no-web"], fmt="json"); res[k] = (r["rc"], orgs(r["envs"]), [e.get("status") for e in r["envs"]])
    expect = (0, nums, ["available", "not_available", "failed"])
    for k, v in res.items():
        if tuple(v) != expect and list(v) != list(expect): ok = False
    return ok, {"expected": expect, "got": res}


@scenario("R-1.4", "R-1.14", "R-1.15", "R-1.21", "R-1.8")
def mixed_hard_inputs(c):
    lines = [EQUINOR, INVALID_CD, "92360901", "92360901X", "ABCDEFGHI", UNKNOWN, DELETED, EQUINOR, "982463718", "923 609 016"]
    r = c.run("mixed", [json.dumps({"organisation_number": x}) for x in lines], ["--no-web", "--expected-count", str(len(lines))])
    good, txt = c.check(r)
    exp = ["available", "failed", "failed", "failed", "failed", "not_available", "not_available", "available", "available", "available"]
    got = [e.get("status") for e in r["envs"]]
    dup = [e for e in r["envs"] if str(e.get("organisation_number")) == EQUINOR]
    same = len({json.dumps(claimset(e)) for e in dup}) == 1
    return (r["rc"] == 0 and got == exp and good and same), {"rc": r["rc"], "expected": exp, "got": got,
            "duplicates_identical_claims": same, "checker": txt}


@scenario("R-1.9")
def resume_after_kill(c):
    rows = universe_sample(60, 424242)
    first = c.run("resume", rows, ["--workers", "4"], kill_after=25)
    n1 = len(first["envs"])
    second = c.run("resume", None, ["--workers", "4", "--resume"], fresh=False)
    second["input"] = os.path.join(second["dir"], "batch.jsonl")
    got = orgs(second["envs"]); exp = [json.loads(x)["organisation_number"] for x in rows]
    good, txt = c.check(second, oracle=False)
    return (second["rc"] == 0 and got == exp and good), {"killed_rc": first["rc"], "envelopes_at_kill": n1,
            "after_resume": len(got), "order_ok": got == exp, "dupes": len(got) - len(set(got)), "checker": txt[-800:]}


@scenario("R-1.10")
def time_budget(c):
    rows = universe_sample(80, 515151); budget = 20
    r = c.run("budget", rows, ["--time-budget-seconds", str(budget), "--workers", "2"])
    got = orgs(r["envs"]); exp = [json.loads(x)["organisation_number"] for x in rows]
    reasons = collections.Counter(e.get("status") for e in r["envs"])
    good, txt = c.check(r, oracle=False)
    return (r["rc"] == 0 and got == exp and r["wall_s"] <= budget + 10 and good), {"budget_s": budget, "wall_s": r["wall_s"],
            "rc": r["rc"], "n": len(got), "status": dict(reasons), "checker": txt[-600:]}


@scenario("R-1.11")
def per_company_timeout(c):
    rows = universe_sample(10, 626262)
    r = c.run("pctimeout", rows, ["--per-company-timeout", "0.3", "--workers", "3"])
    got = orgs(r["envs"]); exp = [json.loads(x)["organisation_number"] for x in rows]
    return (r["rc"] == 0 and got == exp), {"rc": r["rc"], "wall_s": r["wall_s"], "status": [e.get("status") for e in r["envs"]],
            "errors": [e.get("errors") for e in r["envs"]][:3]}


@scenario("R-1.7")
def batch_1100(c):
    rows = universe_sample(1100, 737373)
    r = c.run("b1100", rows, ["--no-web"])
    got = orgs(r["envs"]); exp = [json.loads(x)["organisation_number"] for x in rows]
    good, txt = c.check(r, oracle=False)
    return (r["rc"] == 0 and got == exp), {"rc": r["rc"], "wall_s": r["wall_s"], "n": len(got),
            "status": dict(collections.Counter(e.get("status") for e in r["envs"])), "report": r["report"], "checker": txt[-1500:]}


@scenario("R-1.44", "R-1.45", "R-1.17")
def idempotent_rerun(c):
    rows = universe_sample(15, 848484) + [json.dumps({"organisation_number": EQUINOR})]
    a = c.run("idem", rows, ["--no-web"])
    state = os.path.join(a["dir"], "state")
    sd = state if os.path.isdir(state) else a["dir"]
    n_files_1 = files_in(sd)
    shutil.copy(os.path.join(a["dir"], "envelopes.jsonl"), os.path.join(a["dir"], "envelopes.run1.jsonl"))
    b = c.run("idem", None, ["--no-web"], fresh=False); b["input"] = a["input"]
    n_files_2 = files_in(sd)
    changes = {str(e.get("organisation_number")): e.get("changes") for e in b["envs"] if e.get("changes")}
    # Claims that were available in run 1 must be identical in run 2 with the same first_observed_at.
    # (A source skipped in run 1, e.g. rate-limited filing years, may legitimately become available in run 2 —
    # verifier model correction after rev 2809cfe: such a first observation is not a change.)
    same = True; first_obs_stable = True; diffs = []
    for x, y in zip(a["envs"], b["envs"]):
        fy = {cl.get("claim_key"): cl for cl in y.get("claims") or []}
        for cl in x.get("claims") or []:
            if cl.get("availability") != "available": continue
            o = fy.get(cl.get("claim_key"))
            if not o or o.get("availability") != "available" or json.dumps(o.get("value"), sort_keys=True) != json.dumps(cl.get("value"), sort_keys=True):
                same = False; diffs.append((x.get("organisation_number"), cl.get("claim_key")))
            elif o.get("first_observed_at") != cl.get("first_observed_at"):
                first_obs_stable = False; diffs.append((x.get("organisation_number"), cl.get("claim_key"), "first_observed_at"))
    first_obs_present = any("first_observed_at" in cl for e in a["envs"] for cl in e.get("claims") or [])
    return (b["rc"] == 0 and not changes and same and first_obs_stable and first_obs_present and n_files_2 - n_files_1 <= 2), {
        "state_dir_exists": os.path.isdir(state), "files_run1": n_files_1, "files_run2": n_files_2,
        "changes_on_rerun": changes, "identical_claim_sets": same, "diffs": diffs[:10], "first_observed_at_present": first_obs_present,
        "first_observed_at_stable": first_obs_stable}


@scenario("R-1.46", "R-1.28")
def failed_refresh_no_removal(c):
    rows = [json.dumps({"organisation_number": EQUINOR}), json.dumps({"organisation_number": "982463718"})]
    a = c.run("failrefresh", rows, ["--no-web"])
    # second run with Brreg unreachable (dead proxy): must not report removals, must expose failure
    dead = {"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""}
    b = c.run("failrefresh", None, ["--no-web", "--per-company-timeout", "60"], env=dead, fresh=False); b["input"] = a["input"]
    removed = [ch for e in b["envs"] for ch in (e.get("changes") or []) if re.search(r"remov|closed|deleted", json.dumps(ch))]
    exposed = all(e.get("errors") or e.get("status") in ("blocked", "failed") for e in b["envs"])
    c3 = c.run("failrefresh", None, ["--no-web"], fresh=False)
    ch3 = [e.get("changes") for e in c3["envs"] if e.get("changes")]
    return (len(b["envs"]) == 2 and not removed and exposed and not ch3), {
        "offline_status": [e.get("status") for e in b["envs"]], "offline_rc": b["rc"], "removal_changes": removed[:5],
        "failure_exposed": exposed, "offline_errors": [e.get("errors") for e in b["envs"]][:2],
        "changes_after_recovery": ch3[:3]}


@scenario("R-1.4", "R-1.28")
def network_off(c):
    rows = universe_sample(8, 959595)
    dead = {"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""}
    r = c.run("netoff", rows, ["--per-company-timeout", "30"], env=dead, timeout=900)
    st = [e.get("status") for e in r["envs"]]
    return (r["rc"] == 0 and len(st) == 8 and all(s in ("blocked", "failed") for s in st)), {"rc": r["rc"], "status": st, "wall_s": r["wall_s"]}


@scenario("R-1.47", "R-1.12", "R-1.43", "R-1.48")
def llm_off_and_bogus_key(c):
    rows = [json.dumps({"organisation_number": EQUINOR}), json.dumps({"organisation_number": "982463718"})]
    a = c.run("llm_off", rows)
    cost0 = all((e.get("operations") or {}).get("third_party_cost_usd") == 0 for e in a["envs"])
    b = c.run("llm_bogus", rows, env={"ANTHROPIC_API_KEY": SECRET, "OPENAI_API_KEY": SECRET + "o", "BRAVE_API_KEY": SECRET + "b"})
    leak = []
    for root, _, fs in os.walk(b["dir"]):
        for f in fs:
            try:
                if SECRET in open(os.path.join(root, f), errors="ignore").read(): leak.append(f)
            except Exception: pass
    det = [(e.get("summary") or {}).get("generated_by") for e in b["envs"]]
    same_identity = [x.get("status") for x in a["envs"]] == [x.get("status") for x in b["envs"]] and \
        all(claimset(x) == claimset(y) for x, y in zip(a["envs"], b["envs"]))
    return (a["rc"] == 0 and cost0 and b["rc"] == 0 and len(b["envs"]) == 2 and not leak and same_identity
            and all(x == "deterministic" for x in det)), {"bogus_key_same_claims_as_no_key": same_identity,"no_key_rc": a["rc"], "cost_zero": cost0,
            "bogus_rc": b["rc"], "bogus_generated_by": det, "secret_leaked_in": leak,
            "bogus_status": [e.get("status") for e in b["envs"]]}


@scenario("R-1.45", "R-1.4")
def concurrent_same_state(c):
    """Repeated 6 times: the race is intermittent (verifier correction after 622da56: one trial is not evidence)."""
    trials = [concurrent_trial(c, i) for i in range(6)]
    return all(t[0] for t in trials), {"trials": [t[1] for t in trials], "failed_trials": sum(not t[0] for t in trials)}


def concurrent_trial(c, trial):
    rows = [json.dumps({"organisation_number": x}) for x in (EQUINOR, "982463718", "914778271")]
    d = os.path.join(c.work, f"concurrent{trial}"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    state = os.path.join(d, "state")
    procs = []
    for i in range(2):
        di = os.path.join(d, f"r{i}"); os.makedirs(di)
        open(os.path.join(di, "batch.jsonl"), "w").write("\n".join(rows) + "\n")
        procs.append(subprocess.Popen([c.py, "-m", "signalpost", "run", "--input", os.path.join(di, "batch.jsonl"),
            "--output", os.path.join(di, "envelopes.jsonl"), "--report", os.path.join(di, "report.json"),
            "--state-dir", state, "--no-web"], cwd=c.repo, stdout=open(os.path.join(di, "stdout.log"), "w"), stderr=subprocess.STDOUT))
    rcs = [p.wait(timeout=900) for p in procs]
    di = os.path.join(d, "r2"); os.makedirs(di)
    open(os.path.join(di, "batch.jsonl"), "w").write("\n".join(rows) + "\n")
    rc3 = subprocess.call([c.py, "-m", "signalpost", "run", "--input", os.path.join(di, "batch.jsonl"), "--output",
        os.path.join(di, "envelopes.jsonl"), "--report", os.path.join(di, "report.json"), "--state-dir", state, "--no-web"],
        cwd=c.repo, stdout=open(os.path.join(di, "stdout.log"), "w"), stderr=subprocess.STDOUT)
    e3 = load(os.path.join(di, "envelopes.jsonl"))
    ch = [e.get("changes") for e in e3 if e.get("changes")]
    return (rcs == [0, 0] and rc3 == 0 and len(e3) == 3 and not ch), {"concurrent_rcs": rcs, "third_rc": rc3, "third_changes": ch[:3],
            "counts": [len(load(os.path.join(d, f"r{i}", "envelopes.jsonl"))) for i in range(3)]}


# ---------------- website layer (needs webserve.py running and the test switch) ----------------
WEB_ENV_CANDIDATES = ["SIGNALPOST_ALLOW_PRIVATE_HOSTS", "SIGNALPOST_TEST_ALLOW_PRIVATE", "SIGNALPOST_ALLOW_PRIVATE_IPS"]


NOSITE = "925194336"  # READYSOFT AS: no hjemmeside, no e-mail in Brreg -> the fixture is the only declared candidate


def web_run(c, name, port, allow=True, extra=(), orgnr=EQUINOR):
    row = {"organisation_number": orgnr, "website": f"http://127.0.0.1:{port}/"}
    env = {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    if allow:
        v = os.environ.get("WEB_TEST_SWITCH", "SIGNALPOST_ALLOW_PRIVATE_HOSTS=127.0.0.1")
        k, _, val = v.partition("="); env[k] = val
    return c.run("web_" + name, [json.dumps(row)], list(extra), env=env)


def site_facts(e, marker):
    return marker in json.dumps(e.get("claims") or [], ensure_ascii=False)


@scenario("R-1.30", "R-1.31", "R-1.35", "R-1.36", "R-1.38", "R-1.40")
def web_verified(c):
    r = web_run(c, "verified", 8801); e = r["envs"][0] if r["envs"] else {}
    ws, hi = sec(e, "website_and_profiles"), sec(e, "hiring_and_activity")
    blob = json.dumps(e, ensure_ascii=False)
    ev = [x for x in e.get("evidence") or [] if "127.0.0.1:8801" in str(x.get("source_url"))]
    ev_ok = bool(ev) and all(x.get("source_class") == "company_owned" and x.get("content_sha256") and x.get("retrieved_at")
                             and (x.get("css_selector") or x.get("claim_span") or x.get("selector")) for x in ev)
    checks = {"website_available": ws.get("availability") == "available",
              "orgnr_proof_stored": "923 609 016" in blob or "923609016 MVA" in blob,
              "description": "VFX-DESC" in blob or "VFX-ORG" in blob,
              "social_linkedin": "linkedin.com/company/vfx-equinor" in blob,
              "social_facebook": "facebook.com/vfxequinor" in blob,
              "job_posting": "VFX-JOB" in blob and hi.get("availability") == "available",
              "job_date": "2026-09-01" in blob,
              "news_dated": "VFX-NEWS" in blob and "2026-09-15" in blob,
              "no_js_executed": "VFX-JS-EXECUTED" not in blob,
              "evidence_fields": ev_ok,
              "promo_labelled": "own description" in blob.lower() or "company's description" in blob.lower() or "self-description" in blob.lower() or "company_description" in blob}
    return all(checks.values()), {"checks": checks, "website_state": ws, "hiring_state": hi}


@scenario("R-1.31")
def web_name_address(c):
    r = web_run(c, "nameaddr", 8802); e = r["envs"][0] if r["envs"] else {}
    ws = sec(e, "website_and_profiles")
    return ws.get("availability") == "available" and site_facts(e, "VFX-NAMEADDR"), {"website_state": ws}


@scenario("R-1.31", "R-1.40")
def web_no_proof(c):
    r = web_run(c, "noproof", 8803); e = r["envs"][0] if r["envs"] else {}
    ws = sec(e, "website_and_profiles")
    leaked = site_facts(e, "VFX-NOPROOF") or site_facts(e, "vfx-noproof")
    return (not leaked), {"website_state": ws, "site_facts_published": leaked}


@scenario("R-1.32", "R-1.40")
def web_wrong_company(c):
    r = web_run(c, "wrongco", 8804); e = r["envs"][0] if r["envs"] else {}
    ws = sec(e, "website_and_profiles")
    leaked = site_facts(e, "VFX-WRONGCO") or site_facts(e, "vfx-wrongco")
    return (ws.get("availability") == "ambiguous" and not leaked), {"website_state": ws, "site_facts_published": leaked}


@scenario("R-1.33", "R-1.37", "R-1.40")
def web_robots(c):
    log = os.path.join(HERE, "logs", "webserve-requests.log"); before = open(log).read() if os.path.exists(log) else ""
    r = web_run(c, "robots", 8805, orgnr=NOSITE); e = r["envs"][0] if r["envs"] else {}
    after = open(log).read()[len(before):] if os.path.exists(log) else ""
    fetched = [l for l in after.splitlines() if " 8805 " in l]
    non_robots = [l for l in fetched if "/robots.txt" not in l]
    ws = sec(e, "website_and_profiles")
    return (ws.get("availability") == "blocked" and not non_robots and not site_facts(e, "VFX-ROBOTS")), {
        "website_state": ws, "requests_to_host": fetched[:10]}


@scenario("R-1.37")
def web_403_429_slow(c):
    out = {}
    for name, port, want in (("f403", 8808, {"blocked"}), ("f429", 8809, {"blocked"}), ("slow", 8807, {"failed", "not_available", "blocked"})):
        r = web_run(c, name, port, orgnr=NOSITE); e = r["envs"][0] if r["envs"] else {}
        out[name] = {"state": sec(e, "website_and_profiles").get("availability"), "reason": sec(e, "website_and_profiles").get("reason"),
                     "wall_s": r["wall_s"], "rc": r["rc"], "ok": sec(e, "website_and_profiles").get("availability") in want}
    return all(v["ok"] for v in out.values()), out


@scenario("R-1.34")
def web_private_ip_refused(c):
    log = os.path.join(HERE, "logs", "webserve-requests.log"); before = open(log).read() if os.path.exists(log) else ""
    r = web_run(c, "private_default", 8801, allow=False); e = r["envs"][0] if r["envs"] else {}
    r2 = web_run(c, "redirect_metadata", 8806); e2 = r2["envs"][0] if r2["envs"] else {}
    after = open(log).read()[len(before):] if os.path.exists(log) else ""
    hit_8801 = [l for l in after.splitlines() if " 8801 " in l]
    return (not hit_8801 and not site_facts(e, "VFX-") and not site_facts(e2, "meta-data")
            and sec(e2, "website_and_profiles").get("availability") != "available"), {
        "default_mode_requests_to_private_host": hit_8801[:5], "default_state": sec(e, "website_and_profiles"),
        "redirect_state": sec(e2, "website_and_profiles")}


@scenario("R-1.37")
def web_robots_candidate_recorded(c):
    """Robots-disallowed candidate must be visible in the website section even when another candidate also fails."""
    r = web_run(c, "robots_equinor", 8805)
    e = r["envs"][0] if r["envs"] else {}
    srcs = sec(e, "website_and_profiles").get("sources") or []
    rec = [x for x in srcs if "127.0.0.1:8805" in str(x.get("url"))]
    return bool(rec) and all(x.get("outcome") in ("blocked", "robots_disallowed") or "robots" in json.dumps(x) for x in rec), {
        "sources": srcs, "website_state": {k: v for k, v in sec(e, "website_and_profiles").items() if k != "sources"}}


@scenario("R-1.17", "R-1.45", "R-1.46")
def carried_forward_no_duplicate(c):
    """Company X fully researched; then re-run in a larger batch on the same state so the rate-limited filing-years
    endpoint is skipped for X. The envelope must still hold exactly one claim per claim_key."""
    x = "925536512"
    a = c.run("carryfwd", [x], ["--no-web", "--history-wait", "60"], fmt="text")
    rows = [json.loads(r)["organisation_number"] for r in universe_sample(45, 31337)] + [x]
    open(os.path.join(a["dir"], "batch2.txt"), "w").write("\n".join(rows) + "\n")
    d = a["dir"]
    rc = subprocess.call([c.py, "-m", "signalpost", "run", "--input", os.path.join(d, "batch2.txt"), "--output", os.path.join(d, "e2.jsonl"),
                          "--report", os.path.join(d, "r2.json"), "--state-dir", os.path.join(d, "state"), "--no-web", "--history-wait", "0"],
                         cwd=c.repo, stdout=open(os.path.join(d, "stdout2.log"), "w"), stderr=subprocess.STDOUT)
    dup = {}
    for e in load(os.path.join(d, "e2.jsonl")):
        cnt = collections.Counter(cl.get("claim_key") for cl in e.get("claims") or [])
        dd = [k for k, v in cnt.items() if v > 1]
        if dd: dup[e["organisation_number"]] = [(cl.get("claim_key"), cl.get("id"), cl.get("availability"), cl.get("carried_forward"))
                                                 for cl in e["claims"] if cl.get("claim_key") in dd]
    return rc == 0 and not dup, {"rc": rc, "duplicates": dup}


@scenario("R-1.23")
def status_flags(c):
    """Companies whose registry record has konkurs / underAvvikling / tvangsavvikling set: flags are claims and the
    summary states them prominently (checked by check_envelopes against the reference model)."""
    # The frozen universe has no flagged rows; these came from the live Brreg search API on 2026-09-29
    # (?konkurs=true, ?underAvvikling=true, ?underTvangsavviklingEllerTvangsopplosning=true).
    pick = [json.dumps({"organisation_number": o}) for o in ("935567645", "915330193", "812467182", "878684672", "931744682", "930078069")]
    r = c.run("flags", pick, ["--no-web"])
    good, txt = c.check(r)
    cj = loadj(os.path.join(r["dir"], "checks.json")) or {"checks": {}}
    r23 = cj["checks"].get("R-1.23") or {"pass": False, "n_checked": 0}
    return (r["rc"] == 0 and r23["pass"] and r23["n_checked"] > 0), {"n": len(pick), "r_1_23": r23, "orgnrs": [json.loads(x)["organisation_number"] for x in pick],
            "checker": txt[-1500:]}


@scenario("R-1.4", "R-1.8", "R-1.45")
def concurrent_three_runs(c):
    """Three real runs started together on one state dir, 4 trials; then a 4th run must report 0 changes."""
    rows = [json.dumps({"organisation_number": x}) for x in (EQUINOR, "982463718", "914778271", "925194336")]
    res = []
    for t in range(4):
        d = os.path.join(c.work, f"conc3_{t}"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        state = os.path.join(d, "state"); procs = []
        for i in range(3):
            di = os.path.join(d, f"r{i}"); os.makedirs(di); open(os.path.join(di, "b.jsonl"), "w").write("\n".join(rows) + "\n")
            procs.append(subprocess.Popen([c.py, "-m", "signalpost", "run", "--input", os.path.join(di, "b.jsonl"), "--output",
                os.path.join(di, "e.jsonl"), "--report", os.path.join(di, "r.json"), "--state-dir", state, "--no-web"],
                cwd=c.repo, stdout=open(os.path.join(di, "stdout.log"), "w"), stderr=subprocess.STDOUT))
        rcs = [p.wait(timeout=900) for p in procs]
        counts = [len(load(os.path.join(d, f"r{i}", "e.jsonl"))) for i in range(3)]
        di = os.path.join(d, "r3"); os.makedirs(di); open(os.path.join(di, "b.jsonl"), "w").write("\n".join(rows) + "\n")
        rc4 = subprocess.call([c.py, "-m", "signalpost", "run", "--input", os.path.join(di, "b.jsonl"), "--output", os.path.join(di, "e.jsonl"),
            "--report", os.path.join(di, "r.json"), "--state-dir", state, "--no-web"], cwd=c.repo, stdout=open(os.path.join(di, "stdout.log"), "w"), stderr=subprocess.STDOUT)
        e4 = load(os.path.join(di, "e.jsonl"))
        ok = rcs == [0, 0, 0] and counts == [4, 4, 4] and rc4 == 0 and len(e4) == 4 and not any(e.get("changes") for e in e4)
        res.append({"ok": ok, "rcs": rcs, "counts": counts, "fourth_rc": rc4, "fourth_changes": [e.get("changes") for e in e4 if e.get("changes")][:2]})
    return all(r["ok"] for r in res), {"trials": res}


@scenario("R-1.4", "R-1.8")
def state_store_unavailable(c):
    """--state-dir points at an unusable location (a regular file). The run must still emit one terminal envelope per
    input (lead 00028 item 4: research without the store, or `failed` with reason state_store_unavailable)."""
    d = os.path.join(c.work, "nostore"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    bad = os.path.join(d, "not-a-dir"); open(bad, "w").write("x")
    r = c.run("nostore_run", [json.dumps({"organisation_number": x}) for x in (EQUINOR, "982463718")], ["--no-web", "--state-dir", bad])
    st = [e.get("status") for e in r["envs"]]
    why = [((e.get("sections") or {}).get("refresh_and_changes") or {}).get("reason") for e in r["envs"]] + [e.get("errors") for e in r["envs"]]
    # lead 00030: every envelope names it in sections.refresh_and_changes.reason AND errors; the report records it
    each = all("state_store_unavailable" in str(((e.get("sections") or {}).get("refresh_and_changes") or {}).get("reason"))
               and "state_store_unavailable" in json.dumps(e.get("errors")) for e in r["envs"])
    rep = "state_store" in json.dumps(r["report"] or {}) and "unavailable" in json.dumps(r["report"] or {})
    ok = r["rc"] == 0 and len(r["envs"]) == 2 and each and rep
    return ok, {"rc": r["rc"], "status": st, "each_envelope_names_it": each, "report_records_it": rep, "reasons": json.dumps(why)[:600]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--only"); ap.add_argument("--skip", default=""); a = ap.parse_args()
    c = Ctx(os.path.abspath(a.repo), a.tag)
    names = a.only.split(",") if a.only else [n for n in SCEN if n not in a.skip.split(",")]
    outp = os.path.join(HERE, "logs", a.tag, "scenarios.json"); os.makedirs(os.path.dirname(outp), exist_ok=True)
    results = loadj(outp) or {}
    for n in names:
        rids, f = SCEN[n]; t = time.time()
        try:
            ok, detail = f(c)
        except Exception:
            ok, detail = False, {"error": traceback.format_exc()[-2000:]}
        results[n] = {"ledger": list(rids), "pass": bool(ok), "seconds": round(time.time() - t, 1), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {n} {rids} ({results[n]['seconds']}s)", flush=True)
        json.dump(results, open(outp, "w"), indent=1, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
