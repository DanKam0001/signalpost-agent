"""Deterministic refresh replay: feed saved registry snapshots of one company through the real
research + store pipeline, pass by pass, and report the typed changes each pass produces.

Fixture layout (see tests/fixtures/replay/manifest.json):
    manifest.json  {"organisation_number": ..., "passes": [{"label", "dir"}, ...]}
    <dir>/entity.json, roles.json, subunits.json, accounts.json, years.json
A missing file is served as HTTP 404.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from .fetch import Fetcher, RawResponse
from .inputs import InputRow
from .registry import accounts_url, entity_url, filing_years_url, roles_url, subunits_url
from .research import Researcher, ResearchOptions
from .store import StateStore
from .urlsafety import UrlPolicy


class FixtureTransport:
    """Serves saved responses by exact URL; anything unknown is a 404, status None a
    connection failure."""

    def __init__(self, responses: dict[str, tuple[int, bytes, dict]] | None = None):
        self.responses = responses or {}
        self.requested: list[str] = []

    def __call__(self, url: str, timeout: float, max_bytes: int, accept: str) -> RawResponse:
        self.requested.append(url)
        status, body, headers = self.responses.get(url, (404, b"", {}))
        if status is None:
            return RawResponse(None, {}, b"", error="connection_error: ConnectError")
        return RawResponse(status, {"content-type": "application/json", **headers},
                           body[:max_bytes], truncated=len(body) > max_bytes)


def registry_responses(orgnr: str, folder: Path) -> dict[str, tuple[int, bytes, dict]]:
    files = {
        entity_url(orgnr): "entity.json",
        roles_url(orgnr): "roles.json",
        subunits_url(orgnr, 0): "subunits.json",
        accounts_url(orgnr): "accounts.json",
        filing_years_url(orgnr): "years.json",
    }
    out = {}
    for url, name in files.items():
        path = folder / name
        if path.exists():
            body = path.read_bytes()
            status = 410 if name == "entity.json" and b'"slettedato"' in body and \
                b'"navn"' not in body else 200
            out[url] = (status, body, {})
    return out


def run_replay(fixtures: str | Path, output: str | Path) -> int:
    root = Path(fixtures)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    orgnr = manifest["organisation_number"]
    passes = []
    with tempfile.TemporaryDirectory(prefix="signalpost-replay-") as state_dir:
        store = StateStore(state_dir)
        transport = FixtureTransport()
        fetcher = Fetcher(transport=transport, policy=UrlPolicy(frozenset()),
                          default_interval=0.0, sleep=lambda s: None)
        researcher = Researcher(fetcher, store, ResearchOptions(web=False))
        for number, spec in enumerate(manifest["passes"], start=1):
            transport.responses = registry_responses(orgnr, root / spec["dir"])
            row = InputRow(index=0, raw=orgnr, organisation_number=orgnr)
            far = time.monotonic() + 600
            env = researcher.research(row, f"replay-pass-{number}", far, far)
            snapshots = store.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            claims = store.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            passes.append({
                "pass": number,
                "label": spec.get("label"),
                "organisation_number": orgnr,
                "status": env["status"],
                "change_count": len(env["changes"]),
                "changes": env["changes"],
                "changes_text": env["summary"]["changes_text"],
                "claims_published": sum(1 for c in env["claims"]
                                        if c["availability"] == "available"),
                "stored_snapshots_total": snapshots,
                "stored_claim_versions_total": claims,
            })
        store.close()
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(passes, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    for p in passes:
        types = sorted({c["type"] for c in p["changes"]})
        print(f"pass {p['pass']} ({p['label']}): {p['change_count']} changes {types}")
    return 0 if passes and passes[-1]["change_count"] == 0 else 1
