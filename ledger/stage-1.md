# Stage 1 requirements ledger: Signalpost Registry-First Evidence Agent

Owner: @lead. Written 2026-09-29 before any product code. This ledger, not any shipped check, is the
definition of done. Sources of truth, in priority order:

1. The human's dispatch (TASK.md, "Signalpost specifics" section) — overrides the brief's guesses.
2. The official Builderr pages, saved verbatim in `docs/official/` on 2026-09-29:
   `signalpost.md` (participant brief), `signalpost-evaluation-harness.md` (evaluation contract),
   `signalpost-sources.md` (source policy), `signalpost-agent-playbook.md`, `signalpost-learning-harness.md`,
   `starter-kit-docs/OUTPUT_CONTRACT.md` (minimal output contract) and the starter kit tarball.
3. brief.json / PLAN.md (only where 1 and 2 are silent).

There are no earlier stages, so nothing is carried forward. The stage folder is the repository root
`.` (Builderr clones the repo root and runs one command there).

Verified live on 2026-09-29 from the sandbox (these are facts the builder can rely on):
- `GET https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}` → 200 JSON; unknown number → 404; deleted
  entities → 410 (documented by Brreg). Fields include `navn`, `organisasjonsform`, `forretningsadresse`,
  `postadresse`, `naeringskode1..3`, `antallAnsatte`, `harRegistrertAntallAnsatte`, `hjemmeside`,
  `epostadresse`, `stiftelsesdato`, `registreringsdatoEnhetsregisteret`, `registrertIMvaregisteret`,
  `konkurs`, `underAvvikling`, `underTvangsavviklingEllerTvangsopplosning`, `overordnetEnhet`, `erIKonsern`,
  `vedtektsfestetFormaal`, `aktivitet`, `historiskeNavn`, `institusjonellSektorkode`, `sisteInnsendteAarsregnskap`.
- `GET .../enhetsregisteret/api/enheter/{orgnr}/roller` → role groups with `sistEndret` dates.
- `GET .../enhetsregisteret/api/underenheter?overordnetEnhet={orgnr}` → registered workplaces (paged).
- `GET https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` → latest filed accounts (array; has
  `regnskapsperiode.fraDato/tilDato`, `valuta`, income statement and balance sheet).
- `GET https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{orgnr}/aar` → list of years with
  filed annual-account copies (e.g. `["2011",...,"2025"]`).
- Public universe `https://builderr.ai/signalpost-company-universe-2025.jsonl.gz` (sha256
  `1c89710e…0384`), rows like `{"organisation_number":"810034882","name":"SANDNES ELEKTRISKE AS",...,"website":""}`.
- The sandbox reaches only brreg.no, builderr.ai, GitHub and package registries. Company websites and news
  cannot be reached from here; that layer is built for open internet and tested with saved fixtures.

---

## A. Input, run command and batch contract

- **R-1.1** One single pasteable run command processes a whole batch: organisation numbers in, one result per
  company out. A list of steps or a notebook is not acceptable.
- **R-1.2** The input is a file Builderr supplies at run time. The agent never picks its own companies and
  never reads a built-in list when an input is given.
- **R-1.3** Input formats accepted: (a) JSONL where each line is an object with `organisation_number`
  (also accept `orgnr`, `organization_number`, `organisasjonsnummer`), exactly the shape of the public
  universe rows; (b) a JSON array of such objects or of strings; (c) plain text, one number per line.
  Blank lines and whitespace are ignored; numbers written with spaces (`923 609 016`) are normalised.
- **R-1.4** Exactly ONE terminal envelope per input company, for every company, including when nothing was
  found, the source refused, the number is invalid, or the agent crashed on that company. A missing row
  makes the batch unscorable.
- **R-1.5** Output is JSONL, one envelope object per line, in input order, written to the path given on the
  command line; the run also writes a machine-readable run report (JSON).
- **R-1.6** The run works for companies never seen before (any of the 411,160 universe numbers, and any valid
  Norwegian organisation number).
- **R-1.7** Batch size is not fixed at 100: 1,000 and 1,100-company batches must work with the same command.
- **R-1.8** An `--expected-count` style check (or equivalent in the report) states input count vs envelope
  count; the process exits non-zero only if the envelope count cannot be made to match (it must always
  try to emit a `failed` envelope rather than drop one).
