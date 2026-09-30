"""Claims, evidence and the per-company collector that assembles them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from .fetch import Snapshot

AVAILABLE = "available"
NOT_AVAILABLE = "not_available"
BLOCKED = "blocked"
NOT_APPLICABLE = "not_applicable"
AMBIGUOUS = "ambiguous"
FAILED = "failed"
STATES = (AVAILABLE, NOT_AVAILABLE, BLOCKED, NOT_APPLICABLE, AMBIGUOUS, FAILED)

SECTIONS = (
    "legal_identity_and_brand",
    "annual_accounts",
    "leadership_and_workplaces",
    "website_and_profiles",
    "hiring_and_activity",
    "evidence_and_availability",
    "refresh_and_changes",
)

# Source classes used on evidence records.
OFFICIAL_REGISTRY = "official_registry"
OFFICIAL_ACCOUNTS = "official_accounts"
COMPANY_OWNED = "company_owned"


def short_hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def snapshot_id(url: str, sha256: str) -> str:
    return "snap-" + short_hash(f"{url}|{sha256}")


def json_value(value):
    """Make a value JSON-safe while keeping financial decimals exact."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        as_float = float(value)
        return as_float if Decimal(repr(as_float)) == value else str(value)
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


@dataclass
class Evidence:
    source_url: str
    source_class: str
    retrieved_at: str
    content_sha256: str
    extraction_method: str
    human_url: str | None = None
    record_date: str | None = None
    record_date_field: str | None = None
    json_pointer: str | None = None
    css_selector: str | None = None
    claim_span: str | None = None

    @property
    def id(self) -> str:
        locator = f"{self.json_pointer}|{self.css_selector}|{self.claim_span}"
        return "ev-" + short_hash(f"{self.source_url}|{self.content_sha256}|{locator}")

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "source_url": self.source_url,
            "human_url": self.human_url,
            "source_class": self.source_class,
            "retrieved_at": self.retrieved_at,
            "record_date": self.record_date,
            "record_date_field": self.record_date_field,
            "content_sha256": self.content_sha256,
            "snapshot_id": snapshot_id(self.source_url, self.content_sha256),
            "extraction_method": self.extraction_method,
            "json_pointer": self.json_pointer,
            "css_selector": self.css_selector,
            "claim_span": self.claim_span,
        }
        return {k: v for k, v in data.items() if v is not None or k in ("record_date",)}


@dataclass
class Claim:
    field: str
    label: str
    section: str
    value: object
    availability: str
    identity: str = ""
    confidence: float = 1.0
    evidence: list[Evidence] = field(default_factory=list)
    effective_date: str | None = None
    reporting_period: dict | None = None
    reason: str | None = None
    extra: dict = field(default_factory=dict)

    def key(self, orgnr: str) -> str:
        return f"{orgnr}:{self.field}" + (f":{self.identity}" if self.identity else "")


class Collector:
    """Accumulates claims, evidence, snapshots, source outcomes and errors for one company."""

    def __init__(self, orgnr: str):
        self.orgnr = orgnr
        self.claims: list[Claim] = []
        self.snapshots: dict[str, dict] = {}
        self.raw_snapshots: list[Snapshot] = []
        self.sources: dict[str, list[dict]] = {name: [] for name in SECTIONS}
        self.section_state: dict[str, tuple[str, str]] = {}
        self.checked: set[str] = set()  # source scopes fetched successfully this run
        self.fast_path = False          # time budget forced registry-identity-only research
        self.errors: list[dict] = []

    def add(self, claim: Claim) -> Claim:
        self.claims.append(claim)
        return claim

    def keep_snapshot(self, snap: Snapshot, source_class: str) -> None:
        self.raw_snapshots.append(snap)
        sid = snapshot_id(snap.url, snap.sha256)
        self.snapshots.setdefault(sid, {
            "id": sid,
            "source": snap.source,
            "source_class": source_class,
            "url": snap.url,
            "final_url": snap.final_url or snap.url,
            "redirects": snap.redirects,
            "http_status": snap.status,
            "retrieved_at": snap.retrieved_at,
            "content_sha256": snap.sha256,
            "content_type": snap.content_type,
            "bytes": len(snap.body),
            "truncated": snap.truncated,
        })

    def note_source(self, section: str, snap: Snapshot, outcome: str | None = None) -> None:
        self.sources[section].append({
            "source": snap.source,
            "url": snap.url,
            "http_status": snap.status,
            "outcome": outcome or snap.outcome(),
            "retrieved_at": snap.retrieved_at,
        })

    def set_section(self, section: str, availability: str, reason: str) -> None:
        self.section_state[section] = (availability, reason)

    def error(self, section: str, code: str, detail: str, url: str | None = None) -> None:
        self.errors.append({"section": section, "code": code, "detail": detail, "url": url})
