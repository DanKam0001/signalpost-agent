# 100-company smoke test

- **Sample:** 100 organisation numbers drawn from the public universe
  `https://builderr.ai/signalpost-company-universe-2025.jsonl.gz` (archive SHA-256
  `1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384`), rows sorted by
  organisation number, then `random.Random(20260929).sample(rows, 100)` — **seed 20260929**
  (`signalpost/selfscore.py:sample`).
- **Run date:** 2026-09-29, from the development sandbox (reaches data.brreg.no; company websites
  are blocked by the sandbox's own egress policy, so most website sections read
  `failed — this run's own network policy blocked outbound access` or `not_available`).
- **Command** (the single run command, default options):
  `.venv/bin/python -m signalpost run --input smoke/input.jsonl --output envelopes.jsonl --report report.json`
  (executed through `python -m signalpost selfscore --input smoke/input.jsonl --seed 20260929 --out out/smoke`,
  which runs it twice on the same state to check idempotency).

| File | Content |
|---|---|
| `input.jsonl` | the 100 sampled universe rows |
| `envelopes.jsonl` | 100 envelopes, one per input, in input order |
| `report.json` | run report of the first run |
| `rerun-report.json` | run report of the second run on the same state (`changes_total: 0`) |
| `selfscore.json`, `selfscore.md` | coverage, evidence completeness, idempotency, runtime, rubric estimate |

Result (regenerated at revision 3, code commit 40fcb27): 100 envelopes for 100 inputs; all 100
`available`; 46.9 s total, p50 2.6 s, p95 6.3 s per company, 514 requests, peak memory 60 MB,
third-party cost $0; `state_store: ok`; filing-years list fetched for 22 companies within Brreg's
~30/min limit (78 carry one `blocked` claim naming that limit); second run on the same state:
0 changes, no duplicate claims.
Browse it: `.venv/bin/python -m signalpost serve --batch smoke/envelopes.jsonl` → `/batch`.