- **R-1.9** Checkpoint/resume: a run interrupted part-way can be resumed without duplicating or losing
  envelopes.
- **R-1.10** A fixed time budget can be supplied (e.g. `--time-budget-seconds`). Before the budget runs out
  the agent stops deep research and still emits a terminal envelope for every remaining company (registry-only
  fast path, or `failed` with reason `time_budget_exhausted`). The run finishes inside the budget.
- **R-1.11** Bounded, configurable concurrency; a per-company wall-clock timeout; per-host polite rate limits.
- **R-1.12** Runtime and resource use are measured and reported: total runtime, p50 and p95 per-company
  runtime, request count (total and per source), bytes fetched, peak memory if obtainable, third-party cost in
  USD (0 when no paid API is used).

## B. Envelope and claim schema

- **R-1.13** Every envelope has: `organisation_number`; `status` (one of the six states, see R-1.15);
  `run` (`run_id`, `started_at`, `completed_at`, `terminal_status`); `legal_identity`; `sections`
  (the seven required sections, R-1.16); `claims`; `evidence`; `source_snapshots`; `changes`; `summary`;
  `errors`; `operations` (`requests`, `runtime_ms`, `third_party_cost_usd`). It is a superset of the
  starter kit's minimal output contract (`claims[].field/value/availability/confidence/evidence_ids`,
  `evidence[].id/source_url/source_class/retrieved_at/content_sha256/claim_span`).
- **R-1.14** Valid availability states are exactly `available`, `not_available`, `blocked`, `not_applicable`,
  `ambiguous`, `failed`, used with their official meanings: available = found; not_available = looked and
  nothing is there; blocked = the source refused the request (403/429/robots disallow/captcha); not_applicable
  = the question does not apply to this company; ambiguous = could not be sure it is the right company;
  failed = the run broke on this one.
- **R-1.15** Envelope-level `status`: `available` when the registry identity was retrieved; `not_available`
  when Brreg reports no such entity (404) or it is deleted (410, with deletion date as a claim when given);
  `blocked` when Brreg refused every attempt; `failed` for an invalid organisation number (wrong length or
  mod-11 check digit) or an unrecovered crash/timeout; `ambiguous` is never used at envelope level for a
  number that resolves in the registry (the org number is an exact key). `terminal_status` is always a
  terminal value.
- **R-1.16** Every envelope contains the seven required sections, each with its own availability state and the
  ids of the claims in it: (1) legal identity and public brand; (2) latest annual accounts and available
  history; (3) leadership and registered workplaces; (4) verified official website and company-owned
  profiles; (5) hiring and dated public activity from permitted sources; (6) claim-level evidence and
  availability state; (7) refresh metadata and material changes since the previous run.
- **R-1.17** Each claim has a stable `claim_key` (deterministic from organisation number + field + value
  identity, e.g. role type + person, subunit orgnr), `field`, `value`, `availability`, `confidence`,
  `evidence_ids`, and where relevant `effective_date` / `reporting_period` (`from`, `to`).
- **R-1.18** Every published claim with `availability: available` references at least one evidence record.
  Every evidence record has: `id`, `source_url` (the exact URL fetched — for Brreg the exact API URL),
  `human_url` (a clickable page for people where one exists, e.g.
  `https://virksomhet.brreg.no/nb/oppslag/enheter/{orgnr}`), `source_class` (`official_registry`,
  `official_accounts`, `company_owned`, `external`), `retrieved_at` (UTC ISO-8601), `record_date`
  (the source's own date for the fact where it provides one, e.g. role group `sistEndret`,
  `registreringsdatoEnhetsregisteret`, accounts period end), `content_sha256` of the raw snapshot,
  `extraction_method` (with extractor version), and a locator (`json_pointer`, CSS selector or `claim_span`
  text) pointing at the exact field or text.
- **R-1.19** Missing values are never converted to zero or empty-as-value. An absent number is omitted with an
  explicit `not_available` claim/section state. `antallAnsatte` is published only when
  `harRegistrertAntallAnsatte` is true.
