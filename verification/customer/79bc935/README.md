# Customer verification — commit 79bc935 (Stage 1, revision 3 FINAL)

Tested in an isolated worktree. Covers the two UI verification aids required by lead 00032/00028:
(a) visible "Not refreshed this run: <reason>" stale-tag on carried facts, reproduced with a real
two-run F1 repro; (b) per-section "Sources checked (N)" collapsible details, checked on smoke
companies 929941551 (2 name-guess website candidates) and 818037562 (registry-declared site,
egress-blocked). Verified: closed by default, "No sources recorded" for empty lists, rel=
"noopener noreferrer" links, safeUrl() blocks non-http(s) schemes, h()/textContent-only rendering
(no innerHTML anywhere in app.js) satisfies R-1.56. Tap-target + overflow sweep with every
<details> forced open: 0 elements under 40px, no horizontal scroll, on 8 pages. pytest 68 passed.
