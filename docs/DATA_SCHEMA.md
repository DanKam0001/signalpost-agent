# Data schema

One envelope (JSON object) per input line. It is a strict superset of the starter kit's minimal
output contract (`docs/official/starter-kit-docs/OUTPUT_CONTRACT.md`).

## Envelope

| Key | Content |
|---|---|
| `organisation_number` | normalised 9-digit number (the raw input for unparseable numbers) |
| `input` | `{index, raw}` and `duplicate_of_index` when the number repeats in the batch |
| `status` | `available` (registry identity retrieved) · `not_available` (Brreg 404, or deleted 410) · `blocked` (Brreg refused every attempt) · `failed` (invalid number, crash, timeout, time budget). `ambiguous` is never used at envelope level: the org number is an exact key |
| `status_reason` | plain-language reason |
| `run` | `{run_id, started_at, completed_at, terminal_status, fast_path}`; `terminal_status` ∈ `completed`, `failed`, `timed_out` |
| `legal_identity` | name, form, address, municipality, industry, status flags, parent unit, source and human URLs |
| `sections` | the seven required sections (below), each `{availability, reason, claim_ids, sources}` |
| `claims` | every fact, including explicit `not_available`/`blocked`/`ambiguous` claims |
| `evidence` | evidence records referenced by claims |
| `source_snapshots` | every stored raw response: `{id, source, source_class, url, final_url, redirects, http_status, retrieved_at, content_sha256, content_type, bytes, truncated}` |
| `changes` | typed changes since the previous observation (see `REFRESH.md`) |
| `refresh` | `{first_observed_at, previous_observed_at, previous_run_id, observation_number, change_count}` |
| `summary` | `{text, sentences:[{text, claim_ids, evidence_ids}], unknowns:[{section, availability, text}], changes_text, generated_by}` |
| `errors` | `[{section, code, detail, url}]` |
| `operations` | `{requests, runtime_ms, third_party_cost_usd, bytes_fetched, requests_by_source, requests_by_host}` |
| `agent` | `{name, version}` |

## Sections

`legal_identity_and_brand`, `annual_accounts`, `leadership_and_workplaces`,
`website_and_profiles`, `hiring_and_activity`, `evidence_and_availability`,
`refresh_and_changes`. Availability values are exactly `available`, `not_available`, `blocked`,
`not_applicable`, `ambiguous`, `failed`. A checked source with zero items (e.g. a careers page
with no postings, zero workplaces) is `not_available` with a reason saying it was checked; an
unchecked source says "not checked".

## Claim

| Key | Content |
|---|---|
| `id` | `c-` + hash of `claim_key` (stable across runs) |
| `claim_key` | `orgnr:field[:identity]`, e.g. `923609016:role:DAGL:p:anders opedal`, `923609016:workplace:973861883`, `923609016:total_assets:selskap` |
| `field`, `label`, `section`, `scope` | what the fact is; `scope` is the source it came from (entity, roles, subunits, accounts, filing_years, website) |
| `value` | the value. Financial values are copied exactly as filed (integers when integral; a decimal string only if a float could not represent it exactly) with `currency` and `as_filed` alongside |
| `availability`, `confidence`, `reason` | state; confidence 1.0 for registry facts, 0.7–0.99 for website facts by proof strength |
| `evidence_ids` | at least one for every `available` claim |
| `effective_date`, `reporting_period` | where the source gives them (`{from, to}` for accounts) |
| `first_observed_at`, `last_observed_at` | from the claim store |
| `carried_forward` | true when the source failed this run and the last supported value is shown |
| `refresh_status` | on a carried-forward claim: `{availability, reason}` of this run's failed attempt (each `claim_key` appears once per envelope) |

Fields published: legal_name, organisation_form, registration_date, business_register_date,
founding_date, business_address, municipality, postal_address, industry_code (1–3),
sector_code, registered_employees (only when `harRegistrertAntallAnsatte`), vat_registered,
share_capital, stated_purpose, registered_activity, historical_name, in_group, parent_unit,
bankrupt, under_liquidation, under_forced_liquidation, deleted, closed, registered_phone (not for
sole proprietorships), registered_website, registered_email_domain (domain only),
latest_submitted_accounts_year, accounts_period, operating_revenue, operating_expenses,
operating_result, net_financial_items, profit_before_tax, net_result, total_assets, fixed_assets,
current_assets, total_equity, total_debt, total_equity_and_debt, audited, filing_years, role,
workplace_count, workplace, official_website, site_description, brand_name, site_phone,
site_email (generic mailboxes only), social_profile, careers_page, job_posting, news_item,
website_candidate_relationship (ambiguous only).

## Evidence

| Key | Content |
|---|---|
| `id` | `ev-` + hash of URL, content hash and locator |
| `source_url` | the exact URL fetched (for Brreg, the exact API URL) |
| `human_url` | clickable page for people (virksomhet.brreg.no) where one exists |
| `source_class` | `official_registry`, `official_accounts`, `company_owned` |
| `retrieved_at` | UTC ISO-8601 |
| `record_date`, `record_date_field` | the source's own date for the fact (e.g. role group `sistEndret`, accounts period end, `registreringsdatoAntallAnsatteEnhetsregisteret`, page date); `null` when the source gives none — never invented |
| `content_sha256`, `snapshot_id` | hash of the raw stored response and the matching `source_snapshots` entry |
| `extraction_method` | extractor and version, e.g. `brreg-json-v1`, `site-jsonld-v1` |
| `json_pointer` | RFC 6901 pointer into the body served at `source_url` (array responses start with the index, e.g. `/0/eiendeler/sumEiendeler`); scalar claims resolve to exactly the claimed value |
| `css_selector`, `claim_span` | for web pages: the element and the exact text |