- **R-1.20** Financial values are copied exactly as filed (no rounding, no scaling) with `valuta` (currency)
  and the reporting period. No financial value is ever fabricated, estimated or inferred.
- **R-1.21** Output is valid UTF-8 JSON; Norwegian characters (æøå) are preserved, not mangled.

## C. Official registry facts (Brønnøysundregistrene)

- **R-1.22** Legal identity claims from the entity endpoint: legal name, organisation form (code +
  description), registration date in Enhetsregisteret, founding date (`stiftelsesdato`) when present,
  business address, postal address, municipality, industry codes (NACE 1–3 with descriptions), sector code,
  registered employee count (per R-1.19), VAT registration, registered website (`hjemmeside`), registered
  e-mail domain (domain only; see R-1.34), stated purpose/activity text, historical names with dates, group
  membership (`erIKonsern`), parent unit (`overordnetEnhet`) labelled as parent, latest submitted annual
  accounts year.
- **R-1.23** Status flags as claims: bankrupt, under liquidation, under forced liquidation/dissolution,
  deleted (with date). When any is true the summary states it prominently.
- **R-1.24** Leadership from the roles endpoint: CEO (daglig leder), board chair, board members, deputy
  members, auditor, accountant, contact person, and other role types, each with role type code/description,
  person name or organisation (with its orgnr), resigned/deregistered flag, and the group's `sistEndret`
  as record date. Birth dates of people are NOT published (privacy; only name and role).
- **R-1.25** Registered workplaces from the subunits endpoint: each subunit's orgnr, name, address,
  municipality, industry, employee count (per R-1.19), start date; all pages are followed up to a documented
  cap, and the total count is reported even if the list is capped.
- **R-1.26** Latest annual accounts from the accounts register: reporting period (from/to), currency, account
  type, total operating revenue, operating result, profit before tax, net result for the year, total assets,
  total equity, total debt, and whether the accounts were audited — whichever are present in the filing.
- **R-1.27** Available history: the list of years with filed annual-account copies (`.../aarsregnskap/kopi/
  *Amended 2026-09-29 by @lead (verifier F2):* the filing-years endpoint is limited by Brreg to about 30 requests
  per minute, so in a large batch the list is fetched for as many companies as that limit allows within the run.
  Every company without it carries exactly one explicit `filing_years` claim with `availability: blocked` and a
  reason naming the source's rate limit (the source's own policy refuses more requests); if an earlier run in the
  same state dir obtained it, the single claim is the carried-forward value with the skip exposed on it (R-1.46).
  Never both. The latest filed accounts (R-1.26) are not affected and must be present for every filer.
  {orgnr}/aar`) is published as a claim; values for earlier years are published only if obtained from an
  official source for that year, never extrapolated.
- **R-1.28** The agent is robust to Brreg behaviour: retries with backoff on 429/5xx/timeouts, honours
  `Retry-After`, sets a descriptive User-Agent, and turns persistent refusal into `blocked` and persistent
  errors into `failed` at the section level without losing the rest of the envelope.
- **R-1.29** An optional frozen registry snapshot may be supplied (Brreg bulk CSV/JSON download, the file
  Builderr says it provides for identity anchoring). When given, identity anchoring can use it and the
  evidence cites the snapshot file identity plus the corresponding API URL; when absent the live API is used.

## D. Company website and company-owned sources

- **R-1.30** Website candidates come from: registry `hjemmeside`; the registered e-mail domain when it is not
  a generic mail provider (gmail, hotmail, outlook, online.no, etc.); the input row's `website` field when
  present; and optionally a search API when its key is set (R-1.47). Candidates are candidates, not facts.
- **R-1.31** A website is published as the verified official website only with exact-entity proof: the
  9-digit organisation number (any common formatting, e.g. `923 609 016`, `NO 923609016 MVA`) appears on the
  site, OR a documented strong combination (legal name + registered street address or postcode, or legal
  name + registered phone/e-mail) — the proof itself is stored as evidence. The registry-listed `hjemmeside`
  itself counts as official-registry evidence that the company declares the site, but facts extracted from
  the site are published only if the site resolves (fetch succeeds) and does not contradict identity.
