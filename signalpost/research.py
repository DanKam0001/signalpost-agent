"""Per-company research: registry → company-owned sources → claims → store → envelope."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import __version__
from .fetch import Fetcher, Operations, utc_now
from .inputs import InputRow
from .model import (AMBIGUOUS, AVAILABLE, BLOCKED, FAILED, NOT_APPLICABLE, NOT_AVAILABLE,
                    SECTIONS, Claim, Collector, json_value, short_hash)
from .registry import RegistryResearch
from .store import StateStore
from .summary import build_summary

AGENT = {"name": "signalpost-registry-first", "version": __version__}
_SEVERITY = {AVAILABLE: 0, NOT_APPLICABLE: 1, NOT_AVAILABLE: 2, AMBIGUOUS: 3, BLOCKED: 4,
             FAILED: 5}


class Abandoned(Exception):
    """The runner gave up on this company; its late result must not be recorded."""


@dataclass
class ResearchOptions:
    web: bool = True
    history_max_wait: float = 5.0
    fast_path_seconds: float = 20.0   # below this much run time left: registry identity only
    registry_snapshot: object | None = None  # snapshot_file.RegistrySnapshot


def scope_of(claim: Claim) -> str:
    if claim.field in ("registered_website", "registered_email_domain",
                       "latest_submitted_accounts_year"):
        return "entity"
    if claim.section == "legal_identity_and_brand" and claim.field not in ("brand_name",):
        return "entity"
    if claim.field == "role":
        return "roles"
    if claim.field in ("workplace", "workplace_count"):
        return "subunits"
    if claim.field == "filing_years":
        return "filing_years"
    if claim.section == "annual_accounts":
        return "accounts"
    return "website"


def serialise_claims(orgnr: str, claims: list[Claim]) -> tuple[list[dict], dict[str, dict]]:
    """Claims → dicts (deduplicated by claim key) plus the evidence table."""
    evidence: dict[str, dict] = {}
    out: dict[str, dict] = {}
    for claim in claims:
        key = claim.key(orgnr)
        ev_ids = []
        for ev in claim.evidence:
            evidence.setdefault(ev.id, json_value(ev.to_dict()))
            ev_ids.append(ev.id)
        if key in out:  # the same fact seen twice (e.g. on two pages): merge evidence
            out[key]["evidence_ids"] = sorted(set(out[key]["evidence_ids"]) | set(ev_ids))
            continue
        data = {
            "id": "c-" + key_hash(key),
            "claim_key": key,
            "field": claim.field,
            "label": claim.label,
            "section": claim.section,
            "scope": scope_of(claim),
            "value": json_value(claim.value),
            "availability": claim.availability,
            "confidence": claim.confidence,
            "evidence_ids": ev_ids,
        }
        if claim.effective_date:
            data["effective_date"] = claim.effective_date
        if claim.reporting_period:
            data["reporting_period"] = claim.reporting_period
        if claim.reason:
            data["reason"] = claim.reason
        data.update(json_value(claim.extra))
        out[key] = data
    return list(out.values()), evidence


def key_hash(key: str) -> str:
    return short_hash(key)


def _combine(states: list[tuple[str, str]]) -> tuple[str, str]:
    if not states:
        return NOT_AVAILABLE, "not checked"
    if any(s == AVAILABLE for s, _ in states):
        return AVAILABLE, "; ".join(r for _, r in states)
    worst = max(states, key=lambda s: _SEVERITY.get(s[0], 0))
    return worst[0], "; ".join(r for _, r in states)


class Researcher:
    def __init__(self, fetcher: Fetcher, store: StateStore, options: ResearchOptions | None = None,
                 website_factory=None):
        self.fetcher = fetcher
        self.store = store
        self.options = options or ResearchOptions()
        self.website_factory = website_factory
        # Side lane for the rate-limited filing-years endpoint (runs alongside other research).
        self.side_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="history")

    def research(self, row: InputRow, run_id: str, company_deadline: float,
                 run_deadline: float, index: int | None = None,
                 claim_commit=lambda: True) -> dict:
        """Research one company and return its envelope.

        `claim_commit()` is asked right before the store transaction commits; if it returns
        False (the batch runner already emitted a timeout envelope) the transaction rolls back
        and `Abandoned` is raised, so a late result never overwrites the emitted envelope.
        """
        started_at = utc_now()
        t0 = time.monotonic()
        ops = Operations()
        orgnr = row.organisation_number
        if row.error:
            return failed_envelope(row, run_id, started_at, "invalid_organisation_number",
                                   row.error, ops, t0)
        c = Collector(orgnr)
        deadline = lambda: min(company_deadline, run_deadline)  # noqa: E731
        reg = RegistryResearch(self.fetcher, c, ops, deadline, self.options.history_max_wait)
        result = reg.identity()
        frozen = self.options.registry_snapshot
        if result.status in (BLOCKED, FAILED) and frozen is not None and frozen.get(orgnr):
            result = reg.identity_from_snapshot(frozen.get(orgnr), frozen, result)
        fast_path = run_deadline - time.monotonic() < self.options.fast_path_seconds
        if result.status == AVAILABLE and not fast_path:
            reg.roles()
            if result.is_subunit:
                c.set_section("workplaces", NOT_APPLICABLE,
                              "the organisation number is itself a sub-unit")
                c.set_section("accounts", NOT_APPLICABLE,
                              "sub-units do not file annual accounts; the parent unit does")
            else:
                history = self.side_pool.submit(reg.fetch_filing_years)
                reg.subunits()
                reg.accounts()
            if self.options.web and self.website_factory is not None:
                self.website_factory(self.fetcher, c, ops, deadline, result.entity, row).run()
            else:
                c.set_section("website", NOT_AVAILABLE,
                              "not checked: company website research disabled for this run")
            if not result.is_subunit:
                reg.filing_years(history.result())
        elif result.status == AVAILABLE:
            c.fast_path = True
            for name in ("roles", "workplaces", "accounts", "website"):
                c.set_section(name, FAILED, "time_budget_exhausted: registry-only fast path")

        claims, evidence = serialise_claims(orgnr, c.claims)
        completed_at = utc_now()
        if result.status in (AVAILABLE, NOT_AVAILABLE):
            captured = {}

            def capture(store_result):
                if not claim_commit():
                    raise Abandoned(orgnr)
                captured["env"] = assemble(row, run_id, started_at, completed_at, result, c,
                                           claims, evidence, store_result, ops, t0)
                return (index, captured["env"]) if index is not None else None

            self.store.commit(orgnr, run_id, completed_at, claims, evidence, c.checked,
                              c.raw_snapshots, capture)
            return captured["env"]
        env = assemble(row, run_id, started_at, completed_at, result, c, claims, evidence,
                       {"previous": self.store.company_history(orgnr), "changes": [],
                        "timestamps": {}, "carried": []}, ops, t0)
        if index is not None:
            if not claim_commit():
                raise Abandoned(orgnr)
            self.store.save_envelope(run_id, index, env)
        return env


def _state(pair: tuple[str, str]) -> dict:
    return {"availability": pair[0], "reason": pair[1]}


def _sections(result, c: Collector, claims: list[dict], changes: list[dict],
              history: dict | None) -> dict:
    by_section: dict[str, list[str]] = {name: [] for name in SECTIONS}
    for claim in claims:
        by_section[claim["section"]].append(claim["id"])
    st = c.section_state
    sections: dict[str, dict] = {}
    if result.status != AVAILABLE:
        for name in SECTIONS[:5]:
            sections[name] = {"availability": result.status, "reason": result.reason}
        if any(cl["field"] == "deleted" for cl in claims):
            sections["legal_identity_and_brand"] = {
                "availability": AVAILABLE, "reason": result.reason}
    else:
        sections["legal_identity_and_brand"] = {"availability": AVAILABLE, "reason": result.reason}
        accounts_state = st.get("accounts", (NOT_AVAILABLE, "not checked"))
        years = [cl for cl in claims if cl["field"] == "filing_years"]
        if accounts_state[0] != AVAILABLE and years and years[0]["availability"] == AVAILABLE:
            accounts_state = (AVAILABLE, accounts_state[1] + "; filing history available")
        sections["annual_accounts"] = _state(accounts_state)
        parts = [(st[key][0], f"{key}: {st[key][1]}") for key in ("roles", "workplaces")
                 if key in st]
        sections["leadership_and_workplaces"] = _state(_combine(parts))
        for name, key in (("website_and_profiles", "website"), ("hiring_and_activity", "hiring")):
            sections[name] = _state(st.get(key) or st.get("website")
                                    or (NOT_AVAILABLE, "not checked"))
    available = [cl for cl in claims if cl["availability"] == AVAILABLE]
    unsupported = [cl["id"] for cl in available if not cl["evidence_ids"]]
    sections["evidence_and_availability"] = {
        "availability": AVAILABLE if claims else result.status,
        "reason": (f"{len(available)} available claims, all with evidence" if not unsupported
                   else f"{len(unsupported)} available claims lack evidence"),
        "details": {"claims_total": len(claims), "claims_available": len(available),
                    "claims_unavailable": len(claims) - len(available)},
    }
    by_section["evidence_and_availability"] = [cl["id"] for cl in claims
                                               if cl["availability"] != AVAILABLE]
    refresh_reason = ("first observation" if history is None else
                      f"{len(changes)} change(s) since {history['last_observed_at']}")
    sections["refresh_and_changes"] = {
        "availability": AVAILABLE if result.status in (AVAILABLE, NOT_AVAILABLE) else result.status,
        "reason": refresh_reason,
    }
    by_section["refresh_and_changes"] = sorted({cid for ch in changes
                                                for cid in ch.get("claim_ids", [])})
    for name in SECTIONS:
        sections[name]["claim_ids"] = by_section[name]
        sections[name]["sources"] = c.sources.get(name, [])
    return sections


def assemble(row, run_id, started_at, completed_at, result, c: Collector, claims, evidence,
             store_result, ops: Operations, t0: float) -> dict:
    history = store_result.get("previous")
    changes = store_result.get("changes", [])
    for claim in claims:
        first, last = store_result.get("timestamps", {}).get(claim["claim_key"], (None, None))
        if first:
            claim["first_observed_at"], claim["last_observed_at"] = first, last
    for change in changes:
        cid = "c-" + key_hash(change["claim_key"])
        change["claim_ids"] = [cid] if change.get("current") else []
    # A source that failed this run keeps its last supported value. If this run also produced
    # an unavailable claim under the same key, the carried value replaces it (one claim per
    # key) and the failure is exposed on the claim as `refresh_status`.
    by_key = {claim["claim_key"]: i for i, claim in enumerate(claims)}
    all_claims = list(claims)
    for prev in store_result.get("carried", []) if result.status == AVAILABLE else []:
        claim = dict(prev["claim"])
        claim.update(id="c-" + key_hash(claim["claim_key"]), carried_forward=True,
                     first_observed_at=prev["first_observed_at"],
                     last_observed_at=prev["last_observed_at"],
                     reason="source not refreshed this run; last supported value kept")
        for ev in prev["evidence"]:
            evidence.setdefault(ev["id"], ev)
        status = {"status": "not_refetched", "availability": None,
                  "reason": "source not refreshed this run"}
        if claim["claim_key"] in by_key:
            current = all_claims[by_key[claim["claim_key"]]]
            status.update(availability=current["availability"], reason=current.get("reason"))
            claim["reason"] = (f"not refreshed this run ({current.get('reason')}); "
                               "last supported value kept")
            all_claims[by_key[claim["claim_key"]]] = claim
        else:
            all_claims.append(claim)
        claim["refresh_status"] = status
        c.sources[claim["section"]].append({
            "source": "carried_forward", "claim_key": claim["claim_key"],
            "outcome": "not_refetched", "reason": status["reason"],
            "last_observed_at": claim["last_observed_at"]})
    sections = _sections(result, c, all_claims, changes, history)
    summary = build_summary(all_claims, sections, changes, history, result.legal_identity,
                            result.status, result.reason)
    runtime_ms = int((time.monotonic() - t0) * 1000)
    return {
        "organisation_number": row.organisation_number,
        "input": {"index": row.index, "raw": row.raw},
        "status": result.status,
        "status_reason": result.reason,
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": completed_at,
                "terminal_status": "completed", "fast_path": c.fast_path},
        "legal_identity": result.legal_identity or {"organisation_number": row.organisation_number},
        "sections": sections,
        "claims": all_claims,
        "evidence": list(evidence.values()),
        "source_snapshots": list(c.snapshots.values()),
        "changes": changes,
        "refresh": {
            "first_observed_at": (history or {}).get("first_observed_at") or completed_at,
            "previous_observed_at": (history or {}).get("last_observed_at"),
            "previous_run_id": (history or {}).get("last_run_id"),
            "observation_number": ((history or {}).get("observations") or 0) + 1,
            "change_count": len(changes),
        },
        "summary": summary,
        "errors": c.errors,
        "operations": _operations(ops, runtime_ms),
        "agent": AGENT,
    }


def _operations(ops: Operations, runtime_ms: int) -> dict:
    return {"requests": ops.requests, "runtime_ms": runtime_ms, "third_party_cost_usd": 0,
            "bytes_fetched": ops.bytes, "requests_by_source": dict(sorted(ops.per_source.items())),
            "requests_by_host": dict(sorted(ops.per_host.items()))}


def failed_envelope(row: InputRow, run_id: str, started_at: str, code: str, detail: str,
                    ops: Operations | None = None, t0: float | None = None,
                    terminal_status: str = "failed") -> dict:
    ops = ops or Operations()
    runtime_ms = int((time.monotonic() - t0) * 1000) if t0 else 0
    reason = f"{code}: {detail}"
    sections = {name: {"availability": FAILED, "reason": reason, "claim_ids": [], "sources": []}
                for name in SECTIONS}
    unknowns = [{"section": name, "availability": FAILED, "text": reason} for name in SECTIONS[:5]]
    return {
        "organisation_number": row.organisation_number or row.raw,
        "input": {"index": row.index, "raw": row.raw},
        "status": FAILED,
        "status_reason": reason,
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": utc_now(),
                "terminal_status": terminal_status},
        "legal_identity": {"organisation_number": row.organisation_number or row.raw},
        "sections": sections,
        "claims": [],
        "evidence": [],
        "source_snapshots": [],
        "changes": [],
        "refresh": {"first_observed_at": None, "previous_observed_at": None,
                    "previous_run_id": None, "observation_number": None, "change_count": 0},
        "summary": {"text": f"No profile: {detail}.", "sentences": [], "unknowns": unknowns,
                    "changes_text": "No refresh: the company could not be researched this run.",
                    "generated_by": "deterministic"},
        "errors": [{"section": None, "code": code, "detail": detail, "url": None}],
        "operations": _operations(ops, runtime_ms),
        "agent": AGENT,
    }
