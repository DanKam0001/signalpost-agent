# Stage 1 verification harness (@verifier)

Built from `ledger/stage-1.md` and `docs/official/` only — not from the product code or its tests.

| File | What it is |
|---|---|
| `lib/brreg.py` | Reference model: independent stdlib Brreg client (enheter, roller, underenheter, regnskap, aar) → expected status + facts; mod-11 check; JSON-pointer resolver. |
| `lib/inputs.py` | Reference reading of the input formats (R-1.3). |
| `sample.py` | Download public universe (sha256-checked, cached in `.cache/`, never committed) and draw a seeded sample. |
| `check_envelopes.py` | Per-envelope checks named by ledger id + oracle comparison (legal name, form, address, NACE, employees, CEO/chair, accounts exact values/currency/period, filed years, subunit count, flags), WRONG-COMPANY and FABRICATION blockers. |
| `check_evidence.py` | Samples ≥200 evidence records, fetches `source_url` live (must be 200), resolves `json_pointer`, compares with the claim. |
| `acceptance.sh` | R-1.58 official procedure: clean clone at commit → new folder → empty venv → declared install step only → single run command on 100 random universe companies (verifier seed 73101). |
| `scenarios.py` | Failure conditions: input formats, invalid/404/410/duplicates, kill+resume, time budget, per-company timeout, 1,100 batch, idempotent rerun, failed refresh (no false removals), network off, LLM off/bogus key (no leak), concurrent runs on one state dir, website fixtures (verified / name+address / no proof / wrong company / robots / 403 / 429 / slow / private IP / redirect to metadata IP). |
| `differential.py` | Random mixed batches against product + reference model with a shared state dir; cross-run invariants I1–I6. |
| `repo_checks.py` | Pinned deps, docs, LICENSE, RUN.md, pytest offline, replay, registry snapshot, self-score, committed smoke result, SUBMIT email, Docker build/run (2 CPU/2 GB, and `--network none`). |
| `ui_checks.py` | Headless Chromium at 1280 and 375 px: lookup, states, sections/badges, source links + pointers, hover highlight, compare, batch browser, noopener, tap targets, no horizontal scroll. Run with `.cache/vvenv/bin/python`. |
| `webserve.py`, `fixtures/web/` | Local fixture sites (ports 8801–8809). Private-host test switch: `WEB_TEST_SWITCH=NAME=value` (default `SIGNALPOST_ALLOW_PRIVATE_HOSTS=127.0.0.1`). |
| `coverage.py`, `run_all.sh` | Everything for one commit → `logs/<commit10>/coverage.md`. |

Sandbox note: the system `python3` (3.14) has no `ensurepip`, so `python3 -m venv` fails here. `acceptance.sh` puts a
clean uv-managed CPython 3.12 first on PATH as `python3` (`.cache/pyshim`) and then runs the declared install step
verbatim. Setup: `ln -sf "$(uv python find 3.12)" .cache/pyshim/python3`; UI venv: `.cache/vvenv` with `playwright`.

Known Brreg test numbers (probed 2026-09-29): 923609016 Equinor (available, USD accounts, 35 subunits);
982463718 Telenor; 908660242 → 404; 921326904 → 410 (slettedato 2019-06-18); 923609017 bad check digit.