- **R-1.32** Parent, group, brand, franchise or similarly named companies are never collapsed into the entity:
  if proof points to a different orgnr, the website section is `ambiguous` (or the relationship is labelled),
  and no site facts are published under this company.
- **R-1.33** Site crawl is deterministic and bounded: robots.txt is fetched and obeyed; per-domain max pages
  (documented, ~10) and max bytes; static HTML first; priority paths `/`, `/om-oss`, `/about`, `/kontakt`,
  `/contact`, `/ledelse`, `/leadership`, `/karriere`, `/jobb`, `/careers`, `/jobs`, `/nyheter`, `/news`,
  `/investor`, sitemap.xml; polite per-host delay.
- **R-1.34** Safe URL handling: only http/https; no credentials in URLs; DNS results resolving to private,
  loopback, link-local or metadata addresses are refused; redirects are re-checked; response size and time
  are capped; no JavaScript is executed. The policy is documented.
- **R-1.35** Company-owned facts extracted when present: site description (meta/OpenGraph/JSON-LD
  `Organization`), public brand name, contact phone/e-mail/address on site, company-owned social/video
  profile links found on the verified site (LinkedIn, Facebook, Instagram, YouTube, X, etc. — the link only;
  those platforms are never crawled), careers page URL, job postings (JSON-LD `JobPosting` or careers-page
  listings with title and date where given), dated news/press items (title, date, URL) from the site's news
  pages, RSS/Atom feeds or sitemap `lastmod`.
- **R-1.36** Each company-owned fact carries the exact page URL, retrieval time, the page's date when known,
  content hash and a CSS selector/text span.
- **R-1.37** Blocked (403/429/robots disallow), timed-out, and not-reachable sites give `blocked` / `failed`
  / `not_available` states on the website section — never silent absence.
- **R-1.38** Hiring section: `available` with postings when found; `not_available` when a careers/jobs page
  was checked and has none or no careers page exists on a verified site; `not_available` (reason: no verified
  website) when no site was verified. A checked source with zero jobs is distinguishable from an unchecked one.
- **R-1.39** Only permitted sources: official registers, verified company-owned sites/feeds, and optional
  official/licensed APIs. LinkedIn, Meta, Glassdoor, Indeed and Google result pages are never scraped. Search
  results are only candidates, never evidence.
- **R-1.40** The website/news layer is tested with saved fixtures (HTML files) that cover: org number on the
  page (verified), no proof (not published), wrong-company proof (ambiguous), robots disallow (blocked),
  JobPosting JSON-LD, news items with dates, social links.

## E. Synthesis

- **R-1.41** Every available envelope has a `summary` that explains, in plain language: what the company does
  (from industry code, purpose/activity text and verified site description), its size and latest filed
  numbers, who leads it, where it operates, what changed since the previous run (or "first observation"),
  and what remains unknown (every section that is not_available/blocked/ambiguous/failed, named).
- **R-1.42** Every sentence of the summary cites the claim ids/evidence ids it rests on; the summary makes no
  claim that is not backed by a published claim. Company-owned promotional copy is labelled as the company's
  own description, not as independent assessment.
- **R-1.43** The deterministic (no-LLM) summary is always produced. An optional LLM step (R-1.47) may rewrite
  it only from the published claims and must keep the citations; if its output cites nothing or fails
  validation, the deterministic summary is kept.

## F. Refresh, idempotency and change detection

- **R-1.44** A persistent state directory (configurable; default inside the output folder) stores immutable
  source snapshots (keyed by content hash) and the claim store keyed by stable `claim_key`, with
  `first_observed_at` and `last_observed_at`.
- **R-1.45** Re-running on the same source snapshot is idempotent: no duplicate snapshots, no duplicate claims,
  zero changes reported, identical claim sets (only `last_observed_at`/run timestamps may move).
- **R-1.46** When a value changes, the envelope's `changes` lists typed changes (e.g. `new_role`,
  `removed_role`, `changed_address`, `new_filing`, `changed_name`, `new_location`, `closed_location`,
  `changed_employees`, `status_change`, `new_job`, `closed_job`, `changed_description`, `new_website`) with
  previous value, current value, both evidence references, and materiality. Prior evidence is preserved, not
  overwritten. A failed refresh keeps the last supported value and exposes the failure; it never reports a
  removal because a fetch failed.
