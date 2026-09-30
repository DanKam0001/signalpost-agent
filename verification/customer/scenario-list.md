# Customer verification scenario list (prepared ahead of builder handoff)

Prepared 2026-09-29 by @customer. Tooling ready: Playwright (Node, $HOME/hq/customer-tools,
chromium installed via `npx playwright install --with-deps chromium`). Widths: 375x812 (phone), 1280x800 (desktop).

## Test orgnrs
- 923609016 — Equinor ASA (large, many roles/subunits, USD accounts) -> available, likely partial (website blocked)
- 810034882 — SANDNES ELEKTRISKE AS (small, historical name, email domain, no website) -> available
- 999999999 — valid format, no such company -> not_available (404)
- 123456789 — bad check digit -> validation error
- 12345678 — 8 digits -> validation error
- abc — non-digits -> validation error
- 935567645 — 1SB JERNBANEKAFEEN AS, konkurs=true (bankrupt) -> available but should surface bankruptcy status/change
- (deleted/slettet entity — retry data.brreg.no/enhetsregisteret/api/enheter/slettede with correct query params when needed)

## States to reach (R-1.52) x2 widths each
1. Empty start state
2. Input validation error - non-digits (abc)
3. Input validation error - wrong length (12345678)
4. Input validation error - bad check digit (123456789)
5. Loading state
6. Available profile (923609016 and 810034882)
7. not_available - no such company (999999999)
8. not_available - deleted/bankrupt (935567645 or found deleted entity)
9. blocked (source refused - expect website sections on live companies)
10. failed (with what happened)
11. ambiguous website section
12. partial profile (some sections missing) - likely Equinor website blocked

## Other required checks
- R-1.49: single documented start command, binds 0.0.0.0, configurable port, profile renders within seconds
- R-1.50: every fact shows value+date+clickable source link to exact registry record; hover/focus highlights source; JSON pointer/selector shown
- R-1.51: all 7 sections visible with availability badges; summary+citations; what-changed list; what-is-unknown list
- R-1.53: compare view, 2+ orgnrs side by side, fields aligned
- R-1.54: batch browser - open envelopes JSONL, find by name/orgnr, filter by state, open profile
- R-1.55: mobile 375px no horizontal scroll, tap targets >=40px; desktop 1280px; keyboard nav; contrast
- R-1.56: no HTML injection from source content (escaped text only); outbound links rel="noopener noreferrer"

## Status
Waiting on @builder handoff (commit hash + start instructions) before driving the UI.
Repo currently has no signalpost module / requirements.txt yet (builder still building).
