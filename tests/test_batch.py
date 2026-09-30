import json
import time

from conftest import assert_unique_claims, brreg, make_fetcher

from signalpost.cli import main
from signalpost.registry import entity_url
from signalpost.runner import BatchRun, RunConfig

REPORT_KEYS = {"input_count", "envelope_count", "expected_count", "duplicate_inputs",
               "state_counts", "runtime_ms_total", "runtime_ms_p50", "runtime_ms_p95",
               "requests_total", "requests_by_host", "bytes_fetched", "peak_memory_mb",
               "third_party_cost_usd", "time_budget_seconds", "fast_path_count", "run_id",
               "started_at", "completed_at"}


def _responses():
    out = {}
    for orgnr in ("923609016", "810034882", "921326904"):
        out.update(brreg(orgnr))
    return out


def _run(tmp_path, lines, fetcher=None, **kw):
    inp = tmp_path / "in.txt"
    inp.write_text("\n".join(lines) + "\n")
    cfg = RunConfig(input_path=str(inp), output_path=str(tmp_path / "out.jsonl"),
                    report_path=str(tmp_path / "report.json"), web=False, quiet=True, **kw)
    code = BatchRun(cfg, fetcher=fetcher or make_fetcher(_responses())[0]).run()
    envelopes = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text().splitlines()]
    for env in envelopes:
        assert_unique_claims(env)
    return code, envelopes, json.loads((tmp_path / "report.json").read_text())


def test_one_envelope_per_input_in_order(tmp_path):
    lines = ["923609016", "923609017", "908660242", "810034882", "923 609 016", "921326904"]
    code, envs, report = _run(tmp_path, lines, expected_count=6)
    assert code == 0
    assert len(envs) == 6
    assert [e["input"]["index"] for e in envs] == list(range(6))
    assert [e["status"] for e in envs] == ["available", "failed", "not_available", "available",
                                            "available", "not_available"]
    assert envs[1]["errors"][0]["code"] == "invalid_organisation_number"
    assert envs[4]["input"]["duplicate_of_index"] == 0
    assert envs[4]["claims"] == envs[0]["claims"]
    assert REPORT_KEYS <= set(report)
    assert report["input_count"] == report["envelope_count"] == 6
    assert report["duplicate_inputs"] == 1
    assert report["state_counts"]["available"] == 3
    assert report["requests_by_host"]["data.brreg.no"] > 0
    assert report["third_party_cost_usd"] == 0
    assert report["filing_years_fetched"] == 2 and report["filing_years_skipped"] == 0


def test_crash_on_one_company_becomes_failed_envelope(tmp_path):
    fetcher, transport = make_fetcher(_responses())
    original = transport.__call__

    def exploding(url, *a, **kw):
        if url.endswith("810034882/roller"):
            raise RuntimeError("boom")
        return original(url, *a, **kw)

    fetcher.transport = exploding
    code, envs, _ = _run(tmp_path, ["923609016", "810034882"], fetcher=fetcher)
    assert code == 0 and len(envs) == 2
    assert envs[0]["status"] == "available"
    assert envs[1]["status"] == "failed" and envs[1]["errors"][0]["code"] == "internal_error"


def test_resume_does_not_redo_or_duplicate(tmp_path):
    code, first, _ = _run(tmp_path, ["923609016", "810034882"], run_id="r1")
    assert code == 0
    fetcher, transport = make_fetcher(_responses())
    code, second, report = _run(tmp_path, ["923609016", "810034882"], fetcher=fetcher,
                                run_id="r1", resume=True)
    assert code == 0 and transport.requested == []
    assert [e["organisation_number"] for e in second] == ["923609016", "810034882"]
    assert second == first


def test_time_budget_still_emits_every_envelope(tmp_path):
    fetcher, transport = make_fetcher(_responses())
    original = transport.__call__

    def slow(url, *a, **kw):
        time.sleep(0.6)
        return original(url, *a, **kw)

    fetcher.transport = slow
    started = time.monotonic()
    code, envs, report = _run(tmp_path, ["923609016", "810034882", "921326904", "923609016"],
                              fetcher=fetcher, workers=1, time_budget_seconds=4)
    assert time.monotonic() - started < 6
    assert code == 0 and len(envs) == 4
    reasons = " ".join(e.get("status_reason", "") for e in envs)
    assert "time_budget_exhausted" in reasons or report["fast_path_count"] > 0


def test_cli_run_writes_output_and_report(tmp_path, monkeypatch):
    inp = tmp_path / "in.jsonl"
    inp.write_text('{"organisation_number":"923609017"}\n')
    code = main(["run", "--input", str(inp), "--output", str(tmp_path / "o.jsonl"),
                 "--report", str(tmp_path / "r.json"), "--no-web", "--quiet"])
    assert code == 0
    env = json.loads((tmp_path / "o.jsonl").read_text())
    assert env["status"] == "failed"


def test_entity_url_used_as_source(tmp_path):
    _, envs, _ = _run(tmp_path, ["810034882"])
    urls = {e["source_url"] for e in envs[0]["evidence"]}
    assert entity_url("810034882") in urls
