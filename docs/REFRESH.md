# Refresh model

State lives in `--state-dir` (default `<output dir>/state`):

- `snapshots/<sha[:2]>/<sha256>` — immutable raw responses, content-addressed (a re-fetch of
  identical content adds nothing);
- `state.db` (SQLite): `snapshots`, `fetches` (URL × hash with first/last retrieval), `claims`
  (one row per `claim_key` × value hash with `first_observed_at`, `last_observed_at`,
  `is_current`, `superseded_at` — earlier values and their evidence are kept, never overwritten),
  `companies`, `change_log`, `runs`, `run_envelopes` (checkpoints for `--resume`).

Each company is committed in one transaction. Several processes (e.g. two batch runs, or the UI
and a batch) may share one state directory: opening waits and retries while another process holds
the database (busy timeout plus retry with backoff, up to 60 s; if WAL mode cannot be set the store
continues in its current journal mode), and every write transaction is retried the same way. If
the store still cannot be opened — including a `--state-dir` that is a regular file — the run
emits a `failed` envelope (`state_store_unavailable`, in `errors` and in the
`refresh_and_changes` reason) for every input plus the run report (`state_store: "unavailable"`),
and exits 0 because the envelope count matches the input. On every run:

- same value → only `last_observed_at` moves (idempotent: no new snapshot, claim or change);
- a value changes → the old version is superseded and a typed change is emitted;
- a new claim key → `new_*` change (not on the first observation, which reports "first
  observation");
- a claim key disappears **and its source was fetched successfully this run** → `removed_*` /
  `closed_*` change; if the source failed, the last supported value is carried forward
  (`carried_forward: true`) and the failure is shown — a failed fetch never reports a removal.

Change types: `changed_name`, `changed_address`, `changed_employees`, `status_change`,
`changed_legal_form`, `new_role`, `removed_role`, `changed_role`, `new_location`,
`closed_location`, `changed_location`, `changed_location_count`, `new_filing` (a new accounts
period; its individual account lines are not repeated), `changed_financials` (restated values for
the same period), `changed_filing_history`, `changed_industry`, `new_website`,
`removed_website`, `changed_website`, `changed_description`, `new_job`, `closed_job`,
`new_activity`, `new_profile`, `removed_profile`, `new_careers_page`, and `new_<field>` /
`removed_<field>` / `changed_<field>` for the rest. Materiality: `high` for status, name, legal
form, filings and CEO/chair/owner roles; `medium` for address, employees, other roles,
workplaces, website, jobs, financial restatements; `low` otherwise.

Each change carries `type`, `kind`, `field`, `label`, `claim_key`, `claim_ids`, `materiality`,
`detected_at`, `previous {value, first_observed_at, last_observed_at}`, `current {value}` and
`evidence {previous: [full earlier evidence records], current: [{id, source_url}]}`.

Demonstration: `python -m signalpost replay --fixtures tests/fixtures/replay --output out.json`
(pass 1 first observation, pass 2 eight typed changes, pass 3 identical → zero changes).
