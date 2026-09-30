"""Persistent state: immutable content-addressed snapshots, a claim store keyed by stable
claim keys, typed change detection between runs, and per-run envelope checkpoints.

Everything for one company is written in a single SQLite transaction, so a crash never leaves a
half-updated company; re-running on the same source snapshot changes nothing but timestamps.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from .fetch import Snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    sha256 TEXT PRIMARY KEY, path TEXT NOT NULL, bytes INTEGER NOT NULL,
    content_type TEXT, first_seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fetches (
    url TEXT NOT NULL, sha256 TEXT NOT NULL, http_status INTEGER,
    first_retrieved_at TEXT NOT NULL, last_retrieved_at TEXT NOT NULL, times INTEGER NOT NULL,
    PRIMARY KEY (url, sha256));
CREATE TABLE IF NOT EXISTS claims (
    orgnr TEXT NOT NULL, claim_key TEXT NOT NULL, value_hash TEXT NOT NULL,
    field TEXT NOT NULL, section TEXT NOT NULL, claim_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL, first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL, is_current INTEGER NOT NULL, superseded_at TEXT,
    PRIMARY KEY (claim_key, value_hash));
CREATE INDEX IF NOT EXISTS claims_current ON claims (orgnr, is_current);
CREATE TABLE IF NOT EXISTS companies (
    orgnr TEXT PRIMARY KEY, first_observed_at TEXT NOT NULL, last_observed_at TEXT NOT NULL,
    last_run_id TEXT, observations INTEGER NOT NULL, checked_scopes TEXT);
CREATE TABLE IF NOT EXISTS change_log (
    orgnr TEXT NOT NULL, run_id TEXT NOT NULL, detected_at TEXT NOT NULL,
    change_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_envelopes (
    run_id TEXT NOT NULL, input_index INTEGER NOT NULL, orgnr TEXT NOT NULL,
    envelope_json TEXT NOT NULL, PRIMARY KEY (run_id, input_index));
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, input_sha256 TEXT, meta_json TEXT);
"""

# field -> (type when new, type when removed, type when changed, materiality)
_CHANGE_TYPES = {
    "legal_name": ("changed_name", "changed_name", "changed_name", "high"),
    "business_address": ("changed_address", "changed_address", "changed_address", "medium"),
    "postal_address": ("changed_address", "changed_address", "changed_address", "low"),
    "registered_employees": ("changed_employees", "changed_employees", "changed_employees",
                             "medium"),
    "bankrupt": ("status_change", "status_change", "status_change", "high"),
    "under_liquidation": ("status_change", "status_change", "status_change", "high"),
    "under_forced_liquidation": ("status_change", "status_change", "status_change", "high"),
    "deleted": ("status_change", "status_change", "status_change", "high"),
    "closed": ("status_change", "status_change", "status_change", "high"),
    "organisation_form": ("changed_legal_form", "changed_legal_form", "changed_legal_form",
                          "high"),
    "role": ("new_role", "removed_role", "changed_role", "medium"),
    "workplace": ("new_location", "closed_location", "changed_location", "medium"),
    "workplace_count": ("changed_location_count",) * 3 + ("low",),
    "accounts_period": ("new_filing", "new_filing", "new_filing", "high"),
    "latest_submitted_accounts_year": ("new_filing", "new_filing", "new_filing", "medium"),
    "filing_years": ("changed_filing_history",) * 3 + ("low",),
    "industry_code": ("changed_industry", "changed_industry", "changed_industry", "medium"),
    "registered_website": ("new_website", "removed_website", "changed_website", "medium"),
    "official_website": ("new_website", "removed_website", "changed_website", "medium"),
    "site_description": ("changed_description",) * 3 + ("low",),
    "job_posting": ("new_job", "closed_job", "changed_job", "medium"),
    "careers_page": ("new_careers_page", "removed_careers_page", "changed_careers_page", "low"),
    "news_item": ("new_activity", "removed_activity", "changed_activity", "low"),
    "social_profile": ("new_profile", "removed_profile", "changed_profile", "low"),
}
_SENIOR_ROLES = {"DAGL", "LEDE", "KONT", "INNH"}
_DERIVED_FIELDS = {"municipality"}  # derived from the address; the address change is reported
_ACCOUNT_VALUE_FIELDS = {
    "operating_revenue", "operating_expenses", "operating_result", "net_financial_items",
    "profit_before_tax", "net_result", "total_assets", "fixed_assets", "current_assets",
    "total_equity", "total_debt", "total_equity_and_debt", "audited"}


