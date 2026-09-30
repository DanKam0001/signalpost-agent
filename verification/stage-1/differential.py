#!/usr/bin/env python3
"""Differential runs: random batches of valid and invalid operations replayed against the product and the
reference model (lib/brreg.model), sharing ONE state dir across batches so cross-run invariants are checked:
  I1 one envelope per input, in order;  I2 envelope status == reference status;
  I3 a company seen in an earlier batch reports zero changes when its registry record is unchanged
     (content_sha256 of the entity snapshot identical) — no false changes;
  I4 claim_key set of a company is identical between batches when snapshots are identical;
  I5 first_observed_at of a claim never moves; I6 all check_envelopes checks pass.
usage: differential.py --repo CLONE --tag TAG [--batches 6] [--size 20] [--seed 777]"""
import argparse, json, os, random, shutil, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib")); sys.path.insert(0, HERE)
from brreg import check_digit  # noqa
from scenarios import universe_sample, load  # noqa


def mutate(rnd, o):
    k = rnd.randrange(6)
    if k == 0: return o[:8] + str((int(o[8]) + 1 + rnd.randrange(8)) % 10)          # bad check digit
    if k == 1: return o[:8]                                                         # 8 digits
    if k == 2: return o[:4] + "X" + o[5:]                                           # letter
    if k == 3: return o[:3] + " " + o[3:6] + " " + o[6:]                            # spaced (valid)
    if k == 4:                                                                       # random valid-checksum number (likely 404)
        while True:
            b = "1" + "".join(rnd.choice("0123456789") for _ in range(7)); c = check_digit(b)
            if c is not None: return b + str(c)
    return o + "0"                                                                   # 10 digits


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--batches", type=int, default=6); ap.add_argument("--size", type=int, default=20); ap.add_argument("--seed", type=int, default=777)
    a = ap.parse_args(); rnd = random.Random(a.seed)
    base = os.path.join(HERE, "runs", a.tag, "differential"); shutil.rmtree(base, ignore_errors=True); os.makedirs(base)
    state = os.path.join(base, "state")
    pool = [json.loads(x)["organisation_number"] for x in universe_sample(a.size * a.batches // 2, a.seed)] + ["923609016", "921326904"]
    seen = {}   # orgnr -> (entity snapshot sha, claim keys, first_observed map)
    findings = []; inv = collections.Counter()
    for bi in range(a.batches):
        items = []
        for _ in range(a.size):
            r = rnd.random(); o = rnd.choice(pool)
            items.append(o if r < 0.7 else mutate(rnd, o) if r < 0.9 else rnd.choice(pool[:5]))  # 10%: repeats
        fmt = rnd.choice(["jsonl", "json", "text"])
        d = os.path.join(base, f"b{bi}"); os.makedirs(d)
        inp = os.path.join(d, "batch." + {"jsonl": "jsonl", "json": "json", "text": "txt"}[fmt])
        with open(inp, "w") as f:
            if fmt == "jsonl": f.write("\n".join(json.dumps({"organisation_number": x}) for x in items) + "\n")
            elif fmt == "json": json.dump(items, f)
            else: f.write("\n".join(items) + "\n")
        rc = subprocess.call([os.path.join(a.repo, ".venv/bin/python"), "-m", "signalpost", "run", "--input", inp, "--output",
                              os.path.join(d, "e.jsonl"), "--report", os.path.join(d, "r.json"), "--state-dir", state, "--no-web",
                              "--run-id", f"diff-{bi}"], cwd=a.repo, stdout=open(os.path.join(d, "stdout.log"), "w"), stderr=subprocess.STDOUT)
        envs = load(os.path.join(d, "e.jsonl"))
        ck = subprocess.run([sys.executable, os.path.join(HERE, "check_envelopes.py"), "--input", inp, "--output", os.path.join(d, "e.jsonl"),
                             "--report", os.path.join(d, "r.json"), "--oracle", "--out", os.path.join(d, "checks.json")], capture_output=True, text=True)
        inv["batches"] += 1
        if rc != 0: findings.append({"batch": bi, "problem": f"exit {rc}", "input": inp})
        if ck.returncode != 0:
            cj = json.load(open(os.path.join(d, "checks.json")))
            findings.append({"batch": bi, "problem": "check_envelopes failed", "fails": {k: v["failures"][:3] for k, v in cj["checks"].items() if not v["pass"]}})
        within = {}
        for e in envs:
            o = str(e.get("organisation_number")); inv["envelopes"] += 1
            if e.get("status") != "available": continue
            ent = [x for x in e.get("evidence") or [] if str(x.get("source_url", "")).rstrip("/").endswith(f"/enheter/{o}")]
            sha = ent[0].get("content_sha256") if ent else None
            keys = sorted(c.get("claim_key") for c in e.get("claims") or [])
            fo = {c.get("claim_key"): c.get("first_observed_at") for c in e.get("claims") or []}
            if o in seen and o not in within:
                psha, pkeys, pfo = seen[o]
                inv["repeat_observations"] += 1
                if sha and sha == psha:
                    if e.get("changes"):
                        findings.append({"batch": bi, "orgnr": o, "invariant": "I3 false change on identical snapshot", "changes": e["changes"][:3]})
                    if keys != pkeys:
                        findings.append({"batch": bi, "orgnr": o, "invariant": "I4 claim keys differ on identical snapshot",
                                         "added": sorted(set(keys) - set(pkeys))[:5], "removed": sorted(set(pkeys) - set(keys))[:5]})
                for k, v in fo.items():
                    if k in pfo and pfo[k] and v != pfo[k]:
                        findings.append({"batch": bi, "orgnr": o, "invariant": "I5 first_observed_at moved", "claim_key": k, "was": pfo[k], "now": v}); break
            within[o] = True
            seen[o] = (sha, keys, fo)
        print(f"batch {bi} fmt={fmt} n={len(items)} rc={rc} checks={'ok' if ck.returncode == 0 else 'FAIL'}", flush=True)
    out = {"seed": a.seed, "invariant_counts": dict(inv), "findings": findings, "pass": not findings}
    os.makedirs(os.path.join(HERE, "logs", a.tag), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "logs", a.tag, "differential.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "findings"}), "findings:", len(findings))
    for f in findings[:10]: print(" ", json.dumps(f, default=str)[:400])
    sys.exit(0 if not findings else 1)


if __name__ == "__main__":
    main()
