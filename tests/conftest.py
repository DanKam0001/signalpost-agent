"""Shared offline test helpers: saved Brreg responses and fixture websites served by URL."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from signalpost.fetch import Fetcher
from signalpost.inputs import InputRow
from signalpost.registry import accounts_url, entity_url, filing_years_url, roles_url, subunits_url
from signalpost.replay import FixtureTransport
from signalpost.research import Researcher, ResearchOptions
from signalpost.store import StateStore
from signalpost.urlsafety import UrlPolicy
from signalpost.website import WebsiteResearch

FIXTURES = Path(__file__).parent / "fixtures"
HTML = {"content-type": "text/html; charset=utf-8"}


def brreg(orgnr: str, skip: tuple[str, ...] = ()) -> dict:
    """Saved Brreg responses for `orgnr` keyed by the exact API URL."""
    urls = {"entity": entity_url(orgnr), "roles": roles_url(orgnr),
            "subunits": subunits_url(orgnr, 0), "accounts": accounts_url(orgnr),
            "years": filing_years_url(orgnr)}
    out = {}
    for name, url in urls.items():
        path = FIXTURES / "brreg" / f"{orgnr}.{name}.json"
        if path.exists() and name not in skip:
            body = path.read_bytes()
            status = 410 if b'"slettedato"' in body and b'"navn"' not in body else 200
            out[url] = (status, body, {})
    return out


def site_file(name: str) -> bytes:
    return (FIXTURES / "sites" / name).read_bytes()


def page(name: str, status: int = 200, headers: dict | None = None):
    return (status, site_file(name), headers or HTML)


def make_fetcher(responses: dict, allow_hosts=()) -> tuple[Fetcher, FixtureTransport]:
    transport = FixtureTransport(responses)
    fetcher = Fetcher(transport=transport, policy=UrlPolicy(frozenset(allow_hosts)),
                      default_interval=0.0, sleep=lambda s: None)
    return fetcher, transport


def research(tmp_path, responses: dict, orgnr: str, *, web: bool = False, row: dict | None = None,
             allow_hosts=(), store: StateStore | None = None) -> dict:
    fetcher, _ = make_fetcher(responses, allow_hosts)
    store = store or StateStore(tmp_path / "state")
    researcher = Researcher(fetcher, store, ResearchOptions(web=web),
                            website_factory=WebsiteResearch)
    far = time.monotonic() + 120
    input_row = InputRow(index=0, raw=orgnr, organisation_number=orgnr, row=row or {})
    env = researcher.research(input_row, "test-run", far, far)
    assert_unique_claims(env)
    return env


def assert_unique_claims(env: dict) -> None:
    """Guard applied to every envelope the tests produce: one claim per id and per claim_key."""
    ids = [c["id"] for c in env["claims"]]
    keys = [c["claim_key"] for c in env["claims"]]
    assert len(ids) == len(set(ids)), f"duplicate claim ids in {env['organisation_number']}"
    assert len(keys) == len(set(keys)), f"duplicate claim keys in {env['organisation_number']}"


def resolve_pointer(document, pointer: str):
    """RFC 6901."""
    node = document
    if pointer == "":
        return node
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def claims_by_field(env: dict, field: str) -> list[dict]:
    return [c for c in env["claims"] if c["field"] == field]


def evidence_of(env: dict, claim: dict) -> list[dict]:
    table = {e["id"]: e for e in env["evidence"]}
    return [table[i] for i in claim["evidence_ids"]]


@pytest.fixture
def equinor(tmp_path):
    return research(tmp_path, brreg("923609016"), "923609016")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
