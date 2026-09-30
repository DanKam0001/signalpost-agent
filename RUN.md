# Running Signalpost

Everything below is run from the repository root. No API key, account or LLM is needed.

## 1. Install (the one declared install step)

Requires Python ≥ 3.11 with `venv` and `pip` available (any normal CPython install).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

All dependencies are pinned with `==` in `requirements.txt` (httpx, beautifulsoup4 and their
pinned transitive dependencies).

If your system Python lacks `ensurepip` (some minimal Debian/Ubuntu images), either install the
`python3-venv` package, put a uv-managed CPython first on `PATH`
(`uv python install 3.12 && ln -sf "$(uv python find 3.12)" ~/bin/python3`), or use Docker (§6).

## 2. Run a batch (the single run command)

```bash
.venv/bin/python -m signalpost run --input <batch file> --output <envelopes.jsonl> --report <report.json>
```

Example with the committed smoke input:

```bash
.venv/bin/python -m signalpost run --input smoke/input.jsonl --output out/envelopes.jsonl --report out/report.json
```

- Input: JSONL rows with `organisation_number` (also `orgnr`, `organization_number`,
  `organisasjonsnummer`) — exactly the public-universe row shape — or a JSON array (of objects or
  strings), or plain text with one number per line. `923 609 016` style spacing is fine; `.gz` is
  read transparently. A row's `website` field, if present, is treated as a website *candidate*.
- Output: one envelope per input line, in input order (JSONL, UTF-8). Invalid numbers, unknown or
  deleted companies, refusals, crashes and timeouts all still get an envelope.
- Exit code 0 when the envelope count equals the input count (it always tries to emit a `failed`
  envelope rather than drop one); 2 otherwise.

Options:

| Option | Default | Meaning |
|---|---|---|
| `--state-dir DIR` | `<output dir>/state` | persistent snapshots, claim store, checkpoints |
| `--run-id ID` | generated | name of the run (checkpoint key) |
| `--workers N` | 8 | companies researched concurrently |
| `--time-budget-seconds S` | none | finish inside S seconds: deep research stops early, remaining companies get a registry-only fast path or a `failed` envelope with `time_budget_exhausted` |
| `--per-company-timeout S` | 90 | wall-clock limit per company |
| `--resume` | off | continue an interrupted run of the same input (same state dir) without redoing or duplicating companies |
| `--expected-count N` | none | recorded in the report as `expected_count` / `count_matches_expected` |
| `--registry-snapshot FILE` | none | frozen Brreg bulk file (JSON array, JSONL or CSV, optionally gzipped) used to anchor identity if the live API fails |
| `--no-web` | off | registry sources only |
| `--site-delay S` | 0.5 | minimum seconds between requests to one company website |
| `--history-wait S` | 5 | Brreg limits the annual-account copy index to ~30 requests/min. The filing-years lane runs alongside all other research and is kept saturated at that limit for the whole run; a company waits at most S seconds for a slot, otherwise it gets exactly one `filing_years` claim, `blocked`, reason "Brønnøysund limits this endpoint to about 30 requests per minute; not fetched for this company in this run" (or, if an earlier run in the same state dir obtained the list, the carried-forward list with `refresh_status`). Raise S (e.g. 60) for full history on small batches |

### Run report (`--report`)

Flat JSON with at least: `input_count`, `envelope_count`, `expected_count`, `duplicate_inputs`,
`state_counts`, `runtime_ms_total`, `runtime_ms_p50`, `runtime_ms_p95`, `requests_total`,
`requests_by_host`, `bytes_fetched`, `peak_memory_mb`, `third_party_cost_usd`,
`time_budget_seconds`, `fast_path_count`, `run_id`, `started_at`, `completed_at`, plus
`section_state_counts`, `requests_by_source`, `count_matches_input`, change totals, and
`filing_years_fetched` / `filing_years_skipped` (Brreg's ~30/min filing-years limit, see below).

### Resume after an interruption

Every finished company is committed to `<state-dir>/state.db` in one transaction together with its
envelope. Re-run the same command with `--resume` (same input, same state dir):

```bash
.venv/bin/python -m signalpost run --input in.jsonl --output out/envelopes.jsonl --report out/report.json --resume
```

## 3. Web UI

```bash
.venv/bin/python -m signalpost serve --host 0.0.0.0 --port 8000
# optionally browse a batch result:
.venv/bin/python -m signalpost serve --host 0.0.0.0 --port 8000 --batch smoke/envelopes.jsonl
```

| URL | What |
|---|---|
| `/` | lookup form (validates number, length and check digit) → `/company/{orgnr}` |
| `/company/{orgnr}` | live profile; `?source=batch` shows the loaded batch envelope instead |
| `/compare?orgnr=A&orgnr=B` (or `/compare?orgnrs=A,B`) | 2–4 companies side by side |
| `/batch` | batch browser: search by name/number, filter by state, open profiles; can also open a local envelopes JSONL in the browser |
| `/api/company/{orgnr}` | the envelope as JSON (`?refresh=1` re-researches) |
| `/snapshot/{sha256}` | a stored raw source snapshot, always served as plain text |

Each rendered fact carries `data-claim-id`; its source link carries `data-evidence-id`. Hovering or
focusing a fact shows its source URL, JSON pointer or CSS selector, dates and content hash in the
Source panel. Live lookups keep state in `--state-dir` (default `data/ui-state`), so a later
refresh shows what changed.

## 4. Tests (offline)

```bash
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q
```

The suite uses saved Brreg responses (`tests/fixtures/brreg/`) and saved HTML sites
(`tests/fixtures/sites/`); one test starts a local HTTP server on 127.0.0.1 to check URL safety.

## 5. Refresh replay and self-score

```bash
# two saved snapshots → expected typed changes; third identical pass → zero changes
.venv/bin/python -m signalpost replay --fixtures tests/fixtures/replay --output out/replay.json

# sample N companies from the public universe (seeded), run twice, score
.venv/bin/python -m signalpost selfscore --universe https://builderr.ai/signalpost-company-universe-2025.jsonl.gz --count 100 --seed 20260929 --out out/selfscore
```

`replay` writes a JSON array with one object per pass; each change has `type`, `claim_key`,
`previous`, `current`, `evidence` (`previous` = the preserved earlier evidence records,
`current` = evidence ids and URLs) and `materiality`.

## 6. Docker

```bash
docker build -t signalpost .
docker run --rm -v "$PWD/out:/out" -v "$PWD/smoke:/in:ro" signalpost \
  run --input /in/input.jsonl --output /out/envelopes.jsonl --report /out/report.json
docker run --rm -p 8000:8000 signalpost          # web UI on http://localhost:8000/
```

The image installs every dependency and runs the test suite at build time; at run time it only
needs network access to data.brreg.no and company websites.

## 7. Environment variables

| Variable | Purpose |
|---|---|
| `SIGNALPOST_ALLOW_PRIVATE_HOSTS` | **tests only.** Comma-separated hosts or `host:port` pairs (e.g. `127.0.0.1:8801`) exempt from the private-address refusal. Unset (default): every private, loopback, link-local or metadata address is refused and never requested. Set: only the listed hosts are allowed; any other private address — including a redirect target such as `169.254.169.254` — is still refused. There is no global off switch. |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | honoured by the HTTP client if your network needs a proxy |

No other variable is read. No secret is needed; none is logged or written to outputs.