- **R-1.46a** A deterministic replay mode (or test) feeds two saved snapshots of the same company and shows the
  expected changes, no false changes, and zero changes on a third identical replay.

## G. Optional LLM and external APIs

- **R-1.47** The core works with no LLM and no API key at all. Any LLM or search API is optional, reads only a
  standard environment variable (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `BRAVE_API_KEY`), is off when the
  variable is absent, degrades cleanly on errors, and is capped by a per-run budget. No credential tied to the
  human's account is required or committed. Secrets never appear in outputs or logs.
- **R-1.48** An LLM never decides identity, never invents a missing field, and never overrides deterministic
  evidence.

## H. Web UI (a person uses it)

- **R-1.49** A small web UI started by one documented command (bind `0.0.0.0`, configurable port) where a person
  types an organisation number and gets the profile rendered within seconds.
- **R-1.50** Every fact on screen shows its value, date(s) and a clickable source link that opens the exact
  registry API record or web page; hovering/focusing a fact highlights its source (the "wow" moment:
  each line links straight to the field it came from, with the JSON pointer/selector shown).
- **R-1.51** The UI shows all seven sections with a visible availability state badge each, the summary with
  its citations, the "what changed" list and the "what is unknown" list.
- **R-1.52** Interface states that must be reachable and clearly shown: empty start state; input validation
  error (non-digits, wrong length, bad check digit) with a human message; loading state; available profile;
  not_available (no such company / deleted); blocked (source refused); failed (with what happened); ambiguous
  website section; partial profile (some sections missing).
- **R-1.53** A compare view: two (or more) organisation numbers side by side with the same fields aligned.
- **R-1.54** A batch browser: open an envelopes JSONL (e.g. the smoke-test output) and find companies by
  name/orgnr, filter by state, and open any profile.
- **R-1.55** Usable on mobile (375 px wide, no horizontal scroll, tap targets ≥ 40 px) and desktop (1280 px);
  keyboard accessible; readable contrast.
- **R-1.56** The UI renders only escaped text from sources (no HTML injection from registry or site content);
  outbound links use `rel="noopener noreferrer"`.

## I. Reproducibility, packaging and docs

- **R-1.57** Pinned dependencies (exact versions) and one declared install step, e.g.
  `python -m venv .venv && .venv/bin/pip install -r requirements.txt` (or `pip install .`). Python version
  requirement declared (≥3.11).
- **R-1.58** Acceptance test (the official procedure): clone the repo at the pinned commit into a NEW folder,
  create an EMPTY virtualenv, run only the declared install step, then the single run command on a 100-company
  input → exit 0, exactly 100 envelopes, one per input org number, all with valid states.
- **R-1.59** A `Dockerfile` builds the product with every dependency baked in and runs the same command; a
  `RUN.md` a stranger can follow (install, run batch, run UI, run tests, resume, refresh).
- **R-1.60** Test suite (pytest) runs offline from fixtures and passes.
- **R-1.61** A self-score script samples random org numbers from the public universe (documented seed),
  runs the agent, and reports: envelope count vs input, state distribution, per-field and per-section coverage,
  evidence completeness (share of available claims with source_url + retrieved_at + record/reporting date),
  idempotency check (second run → zero changes), runtime p50/p95, requests, and a rubric estimate.
- **R-1.62** A committed 100-company smoke-test result (envelopes JSONL + run report) from a random 100 drawn
  from the public universe with the seed recorded.
- **R-1.63** Docs: `README.md` (what it is, setup, run command, UI, screenshot, live-link status, limitations),
  `LICENSE` (MIT), and documentation of the data schema, source rights/policy (robots, rate limits, URL safety,
  secrets via env vars only), identity/abstention policy, refresh model and known limitations.
- **R-1.64** Declaration of models, APIs, licences and expected cost per official run (expected $0 with no LLM).

## J. Submission kit (presenter)

