# Sources, rights and outbound policy

## Sources used

| Source | Class | Access | Rights |
|---|---|---|---|
| Enhetsregisteret API `data.brreg.no/enhetsregisteret/api/enheter/{orgnr}`, `/roller`, `underenheter?overordnetEnhet=` | official_registry | open, no key | NLOD 2.0 |
| Regnskapsregisteret `data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` and `/aarsregnskap/kopi/{orgnr}/aar` | official_accounts | open, no key | NLOD 2.0 |
| Optional Brreg bulk snapshot supplied by the evaluator (`--registry-snapshot`) | official_registry | local file | NLOD 2.0 |
| The company's own website: homepage, contact/about, careers, news, leadership, investor pages, robots.txt, sitemap, RSS/Atom feeds | company_owned | public HTTP(S), robots.txt obeyed | the company's own publication; we store snapshots as evidence and quote short spans |

Not used: search engines or search result pages, LinkedIn, Meta (Facebook/Instagram), Glassdoor,
Indeed, X or any other platform. Social/video profile *links* found on a verified company site are
recorded as links; those platforms are never requested. No paid API, no LLM.

## Politeness and budgets

- User-Agent `SignalpostEvidenceAgent/<version> (registry-first company research; obeys robots.txt)`.
- Brreg: ≤ 25 requests/s overall; the annual-account copy index is limited to one request per 2.1 s
  (Brreg allows ~30/min); `Retry-After` and `x-rate-limit-remaining: 0` push requests back;
  429/5xx/timeouts retried with exponential backoff (max 3 retries), never past the deadline.
- Websites: robots.txt fetched first and obeyed (RFC 9309: 4xx robots → allowed; 5xx/unreachable →
  treated as full disallow; `Crawl-delay` honoured up to 5 s); ≥ 0.5 s between requests to one
  host; at most 10 HTML pages + 4 auxiliary files (robots, sitemap, feed) per site; 1.5 MB per
  response; 10 s per request; no retries; static HTML only — JavaScript is never executed.

## Safe URL handling

Implemented in `signalpost/urlsafety.py` and applied to every request and every redirect hop:

- only `http`/`https`; no credentials in URLs; only default ports (80/443);
- `localhost`, `.local`, `.internal`, `.lan`, `.home.arpa` refused;
- the host must resolve only to public addresses: private (RFC 1918, ULA), loopback, link-local
  (incl. the 169.254.169.254 metadata address), carrier-grade NAT, multicast, reserved and
  unspecified addresses are refused before any request is made;
- at most 5 redirects, each re-checked (and robots-checked);
- response size and time are capped; stored pages are served back by the UI only as `text/plain`.

`SIGNALPOST_ALLOW_PRIVATE_HOSTS` exempts listed hosts for tests only (see RUN.md).

## Secrets

The agent needs no secrets. It reads no API key. If a future optional connector is added it must
read a standard environment variable, be off when the variable is absent, and never write the value
to outputs or logs.

## Privacy

Role holders are published by name and role only (company context). Birth dates from the roles
endpoint are never published or stored in claims. Registered e-mail addresses are reduced to their
domain; on websites only generic company mailboxes (post@, info@, …) are published; phone numbers
of sole proprietorships are not published.
