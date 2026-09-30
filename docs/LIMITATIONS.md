# Known limitations

- **Website discovery without search.** Candidates are the registry website, the registered
  e-mail domain, the input row and two name guesses. Companies with none of these (about 70–80 %
  of a random universe sample have no registered website) usually end `not_available` for the
  website, hiring and activity sections. A licensed search API would raise recall but needs a key;
  none is used or required.
- **Static HTML only.** JavaScript is never executed, so sites that render everything client-side
  (JavaScript shells) yield little beyond the homepage metadata.
- **Filing history rate limit.** Brreg's annual-account copy index allows ~30 requests/minute
  (ledger R-1.27 as amended). The lane uses every slot during the run; a company waits at most 5 s
  for a slot, so in large batches many companies get one explicit `blocked` filing-years claim
  ("Brønnøysund limits this endpoint to about 30 requests per minute; not fetched for this company
  in this run") while their latest accounts are still published. The run report counts
  `filing_years_fetched` / `filing_years_skipped`. `--history-wait 60` gives full history on small
  batches.
- **Only the latest accounts' values.** Regnskapsregisteret's open API returns the latest filing;
  earlier years are listed (years with filed copies) but their values are not published, because
  they are not available from an official machine-readable source here. Nothing is extrapolated.
- **Record dates.** Brreg does not date every entity field. Where the source has no own date,
  `record_date` is `null` (the retrieval time is always present); it is never invented.
- **Job and news extraction** covers JSON-LD `JobPosting`, careers-page links to job pages or
  common Norwegian ATS domains, `<article>`/`<time>` news listings, RSS/Atom feeds and dated
  sitemap URLs under news paths. Titles from sitemap entries are derived from the URL and labelled
  as such.
- **Sandbox testing.** The development sandbox can reach only data.brreg.no, builderr.ai and
  package registries, so the website layer was tested with saved fixture sites and one real
  reachable site (www.brreg.no for 974760673). In the committed smoke run most company sites show
  "this run's own network policy blocked outbound access" (`failed`) or `not_available`; on the
  open internet those sites are crawled.
- **Sub-units as input.** A sub-unit number is resolved via the sub-unit endpoint; roles come from
  the roles endpoint if any, workplaces and accounts are `not_applicable`.
- **No LLM.** Summaries are deterministic templates over published claims.
- **Public live UI.** Hosting a public instance needs a hosting account (human blocker); the UI
  runs locally or in Docker with one command.
