# Self-score (seed 20260929)

- Envelopes: 100 for 100 inputs (match: True)
- States: {'available': 100, 'not_available': 0, 'blocked': 0, 'not_applicable': 0, 'ambiguous': 0, 'failed': 0}
- Runtime: total 46.9 s, p50 2581 ms, p95 6317 ms; requests 514; third-party cost $0
- Evidence: {'available_claims': 3814, 'share_with_source_url_and_retrieved_at': 1.0, 'share_also_with_record_or_reporting_date': 0.6474}
- Idempotency (second run on the same state): {'second_run_changes_total': 0, 'second_run_companies_with_changes': 0}

| Field family | Companies | Share | Facts |
|---|---:|---:|---:|
| identity (registry) | 100 | 100% | 401 |
| employees (registry) | 15 | 15% | 15 |
| latest accounts | 100 | 100% | 277 |
| filing history | 22 | 22% | 22 |
| leadership (roles) | 100 | 100% | 358 |
| workplaces | 100 | 100% | 100 |
| official website | 10 | 10% | 10 |
| company description | 0 | 0% | 0 |
| social profiles | 0 | 0% | 0 |
| job postings | 0 | 0% | 0 |
| dated activity | 0 | 0% | 0 |

| Section | States |
|---|---|
| legal_identity_and_brand | {'available': 100} |
| annual_accounts | {'available': 100} |
| leadership_and_workplaces | {'available': 100} |
| website_and_profiles | {'not_available': 81, 'failed': 19} |
| hiring_and_activity | {'not_available': 81, 'failed': 19} |
| evidence_and_availability | {'available': 100} |
| refresh_and_changes | {'available': 100} |

## Rubric estimate (ours, not Builderr's)

- recall_and_coverage_50: 19.2
- precision_and_evidence_30: 30.0
- synthesis_12: 10.0
- ux_8: 6.5
- total_100: 65.7

- External recall compared with an assumed pool covering ~50% of companies.
- Precision assumes no wrong-company publication (org number is the key; websites need exact-entity proof).
- UX is our own judgement from the 1280 px and 375 px screenshots.
- In this sandbox company websites are unreachable, so external families score low here; on the open internet they will be higher.
