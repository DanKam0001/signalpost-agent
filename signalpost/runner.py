"""Batch runner: one terminal envelope per input row, in input order, within the time budget.

Guarantees: every input line gets exactly one envelope (a `failed` one if research crashed, timed
out or the run's time budget ran out); completed companies are checkpointed in the state store so
`--resume` continues without duplicating or losing envelopes.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sqlite3
import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .fetch import Fetcher, utc_now
from .inputs import InputRow, read_input
from .model import SECTIONS, STATES
from .research import Abandoned, Researcher, ResearchOptions, failed_envelope
from .store import StateStore, StateStoreUnavailable

BRREG_INTERVALS = {
    "data.brreg.no": 0.04,  # ~25 requests/second overall, well inside Brreg's fair use
    # The annual-account copy index is limited by Brreg to about 30 requests per minute.
    "data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap": 2.1,
}


@dataclass
class RunConfig:
    input_path: str
    output_path: str
    report_path: str
    state_dir: str | None = None
    run_id: str | None = None
    workers: int = 8
    time_budget_seconds: float | None = None
    per_company_timeout: float = 90.0
    resume: bool = False
    expected_count: int | None = None
    registry_snapshot: str | None = None
    web: bool = True
    site_delay: float = 0.5
    history_wait: float = 5.0
    quiet: bool = False
    extra: dict = field(default_factory=dict)


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1)))))
    return ordered[k]


def _log(cfg: RunConfig, message: str) -> None:
    if not cfg.quiet:
        print(f"[signalpost {datetime.now(timezone.utc):%H:%M:%S}] {message}", file=sys.stderr,
              flush=True)


def build_researcher(cfg: RunConfig, store: StateStore, fetcher: Fetcher | None = None):
    from .urlsafety import UrlPolicy
    from .website import WebsiteResearch

    if fetcher is None:
        fetcher = Fetcher(policy=UrlPolicy(), rate_intervals=BRREG_INTERVALS,
                          default_interval=cfg.site_delay)
    snapshot = None
    if cfg.registry_snapshot:
        from .snapshot_file import RegistrySnapshot
        snapshot = RegistrySnapshot(cfg.registry_snapshot)
    options = ResearchOptions(web=cfg.web, registry_snapshot=snapshot,
                              history_max_wait=cfg.history_wait)
    return Researcher(fetcher, store, options, website_factory=WebsiteResearch), fetcher


class BatchRun:
    def __init__(self, cfg: RunConfig, fetcher: Fetcher | None = None):
        self.cfg = cfg
        self.output = Path(cfg.output_path)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(cfg.state_dir) if cfg.state_dir else self.output.parent / "state"
        self.store = StateStore(self.state_dir)
        self.researcher, self.fetcher = build_researcher(cfg, self.store, fetcher)
        self._lock = threading.Lock()
        self.finalized: set[int] = set()
        self.committing: set[int] = set()
        self.results: dict[int, dict] = {}

    # -- bookkeeping shared by workers and the main thread ---------------------------------
    def _claim_commit(self, index: int) -> bool:
        with self._lock:
            if index in self.finalized:
                return False
            self.committing.add(index)
            return True

    def _finalize_failed(self, row: InputRow, run_id: str, code: str, detail: str,
                         terminal_status: str) -> bool:
        with self._lock:
            if row.index in self.committing or row.index in self.finalized:
                return False
            self.finalized.add(row.index)
        env = failed_envelope(row, run_id, utc_now(), code, detail,
                              terminal_status=terminal_status)
        self.store.save_envelope(run_id, row.index, env)
        with self._lock:
            self.results[row.index] = env
        return True

    def _work(self, row: InputRow, run_id: str, run_deadline: float, started: dict) -> dict | None:
        started[row.index] = time.monotonic()
        company_deadline = started[row.index] + self.cfg.per_company_timeout
        try:
            env = self.researcher.research(row, run_id, company_deadline, run_deadline,
                                           index=row.index,
                                           claim_commit=lambda: self._claim_commit(row.index))
        except Abandoned:
            return None
        except Exception as exc:  # one company must never sink the batch
            detail = f"{type(exc).__name__}: {exc}"
            _log(self.cfg, f"{row.organisation_number}: crashed: {detail}\n"
                 + traceback.format_exc(limit=3))
            self._finalize_failed(row, run_id, "internal_error", detail, "failed")
            return None
        with self._lock:
            self.finalized.add(row.index)
            self.results[row.index] = env
        return env

    # -- main entry ------------------------------------------------------------------------
    def run(self) -> int:
        cfg = self.cfg
        t_start = time.monotonic()
        started_at = utc_now()
        input_bytes = Path(cfg.input_path).read_bytes()
        input_sha = hashlib.sha256(input_bytes).hexdigest()
        rows = read_input(cfg.input_path)
        frozen = self.researcher.options.registry_snapshot
        if frozen is not None:
            loaded = frozen.load({r.organisation_number for r in rows if not r.error})
            _log(cfg, f"registry snapshot {frozen.path.name}: {loaded} batch entities loaded")
        run_id = self._resolve_run_id(input_sha)
        self.store.start_run(run_id, started_at, input_sha,
                             {"input": str(cfg.input_path), "output": str(self.output)})
        (self.state_dir / "current_run.json").write_text(json.dumps(
            {"run_id": run_id, "input_sha256": input_sha, "output": str(self.output)}))

        if cfg.resume:
            for index, env in self.store.completed_envelopes(run_id).items():
                if index < len(rows) and env.get("organisation_number") in (
                        rows[index].organisation_number, rows[index].raw):
                    self.results[index] = env
                    self.finalized.add(index)
            _log(cfg, f"resume {run_id}: {len(self.results)} of {len(rows)} already done")

        budget = cfg.time_budget_seconds
        reserve = min(30.0, max(3.0, budget * 0.05)) if budget else 0.0
        run_deadline = t_start + budget - reserve if budget else float("inf")

        first_of: dict[str, int] = {}
        duplicates: dict[int, int] = {}
        todo: list[InputRow] = []
        for row in rows:
            key = row.organisation_number if not row.error else f"invalid:{row.index}"
            if key in first_of:
                duplicates[row.index] = first_of[key]
                continue
            first_of[key] = row.index
            if row.index not in self.results:
                todo.append(row)
        _log(cfg, f"run {run_id}: {len(rows)} inputs, {len(todo)} to research, "
                  f"{len(duplicates)} duplicates, workers={cfg.workers}")

        started: dict[int, float] = {}
        pool = ThreadPoolExecutor(max_workers=max(1, cfg.workers), thread_name_prefix="company")
        futures: dict[Future, InputRow] = {
            pool.submit(self._work, row, run_id, run_deadline, started): row for row in todo}
        pending = set(futures)
        grace = 10.0
        last_log = 0.0
        while pending:
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            now = time.monotonic()
            if now >= run_deadline:
                for fut in list(pending):
                    fut.cancel()
                    row = futures[fut]
                    self._finalize_failed(row, run_id, "time_budget_exhausted",
                                          "the run's time budget ran out before this company "
                                          "could be researched", "timed_out")
                break
            for fut in list(pending):
                row = futures[fut]
                begun = started.get(row.index)
                if begun and now - begun > cfg.per_company_timeout + grace:
                    if self._finalize_failed(row, run_id, "per_company_timeout",
                                             f"research exceeded {cfg.per_company_timeout:.0f}s",
                                             "timed_out"):
                        pending.discard(fut)
            if now - last_log > 10:
                last_log = now
                _log(cfg, f"progress: {len(self.results)}/{len(rows) - len(duplicates)} "
                          f"companies, {self.fetcher.totals.requests} requests")
        # Companies caught mid-commit when the budget ran out finish their (short) transaction.
        with self._lock:
            in_flight = [f for f in pending if futures[f].index in self.committing]
        if in_flight:
            wait(in_flight, timeout=10)
        pool.shutdown(wait=False, cancel_futures=True)

        envelopes = self._assemble(rows, duplicates, run_id)
        self._write_output(envelopes)
        report = self._report(rows, envelopes, duplicates, run_id, started_at, t_start)
        Path(cfg.report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
        _log(cfg, f"done: {len(envelopes)} envelopes for {len(rows)} inputs in "
                  f"{report['runtime_ms_total'] / 1000:.1f}s -> {self.output}")
        self.store.close()
        return 0 if report["count_matches_input"] else 2

    def _resolve_run_id(self, input_sha: str) -> str:
        if self.cfg.run_id:
            return self.cfg.run_id
        marker = self.state_dir / "current_run.json"
        if self.cfg.resume and marker.exists():
            previous = json.loads(marker.read_text())
            if previous.get("input_sha256") == input_sha:
                return previous["run_id"]
        return f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{input_sha[:8]}"

    def _assemble(self, rows: list[InputRow], duplicates: dict[int, int], run_id: str) -> list[dict]:
        envelopes = []
        for row in rows:
            source_index = duplicates.get(row.index, row.index)
            env = self.results.get(source_index)
            if env is None:
                env = failed_envelope(row, run_id, utc_now(), "missing_result",
                                      "no result was produced for this company")
            if source_index != row.index:
                env = json.loads(json.dumps(env))
                env["input"] = {"index": row.index, "raw": row.raw,
                                "duplicate_of_index": source_index}
            envelopes.append(env)
        return envelopes

    def _write_output(self, envelopes: list[dict]) -> None:
        tmp = self.output.with_name(self.output.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for env in envelopes:
                fh.write(json.dumps(env, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.output)

    def _report(self, rows, envelopes, duplicates, run_id, started_at, t_start) -> dict:
        cfg = self.cfg
        total_ms = int((time.monotonic() - t_start) * 1000)
        researched = [e for i, e in enumerate(envelopes) if i not in duplicates]
        runtimes = [e["operations"]["runtime_ms"] for e in researched
                    if e["run"]["terminal_status"] == "completed"]
        state_counts = dict.fromkeys(STATES, 0)
        terminal: dict[str, int] = {}
        section_counts = {name: dict.fromkeys(STATES, 0) for name in SECTIONS}
        for e in envelopes:
            state_counts[e["status"]] += 1
            terminal[e["run"]["terminal_status"]] = terminal.get(e["run"]["terminal_status"], 0) + 1
            for name in SECTIONS:
                section_counts[name][e["sections"][name]["availability"]] += 1
        matches = len(envelopes) == len(rows) and all(
            e["input"]["index"] == r.index and e["organisation_number"] in (r.organisation_number,
                                                                          r.raw)
            for e, r in zip(envelopes, rows, strict=True))
        totals = self.fetcher.totals
        years_fetched = years_skipped = 0
        for e in researched:
            years = next((c for c in e["claims"] if c["field"] == "filing_years"), None)
            if years is None:
                continue
            if years.get("carried_forward") or years["availability"] == "blocked":
                years_skipped += 1
            elif years["availability"] in ("available", "not_available"):
                years_fetched += 1
        return {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": utc_now(),
            "agent_version": __version__,
            "input_path": str(cfg.input_path),
            "output_path": str(self.output),
            "state_dir": str(self.state_dir),
            "input_count": len(rows),
            "envelope_count": len(envelopes),
            "expected_count": cfg.expected_count,
            "count_matches_input": matches,
            "count_matches_expected": cfg.expected_count in (None, len(envelopes)),
            "duplicate_inputs": len(duplicates),
            "invalid_inputs": sum(1 for r in rows if r.error),
            "state_counts": state_counts,
            "terminal_status_counts": terminal,
            "section_state_counts": section_counts,
            "fast_path_count": sum(1 for e in researched if e["run"].get("fast_path")),
            "runtime_ms_total": total_ms,
            "runtime_ms_p50": _percentile(runtimes, 50),
            "runtime_ms_p95": _percentile(runtimes, 95),
            "runtime_ms_max": max(runtimes) if runtimes else None,
            "companies_per_minute": round(len(researched) / total_ms * 60000, 1)
            if total_ms else None,
            "time_budget_seconds": cfg.time_budget_seconds,
            "per_company_timeout_seconds": cfg.per_company_timeout,
            "workers": cfg.workers,
            "requests_total": totals.requests,
            "requests_by_host": dict(sorted(totals.per_host.items())),
            "requests_by_source": dict(sorted(totals.per_source.items())),
            "bytes_fetched": totals.bytes,
            "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "third_party_cost_usd": 0,
            "llm_calls": 0,
            "state_store": "ok",
            "filing_years_fetched": years_fetched,
            "filing_years_skipped": years_skipped,
            "changes_total": sum(len(e["changes"]) for e in researched),
            "companies_with_changes": sum(1 for e in researched if e["changes"]),
        }


def run_batch(cfg: RunConfig) -> int:
    try:
        batch = BatchRun(cfg)
    except (StateStoreUnavailable, sqlite3.Error, OSError) as exc:
        return _emit_all_failed(cfg, f"{type(exc).__name__}: {exc}")
    return batch.run()


def _emit_all_failed(cfg: RunConfig, detail: str) -> int:
    """Last resort when the state store cannot be opened: still one envelope per input."""
    _log(cfg, f"state store unavailable, emitting failed envelopes: {detail}")
    started_at = utc_now()
    rows = read_input(cfg.input_path)
    run_id = cfg.run_id or f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-nostate"
    envelopes = [failed_envelope(row, run_id, started_at, "state_store_unavailable", detail)
                 for row in rows]
    output = Path(cfg.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n"
                              for e in envelopes), encoding="utf-8")
    report = {"run_id": run_id, "started_at": started_at, "completed_at": utc_now(),
              "input_count": len(rows), "envelope_count": len(envelopes),
              "expected_count": cfg.expected_count, "count_matches_input": True,
              "duplicate_inputs": 0, "state_counts": {**dict.fromkeys(STATES, 0),
                                                      "failed": len(envelopes)},
              "runtime_ms_total": 0, "runtime_ms_p50": None, "runtime_ms_p95": None,
              "requests_total": 0, "requests_by_host": {}, "bytes_fetched": 0,
              "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                                      1),
              "third_party_cost_usd": 0, "time_budget_seconds": cfg.time_budget_seconds,
              "fast_path_count": 0, "filing_years_fetched": 0, "filing_years_skipped": 0,
              "state_store": "unavailable",
              "error": f"state_store_unavailable: {detail}"}
    Path(cfg.report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0
