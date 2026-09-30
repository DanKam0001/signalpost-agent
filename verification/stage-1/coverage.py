#!/usr/bin/env python3
"""Assemble the ledger coverage table for one tested commit from every log under logs/<tag>/ and the acceptance log.
usage: coverage.py --tag TAG --acceptance logs/acceptance-... > logs/TAG/coverage.md
A ledger entry with no executed check, or whose check errored, is FAIL."""
import argparse, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
IDS = [f"R-1.{i}" for i in range(1, 67)]; IDS.insert(IDS.index("R-1.47"), "R-1.46a")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--tag", required=True); ap.add_argument("--acceptance", required=True); a = ap.parse_args()
    L = os.path.join(HERE, "logs", a.tag); acc = os.path.join(HERE, a.acceptance) if not os.path.isabs(a.acceptance) else a.acceptance
    res = {i: [] for i in IDS + ["WRONG-COMPANY", "FABRICATION", "DIFFERENTIAL"]}
    def add(rid, ok, where, note=""):
        res.setdefault(rid, []).append((bool(ok), where, note))
    def J(p):
        try: return json.load(open(p))
        except Exception: return None
    ck = J(os.path.join(acc, "checks.json")); tm = J(os.path.join(acc, "time.json")); ev = J(os.path.join(acc, "evidence.json"))
    if ck:
        for rid, r in ck["checks"].items(): add(rid, r["pass"], f"{acc}/checks.json", f"{r['n_checked']} checked; " + "; ".join(r["failures"][:2]))
        full = tm and tm["exit_code"] == 0 and ck["n_inputs"] == ck["n_envelopes"]
        add("R-1.58", full and all(ck["checks"][k]["pass"] for k in ("R-1.4", "R-1.5", "R-1.14", "R-1.15")), f"{acc}/acceptance.log", f"rc={tm and tm['exit_code']} n={ck['n_inputs']}/{ck['n_envelopes']}")
        add("R-1.6", full and ck["status_distribution"].get("available", 0) >= 0.95 * ck["n_inputs"], f"{acc}/checks.json", str(ck["status_distribution"]))
    else:
        add("R-1.58", False, acc, "acceptance did not produce checks")
    if ev: add("R-1.18", ev["pass"], f"{acc}/evidence.json", json.dumps(ev["stats"]))
    sc = J(os.path.join(L, "scenarios.json")) or {}
    for n, r in sc.items():
        for rid in r["ledger"]: add(rid, r["pass"], f"{L}/scenarios.json#{n}")
    df = J(os.path.join(L, "differential.json"))
    add("DIFFERENTIAL", bool(df and df["pass"]), f"{L}/differential.json", f"{len(df['findings'])} findings" if df else "not run")
    if df: add("R-1.45", df["pass"], f"{L}/differential.json")
    for f in ("repo_checks.json", "ui/ui.json"):
        for rid, r in (J(os.path.join(L, f)) or {}).items():
            add(rid, r["pass"], f"{L}/{f}", "; ".join(i["check"] for i in r["items"] if not i["pass"])[:200])
    n_pass = 0
    print(f"| Entry | Result | Evidence | Notes |\n|---|---|---|---|")
    for rid in res:
        rs = res[rid]
        ok = bool(rs) and all(x[0] for x in rs)
        if rid.startswith("R-"): n_pass += ok
        notes = " / ".join(x[2] for x in rs if not x[0])[:300] if rs else "no check executed"
        print(f"| {rid} | {'PASS' if ok else 'FAIL'} | {', '.join(sorted({os.path.relpath(x[1], HERE) for x in rs}))} | {notes.replace('|', '/')} |")
    print(f"\nCoverage: {n_pass}/{len(IDS)} ledger entries with a passing check.")

if __name__ == "__main__":
    main()