- **R-1.65** `SUBMIT/email.md` drafted for `submit@builderr.ai`, subject "Signalpost Round 1 submission",
  with every field of the official mailto template: agent name, repository URL, exact commit hash,
  100-company smoke-test result or report link, one-command run instruction, models/APIs/licences,
  expected cost per official run, contact for results (placeholder for the human).
- **R-1.66** README screenshot of the UI and an honest self-score against the rubric.

## Checklist mapping (task checklist.json)

D1 → R-1.1–R-1.6; D2 → R-1.13–R-1.27, R-1.35–R-1.36, R-1.41; D3 → R-1.4, R-1.7–R-1.12, R-1.58, R-1.62;
R1 → R-1.39 + docs/official/signalpost-sources.md; R2 → Ambiguity 8; R3 → R-1.61 self-score; R4 → Ambiguity 9;
R5 → R-1.9–R-1.11, R-1.28, R-1.45, R-1.58; X1 → R-1.63, R-1.66 (publishing = human blocker);
X2, X3 → not required (human: no video/slides for this event); X4 → R-1.65.

## Ambiguities (reading chosen, and why)

1. **Official output format.** The page says Builderr "supplies the company batch and output format for the
   run" but publishes only the starter kit's minimal contract. Reading: emit a strict superset of
   `OUTPUT_CONTRACT.md` (same field names) plus the seven sections; accept an `--output` path. Keeps every
   documented field valid whatever extra the harness reads.
2. **Envelope state vs claim state.** Both exist: one envelope-level `status` and per-section/per-claim
   availability. The registry identity drives envelope status (R-1.15).
3. **Duplicate org numbers in the input.** Reading: one envelope per input line, in order; duplicates reuse the
   same research result (same claim keys, no duplicate records in the store) and the report counts them.
   Why: "one result per input" and "no duplicate records" both stay true.
4. **Invalid org number.** Reading: `failed` with error `invalid_organisation_number` (the run could not
   research it); not `not_available` (we did not look).
5. **"Date" for each fact.** Reading: every evidence has `retrieved_at`; plus the source's own date where it
   has one (`record_date`) and the reporting period for accounts. Where the source has no own date,
   `record_date` is null and that is stated, never invented.
6. **Stage folder.** Single stage; the folder is the repository root, because Builderr clones and runs the
   root.
7. **Starter kit code.** The starter kit tarball has no licence file. Reading: use it as documentation of
   the contract only; do not copy its code into our MIT repo. Its tests are not our checks.
8. **Deadline (R2).** Page: "Closes Oct 21"; revisions "before Oct 18" / "by 18 October 2026"; round runs
   23 Aug–21 Oct 2026. No time of day or timezone is given. Reading: treat 17 Oct 2026 23:59 UTC as the
   safe last-revision time and 20 Oct 2026 as the safe final-submission day.
9. **Prize split (R4).** Resolved by the page: main pool $1,200 / $500 / $300 for 1st/2nd/3rd, separate JBOX
   bonus $250/$150/$100 for qualifying agents built with JBOX (we do not use JBOX), $100 × 4 community awards.
10. **Time/resource budget.** Not published. Reading: design for 1,000–1,100 companies with bounded concurrency
    and an explicit `--time-budget-seconds`; measure and report our real throughput so the human can declare it.
11. **Website "verification" when the registry lists the site but it carries no org number.** Reading:
    the registry `hjemmeside` is official evidence that the company declares that URL, so the URL is
    published as `official_website` with registry evidence; site-extracted facts additionally require the
    site to load and not contradict identity (no other orgnr presented as the owner). E-mail-domain and
    guessed candidates require the stronger proof in R-1.31.
12. **External news.** No permitted news source is named and news sites' terms vary. Reading: dated
    activity comes from the verified company's own news pages/feeds/sitemaps; an external news connector is
    only added behind an optional API key for an official/licensed API. This favours precision (the scoring
    says it is better to miss than to publish the wrong company).
13. **Live link (X1).** A public live UI needs a hosting account → human blocker. The UI runs locally
    via one command and in Docker; README states this.
14. **Builder mandate says "no outbound network".** This product's purpose is to call public registries;
    the official run has network. Reading: the product must *build and install* offline-capable in Docker
    (dependencies baked in) and its tests run offline from fixtures; the batch run itself uses the network.
