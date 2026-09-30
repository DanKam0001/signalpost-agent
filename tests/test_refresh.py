import json

from conftest import FIXTURES, brreg, research

from signalpost.registry import roles_url
from signalpost.replay import run_replay
from signalpost.store import StateStore


def test_replay_reports_expected_changes_and_zero_on_identical(tmp_path):
    out = tmp_path / "replay.json"
    assert run_replay(FIXTURES / "replay", out) == 0
    passes = json.loads(out.read_text())
    manifest = json.loads((FIXTURES / "replay" / "manifest.json").read_text())
    assert passes[0]["change_count"] == 0
    assert sorted({c["type"] for c in passes[1]["changes"]}) == \
        manifest["expected_pass2_change_types"]
    assert passes[2]["changes"] == []
    assert passes[2]["stored_snapshots_total"] == passes[1]["stored_snapshots_total"]
    for change in passes[1]["changes"]:
        assert {"type", "claim_key", "previous", "current", "evidence", "materiality"} <= set(change)
        if change["previous"] is not None:
            assert change["evidence"]["previous"][0]["source_url"].startswith("https://")


def test_rerun_same_snapshot_is_idempotent(tmp_path):
    store = StateStore(tmp_path / "state")
    first = research(tmp_path, brreg("923609016"), "923609016", store=store)
    snaps = store.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    second = research(tmp_path, brreg("923609016"), "923609016", store=store)
    assert second["changes"] == []
    assert store.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == snaps
    strip = lambda env: sorted((c["claim_key"], json.dumps(c["value"], sort_keys=True))  # noqa
                               for c in env["claims"])
    assert strip(first) == strip(second)
    assert [c["id"] for c in first["claims"]] == [c["id"] for c in second["claims"]]


def test_failed_refresh_keeps_last_value_and_reports_no_removal(tmp_path):
    store = StateStore(tmp_path / "state")
    research(tmp_path, brreg("810034882"), "810034882", store=store)
    responses = brreg("810034882")
    responses[roles_url("810034882")] = (503, b"", {})
    env = research(tmp_path, responses, "810034882", store=store)
    assert not [c for c in env["changes"] if c["type"] == "removed_role"]
    carried = [c for c in env["claims"] if c.get("carried_forward")]
    assert carried and all(c["field"] == "role" for c in carried)
    assert "source error" in env["sections"]["leadership_and_workplaces"]["reason"]


def test_source_seen_for_the_first_time_is_not_a_change(tmp_path):
    from signalpost.registry import filing_years_url
    store = StateStore(tmp_path / "state")
    responses = brreg("810034882")
    skipped = dict(responses)
    skipped[filing_years_url("810034882")] = (429, b"", {})
    research(tmp_path, skipped, "810034882", store=store)
    env = research(tmp_path, responses, "810034882", store=store)
    assert env["changes"] == []
    assert any(c["field"] == "filing_years" and c["availability"] == "available"
               for c in env["claims"])


def test_carried_value_replaces_unavailable_claim_with_same_key(tmp_path):
    from signalpost.registry import filing_years_url
    store = StateStore(tmp_path / "state")
    responses = brreg("810034882")
    research(tmp_path, responses, "810034882", store=store)
    skipped = dict(responses)
    skipped[filing_years_url("810034882")] = (429, b"", {})
    env = research(tmp_path, skipped, "810034882", store=store)
    keys = [c["claim_key"] for c in env["claims"]]
    ids = [c["id"] for c in env["claims"]]
    assert len(keys) == len(set(keys)) and len(ids) == len(set(ids))
    years = [c for c in env["claims"] if c["field"] == "filing_years"]
    assert len(years) == 1 and years[0]["carried_forward"]
    assert years[0]["availability"] == "available"
    assert years[0]["refresh_status"]["status"] == "not_refetched"
    assert years[0]["refresh_status"]["availability"] == "blocked"
    assert env["changes"] == []


def test_rate_limit_skip_reason_names_the_source_limit(tmp_path):
    from signalpost.registry import RATE_LIMIT_REASON, filing_years_url
    responses = brreg("810034882")
    responses[filing_years_url("810034882")] = (429, b"", {})
    env = research(tmp_path, responses, "810034882")
    years = [c for c in env["claims"] if c["field"] == "filing_years"]
    assert len(years) == 1 and years[0]["availability"] == "blocked"
    assert years[0]["reason"] == RATE_LIMIT_REASON
