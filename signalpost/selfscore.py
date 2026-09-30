"""Self-score: sample the public universe with a recorded seed, run the batch twice on the same
state (the second run checks idempotency), and report coverage, evidence completeness, states,
runtime and a rubric estimate. The estimate is ours, not Builderr's hidden scoring."""

from __future__ import annotations

import gzip
import hashlib
import json
import random
import urllib.request
from collections import Counter
from pathlib import Path

from .model import SECTIONS
from .runner import RunConfig, run_batch

UNIVERSE_SHA256 = "1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384"
FIELD_FAMILIES = {
    "identity (registry)": ["legal_name", "organisation_form", "business_address",
                            "industry_code"],
    "employees (registry)": ["registered_employees"],
    "latest accounts": ["operating_revenue", "net_result", "total_assets"],
    "filing history": ["filing_years"],
    "leadership (roles)": ["role"],
    "workplaces": ["workplace_count"],
    "official website": ["official_website"],
    "company description": ["site_description"],
    "social profiles": ["social_profile"],
    "job postings": ["job_posting"],
    "dated activity": ["news_item"],
}
EXTERNAL = {"official website", "company description", "social profiles", "job postings",
            "dated activity"}


def _universe(source: str, cache_dir: Path) -> Path:
    if not source.startswith(("http://", "https://")):
        return Path(source)
    target = cache_dir / "universe.jsonl.gz"
    if not target.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(source, target)  # noqa: S310 (fixed https URL from the user)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != UNIVERSE_SHA256:
        raise SystemExit(f"universe checksum mismatch: {digest}")
    return target


