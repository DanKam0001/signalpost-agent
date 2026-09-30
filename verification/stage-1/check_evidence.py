#!/usr/bin/env python3
"""Evidence validity (R-1.18, R-1.36; ledger item 4): sample evidence records, fetch source_url live,
require HTTP 200, resolve the JSON pointer in the fetched record and compare with the claimed value.

usage: check_evidence.py --output ENVELOPES.jsonl [--sample 250] [--seed 11] [--out RESULT.json]
"""
import argparse, hashlib, json, os, random, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from brreg import fetch, resolve_pointer  # noqa


def leaves(v):
    if isinstance(v, dict):
        for x in v.values(): yield from leaves(x)
    elif isinstance(v, list):
        for x in v: yield from leaves(x)
    elif v is not None:
        yield v


def matches(pointed, claimed):
    """Claimed value is supported by the pointed-at field: equal, or every scalar leaf of one found in the other."""
    if pointed == claimed:
        return True
    pl = {str(x).strip().lower() for x in leaves(pointed)}
    cl = {str(x).strip().lower() for x in leaves(claimed)}
    num = lambda s: {float(x) for x in s if x.replace('.', '', 1).replace('-', '', 1).isdigit()}
    if cl and (cl <= pl or pl <= cl):
        return True
    if num(pl) and num(pl) & num(cl):
        return True
    # string containment (e.g. pointer to a person object vs claimed "First Last")
    sp = " ".join(sorted(pl)); sc = " ".join(sorted(cl))
    return bool(sc) and (sc in sp or sp in sc or all(t in sp for t in sc.split()))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--output", required=True)
    ap.add_argument("--sample", type=int, default=250); ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out"); a = ap.parse_args()
    pool = []
    for line in open(a.output, encoding="utf-8"):
        if not line.strip(): continue
        env = json.loads(line)
        ev = {e["id"]: e for e in env.get("evidence") or [] if "id" in e}
        for c in env.get("claims") or []:
            if c.get("availability") != "available": continue
            for eid in c.get("evidence_ids") or []:
                if eid in ev:
                    pool.append((env["organisation_number"], c, ev[eid]))
    rnd = random.Random(a.seed)
    sample = rnd.sample(pool, min(a.sample, len(pool)))
    stats = collections.Counter(); fails = []
    for o, c, e in sample:
        u = e.get("source_url", "")
        st, body = fetch(u, use_cache=False) if u.startswith("http") else (0, b"")
        stats[f"http_{st}"] += 1
        if st != 200:
            fails.append({"orgnr": o, "url": u, "problem": f"HTTP {st}"}); continue
        if hashlib.sha256(body).hexdigest() == e.get("content_sha256"):
            stats["sha_equal_live"] += 1
        ptr = e.get("json_pointer")
        if ptr is None:
            stats["no_json_pointer"] += 1; continue
        try:
            doc = json.loads(body)
            val = resolve_pointer(doc, ptr)
        except Exception as ex:
            stats["pointer_unresolved"] += 1
            fails.append({"orgnr": o, "url": u, "pointer": ptr, "problem": f"pointer does not resolve: {ex}"}); continue
        if matches(val, c.get("value")):
            stats["pointer_value_match"] += 1
        else:
            stats["pointer_value_mismatch"] += 1
            fails.append({"orgnr": o, "field": c.get("field"), "url": u, "pointer": ptr,
                          "claimed": c.get("value"), "at_pointer": val, "problem": "value differs"})
    out = {"pool": len(pool), "sampled": len(sample), "stats": dict(stats), "failures": fails[:100],
           "pass": len(sample) >= min(200, len(pool)) and not [f for f in fails if f["problem"] != "value differs"]
                   and stats["pointer_value_mismatch"] == 0}
    print(json.dumps({k: v for k, v in out.items() if k != "failures"}, indent=1))
    for f in fails[:15]: print(" ", json.dumps(f, ensure_ascii=False, default=str)[:300])
    if a.out: json.dump(out, open(a.out, "w"), indent=1, ensure_ascii=False, default=str)
    sys.exit(0 if out["pass"] else 1)


if __name__ == "__main__":
    main()
