#!/usr/bin/env python3
"""Download the public universe (sha256-checked, cached, never committed) and write a random sample.
usage: sample.py --count N --seed S --out batch.jsonl [--format jsonl|json|text]"""
import argparse, gzip, hashlib, json, os, random, urllib.request
URL = "https://builderr.ai/signalpost-company-universe-2025.jsonl.gz"
SHA = "1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "universe.jsonl.gz")

def universe():
    if not os.path.exists(CACHE):
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        urllib.request.urlretrieve(URL, CACHE + ".part"); os.replace(CACHE + ".part", CACHE)
    h = hashlib.sha256(open(CACHE, "rb").read()).hexdigest()
    assert h == SHA, f"universe sha mismatch {h}"
    return CACHE

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--format", default="jsonl"); a = ap.parse_args()
    rows = [l for l in gzip.open(universe(), "rt", encoding="utf-8") if l.strip()]
    pick = random.Random(a.seed).sample(rows, a.count)
    with open(a.out, "w", encoding="utf-8") as f:
        if a.format == "jsonl": f.writelines(pick)
        elif a.format == "json": json.dump([json.loads(r)["organisation_number"] for r in pick], f)
        else: f.write("\n".join(json.loads(r)["organisation_number"] for r in pick) + "\n")
    print(f"wrote {a.count} rows seed={a.seed} -> {a.out}")