def sample(universe: Path, count: int, seed: int) -> list[dict]:
    with gzip.open(universe, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    rows.sort(key=lambda r: r["organisation_number"])
    return random.Random(seed).sample(rows, count)


def score(envelopes: list[dict], report: dict, second: dict | None) -> dict:
    n = len(envelopes)
    available = [e for e in envelopes if e["status"] == "available"]
    fields = {}
    for family, names in FIELD_FAMILIES.items():
        covered = [e for e in available if any(
            c["field"] in names and c["availability"] == "available" for c in e["claims"])]
        facts = sum(1 for e in available for c in e["claims"]
                    if c["field"] in names and c["availability"] == "available")
        fields[family] = {"companies": len(covered),
                          "company_share": round(len(covered) / n, 3) if n else 0,
                          "facts": facts}
    sections = {name: dict(Counter(e["sections"][name]["availability"] for e in envelopes))
                for name in SECTIONS}
    claims = [c for e in envelopes for c in e["claims"] if c["availability"] == "available"]
    ev_by_id = {ev["id"]: ev for e in envelopes for ev in e["evidence"]}
    with_source = with_date = 0
    for c in claims:
        evs = [ev_by_id[i] for i in c["evidence_ids"] if i in ev_by_id]
        if evs and all(ev.get("source_url") and ev.get("retrieved_at") for ev in evs):
            with_source += 1
            if c.get("reporting_period") or any(ev.get("record_date") for ev in evs):
                with_date += 1
    sentences = [s for e in available for s in e["summary"]["sentences"]]
    return {
        "input_count": report["input_count"],
        "envelope_count": report["envelope_count"],
        "count_matches_input": report["count_matches_input"],
        "state_counts": report["state_counts"],
        "section_state_counts": sections,
        "field_coverage": fields,
        "evidence": {
            "available_claims": len(claims),
            "share_with_source_url_and_retrieved_at": round(with_source / len(claims), 4)
            if claims else None,
            "share_also_with_record_or_reporting_date": round(with_date / len(claims), 4)
            if claims else None,
        },
        "summary": {"sentences": len(sentences),
                    "sentences_with_citations": sum(1 for s in sentences if s["claim_ids"])},
        "idempotency": None if second is None else {
            "second_run_changes_total": second["changes_total"],
            "second_run_companies_with_changes": second["companies_with_changes"],
        },
        "runtime_ms_total": report["runtime_ms_total"],
        "runtime_ms_p50": report["runtime_ms_p50"],
        "runtime_ms_p95": report["runtime_ms_p95"],
        "requests_total": report["requests_total"],
        "requests_by_host": report["requests_by_host"],
        "third_party_cost_usd": report["third_party_cost_usd"],
    }


def rubric_estimate(s: dict) -> dict:
    """Transparent heuristic; Builderr's pooled reference set is hidden."""
    fc = s["field_coverage"]
    registry = [v["company_share"] for k, v in fc.items() if k not in EXTERNAL]
    external = [v["company_share"] for k, v in fc.items() if k in EXTERNAL]
    # Recall is measured on external field families against a pooled union; we assume the pool
    # finds such facts for roughly half the companies, so our share is compared with 0.5.
    ext_recall = min(1.0, (sum(external) / len(external)) / 0.5) if external else 0.0
    recall = round(50 * (0.5 * ext_recall + 0.5 * (sum(registry) / len(registry))), 1)
    ev = s["evidence"]["share_with_source_url_and_retrieved_at"] or 0
    precision = round(30 * ev, 1)          # registry-anchored, abstains when unsure
    synthesis = 10.0 if s["summary"]["sentences"] and \
        s["summary"]["sentences"] == s["summary"]["sentences_with_citations"] else 5.0
    ux = 6.5
    return {"recall_and_coverage_50": recall, "precision_and_evidence_30": precision,
            "synthesis_12": synthesis, "ux_8": ux,
            "total_100": round(recall + precision + synthesis + ux, 1),
            "assumptions": [
                "External recall compared with an assumed pool covering ~50% of companies.",
                "Precision assumes no wrong-company publication (org number is the key; websites "
                "need exact-entity proof).",
                "UX is our own judgement from the 1280 px and 375 px screenshots.",
                "In this sandbox company websites are unreachable, so external families score "
                "low here; on the open internet they will be higher."]}


def _markdown(s: dict, est: dict, seed: int) -> str:
    lines = [f"# Self-score (seed {seed})", "",
             f"- Envelopes: {s['envelope_count']} for {s['input_count']} inputs "
             f"(match: {s['count_matches_input']})",
             f"- States: {s['state_counts']}",
             f"- Runtime: total {s['runtime_ms_total'] / 1000:.1f} s, p50 "
             f"{s['runtime_ms_p50']} ms, p95 {s['runtime_ms_p95']} ms; requests "
             f"{s['requests_total']}; third-party cost ${s['third_party_cost_usd']}",
             f"- Evidence: {s['evidence']}",
             f"- Idempotency (second run on the same state): {s['idempotency']}", "",
             "| Field family | Companies | Share | Facts |", "|---|---:|---:|---:|"]
    for family, v in s["field_coverage"].items():
        lines.append(f"| {family} | {v['companies']} | {v['company_share']:.0%} | {v['facts']} |")
    lines += ["", "| Section | States |", "|---|---|"]
    for name, counts in s["section_state_counts"].items():
        lines.append(f"| {name} | {counts} |")
    lines += ["", "## Rubric estimate (ours, not Builderr's)", ""]
    for key in ("recall_and_coverage_50", "precision_and_evidence_30", "synthesis_12", "ux_8",
                "total_100"):
        lines.append(f"- {key}: {est[key]}")
    lines += [""] + [f"- {a}" for a in est["assumptions"]]
    return "\n".join(lines) + "\n"


def run_selfscore(universe: str, count: int, seed: int, out: str, workers: int = 8,
                  web: bool = True, input_file: str | None = None) -> int:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if input_file:
        input_path = Path(input_file)
    else:
        rows = sample(_universe(universe, out_dir / "cache"), count, seed)
        input_path = out_dir / "input.jsonl"
        input_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                              encoding="utf-8")
    state = out_dir / "state"
    first = RunConfig(input_path=str(input_path), output_path=str(out_dir / "envelopes.jsonl"),
                      report_path=str(out_dir / "report.json"), state_dir=str(state),
                      workers=workers, web=web)
    code = run_batch(first)
    second = RunConfig(input_path=str(input_path),
                       output_path=str(out_dir / "rerun" / "envelopes.jsonl"),
                       report_path=str(out_dir / "rerun" / "report.json"), state_dir=str(state),
                       workers=workers, web=web)
    run_batch(second)
    envelopes = [json.loads(line) for line in (out_dir / "envelopes.jsonl").read_text(
        encoding="utf-8").splitlines()]
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    rerun = json.loads((out_dir / "rerun" / "report.json").read_text(encoding="utf-8"))
    result = score(envelopes, report, rerun)
    result["seed"] = seed
    result["rubric_estimate"] = rubric_estimate(result)
    (out_dir / "selfscore.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    (out_dir / "selfscore.md").write_text(_markdown(result, result["rubric_estimate"], seed),
                                          encoding="utf-8")
    print(_markdown(result, result["rubric_estimate"], seed))
    return code