def value_hash(value) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def change_type(field: str, kind: str, value) -> tuple[str, str]:
    """kind is one of new/removed/changed. Returns (change_type, materiality)."""
    new, removed, changed, materiality = _CHANGE_TYPES.get(
        field, (f"new_{field}", f"removed_{field}", f"changed_{field}", "low"))
    if field == "role" and isinstance(value, dict) and value.get("role_code") in _SENIOR_ROLES:
        materiality = "high"
    if field in _ACCOUNT_VALUE_FIELDS:
        new = removed = changed = "changed_financials"
        materiality = "medium"
    return {"new": new, "removed": removed, "changed": changed}[kind], materiality


OPEN_TIMEOUT = 60.0


class StateStoreUnavailable(Exception):
    """The state directory's database could not be opened (e.g. held locked by another run)."""


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _retry_locked(fn, timeout: float):
    """Run `fn`, retrying with exponential backoff while the database is locked or busy."""
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not _is_lock_error(exc) or time.monotonic() + delay > deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 1.0)


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.root = Path(state_dir)
        try:
            (self.root / "snapshots").mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.root / "state.db", check_same_thread=False,
                                      isolation_level=None, timeout=OPEN_TIMEOUT)
            self.db.execute(f"PRAGMA busy_timeout={int(OPEN_TIMEOUT * 1000)}")
        except (OSError, sqlite3.Error) as exc:  # e.g. --state-dir is a regular file
            raise StateStoreUnavailable(f"cannot open state directory {self.root}: {exc}") from exc
        self._lock = threading.RLock()
        self._initialise()

    def _initialise(self) -> None:
        """Set up WAL and the schema. Another process opening the same state directory at the
        same moment can hold the lock; switching to WAL does not wait on SQLite's busy handler,
        so retry with backoff. If WAL still cannot be set, continue in the current journal mode
        (still correct, only less concurrent)."""
        try:
            _retry_locked(lambda: self.db.execute("PRAGMA journal_mode=WAL"), OPEN_TIMEOUT / 4)
        except sqlite3.OperationalError:
            pass

        def schema():
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(SCHEMA)
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(companies)")}
            if "checked_scopes" not in columns:  # state directories from before this column
                try:
                    self.db.execute("ALTER TABLE companies ADD COLUMN checked_scopes TEXT")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc):  # a concurrent opener migrated it
                        raise

        try:
            _retry_locked(schema, OPEN_TIMEOUT)
        except sqlite3.OperationalError as exc:
            raise StateStoreUnavailable(f"state store stayed locked: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # -- snapshots -------------------------------------------------------------------------
    def snapshot_path(self, sha256: str) -> Path:
        return self.root / "snapshots" / sha256[:2] / sha256

    def _save_snapshot(self, snap: Snapshot) -> None:
        sha = snap.sha256
        path = self.snapshot_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(snap.body)
            tmp.replace(path)
        self.db.execute(
            "INSERT OR IGNORE INTO snapshots (sha256, path, bytes, content_type, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sha, str(path.relative_to(self.root)), len(snap.body), snap.content_type,
             snap.retrieved_at))
        self.db.execute(
            "INSERT INTO fetches (url, sha256, http_status, first_retrieved_at, last_retrieved_at,"
            " times) VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT (url, sha256) DO UPDATE SET "
            "last_retrieved_at = excluded.last_retrieved_at, times = times + 1",
            (snap.url, sha, snap.status, snap.retrieved_at, snap.retrieved_at))

    def read_snapshot(self, sha256: str) -> bytes | None:
        path = self.snapshot_path(sha256)
        return path.read_bytes() if path.exists() else None

    # -- runs / checkpoints ----------------------------------------------------------------
    def start_run(self, run_id: str, started_at: str, input_sha256: str, meta: dict) -> None:
        with self._lock:
            _retry_locked(lambda: self.db.execute(
                "INSERT OR IGNORE INTO runs (run_id, started_at, input_sha256, meta_json) "
                "VALUES (?, ?, ?, ?)", (run_id, started_at, input_sha256, json.dumps(meta))),
                OPEN_TIMEOUT)

    def run_info(self, run_id: str) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT started_at, input_sha256, meta_json FROM runs "
                                  "WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return {"started_at": row[0], "input_sha256": row[1], "meta": json.loads(row[2] or "{}")}

    def completed_envelopes(self, run_id: str) -> dict[int, dict]:
        with self._lock:
            rows = self.db.execute("SELECT input_index, envelope_json FROM run_envelopes "
                                   "WHERE run_id = ?", (run_id,)).fetchall()
        return {idx: json.loads(blob) for idx, blob in rows}

    def save_envelope(self, run_id: str, index: int, envelope: dict) -> None:
        with self._lock:
            _retry_locked(lambda: self.db.execute(
                "INSERT OR REPLACE INTO run_envelopes VALUES (?, ?, ?, ?)",
                (run_id, index, envelope["organisation_number"],
                 json.dumps(envelope, ensure_ascii=False))), OPEN_TIMEOUT)

    # -- claims ----------------------------------------------------------------------------
    def company_history(self, orgnr: str) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT first_observed_at, last_observed_at, last_run_id, "
                                  "observations, checked_scopes FROM companies WHERE orgnr = ?",
                                  (orgnr,)).fetchone()
        if not row:
            return None
        return {"first_observed_at": row[0], "last_observed_at": row[1], "last_run_id": row[2],
                "observations": row[3], "checked_scopes": json.loads(row[4] or "[]")}

    def current_claims(self, orgnr: str) -> dict[str, dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT claim_key, value_hash, claim_json, evidence_json, first_observed_at, "
                "last_observed_at FROM claims WHERE orgnr = ? AND is_current = 1",
                (orgnr,)).fetchall()
        return {key: {"value_hash": vh, "claim": json.loads(cj), "evidence": json.loads(ej),
                      "first_observed_at": fo, "last_observed_at": lo}
                for key, vh, cj, ej, fo, lo in rows}

    def commit(self, orgnr: str, run_id: str, now: str, claims: list[dict],
               evidence: dict[str, dict], checked_scopes: set[str], snapshots: list[Snapshot],
               envelope_hook) -> dict:
        """Upsert this run's supported claims and detect changes, atomically.

        `claims` are serialised claim dicts (with `claim_key`, `scope`, `availability`).
        Only claims whose scope was fetched successfully this run can be reported as removed;
        previous values in unchecked scopes are carried forward, never silently dropped.
        `envelope_hook(result)` builds the final envelope inside the same transaction and
        returns (run_index, envelope) to checkpoint, or None.
        """
        def transaction():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                result = self._commit_locked(orgnr, run_id, now, claims, evidence,
                                             checked_scopes, snapshots)
                saved = envelope_hook(result)
                if saved is not None:
                    index, envelope = saved
                    self.db.execute("INSERT OR REPLACE INTO run_envelopes VALUES (?, ?, ?, ?)",
                                    (run_id, index, orgnr,
                                     json.dumps(envelope, ensure_ascii=False)))
                self.db.execute("COMMIT")
                return result
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

        # The whole transaction is retried if another process holds the write lock.
        with self._lock:
            return _retry_locked(transaction, OPEN_TIMEOUT)

    def _commit_locked(self, orgnr, run_id, now, claims, evidence, checked_scopes, snapshots):
        for snap in snapshots:
            if snap.ok or snap.body:
                self._save_snapshot(snap)
        history = self.company_history(orgnr)
        previous = self.current_claims(orgnr)
        observed: dict[str, dict] = {}
        for claim in claims:
            if claim["availability"] == "available":
                observed[claim["claim_key"]] = claim

        changes: list[dict] = []
        timestamps: dict[str, tuple[str, str]] = {}
        for key, claim in observed.items():
            vh = value_hash(claim["value"])
            ev = [evidence[e] for e in claim["evidence_ids"] if e in evidence]
            row = self.db.execute("SELECT first_observed_at FROM claims WHERE claim_key = ? "
                                  "AND value_hash = ?", (key, vh)).fetchone()
            first = row[0] if row else now
            stored_claim = {k: v for k, v in claim.items()
                            if k not in ("first_observed_at", "last_observed_at", "id")}
            self.db.execute(
                "INSERT INTO claims (orgnr, claim_key, value_hash, field, section, claim_json, "
                "evidence_json, first_observed_at, last_observed_at, is_current, superseded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL) ON CONFLICT (claim_key, value_hash) "
                "DO UPDATE SET last_observed_at = excluded.last_observed_at, is_current = 1, "
                "superseded_at = NULL, evidence_json = excluded.evidence_json, "
                "claim_json = excluded.claim_json",
                (orgnr, key, vh, claim["field"], claim["section"],
                 json.dumps(stored_claim, ensure_ascii=False), json.dumps(ev, ensure_ascii=False),
                 first, now))
            timestamps[key] = (first, now)
            prev = previous.get(key)
            if prev is None:
                # Only a source we had checked before can show something *new*; a source seen
                # for the first time (e.g. skipped by a rate limit last run) is not a change.
                if history is not None and claim.get("scope") in history["checked_scopes"]:
                    changes.append(self._change("new", claim, None, now, evidence))
            elif prev["value_hash"] != vh:
                self.db.execute("UPDATE claims SET is_current = 0, superseded_at = ? WHERE "
                                "claim_key = ? AND value_hash = ?", (now, key, prev["value_hash"]))
                changes.append(self._change("changed", claim, prev, now, evidence))

        carried: list[dict] = []
        for key, prev in previous.items():
            if key in observed:
                continue
            if prev["claim"].get("scope") in checked_scopes:
                self.db.execute("UPDATE claims SET is_current = 0, superseded_at = ? WHERE "
                                "claim_key = ? AND value_hash = ?", (now, key, prev["value_hash"]))
                changes.append(self._change("removed", prev["claim"], prev, now, evidence))
            else:
                carried.append(prev)

        changes = self._collapse_filing_changes(changes)
        for change in changes:
            self.db.execute("INSERT INTO change_log VALUES (?, ?, ?, ?)",
                            (orgnr, run_id, now, json.dumps(change, ensure_ascii=False)))
        scopes = sorted(set((history or {}).get("checked_scopes", [])) | set(checked_scopes))
        if history is None:
            self.db.execute("INSERT INTO companies VALUES (?, ?, ?, ?, 1, ?)",
                            (orgnr, now, now, run_id, json.dumps(scopes)))
        else:
            self.db.execute("UPDATE companies SET last_observed_at = ?, last_run_id = ?, "
                            "observations = observations + 1, checked_scopes = ? WHERE orgnr = ?",
                            (now, run_id, json.dumps(scopes), orgnr))
        return {"previous": history, "changes": changes, "timestamps": timestamps,
                "carried": carried}

    @staticmethod
    def _change(kind: str, claim: dict, prev: dict | None, now: str,
                current_evidence: dict[str, dict]) -> dict:
        ctype, materiality = change_type(claim["field"], kind,
                                         claim.get("value") if kind != "removed" else
                                         prev["claim"].get("value"))
        change = {
            "type": ctype,
            "kind": kind,
            "field": claim["field"],
            "label": claim.get("label"),
            "claim_key": claim["claim_key"],
            "materiality": materiality,
            "detected_at": now,
            "previous": None,
            "current": None,
            "evidence": {"previous": [], "current": []},
        }
        if prev is not None:
            change["previous"] = {"value": prev["claim"].get("value"),
                                  "first_observed_at": prev["first_observed_at"],
                                  "last_observed_at": prev["last_observed_at"]}
            # Prior evidence is preserved in full: it is not part of this run's evidence list.
            change["evidence"]["previous"] = prev["evidence"]
        if kind != "removed":
            change["current"] = {"value": claim.get("value")}
            change["evidence"]["current"] = [
                {"id": e, "source_url": current_evidence.get(e, {}).get("source_url")}
                for e in claim.get("evidence_ids", [])]
        return change

    @staticmethod
    def _collapse_filing_changes(changes: list[dict]) -> list[dict]:
        """A new filing period replaces every account value; report it once, not per line."""
        new_periods = {c["claim_key"].rsplit(":", 1)[-1] for c in changes
                       if c["field"] == "accounts_period"}
        if not new_periods:
            return [c for c in changes if c["field"] not in _DERIVED_FIELDS]
        kept = []
        for c in changes:
            if c["field"] in _DERIVED_FIELDS:
                continue
            if c["field"] == "latest_submitted_accounts_year":
                continue
            if c["field"] in _ACCOUNT_VALUE_FIELDS and \
                    c["claim_key"].rsplit(":", 1)[-1] in new_periods:
                continue
            kept.append(c)
        return kept
