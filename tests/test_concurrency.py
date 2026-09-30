import json
import os
import subprocess
import sys
import time
from pathlib import Path

from signalpost import runner
from signalpost.runner import RunConfig
from signalpost.store import StateStoreUnavailable

TESTS = Path(__file__).parent
CHILD = TESTS / "concurrency_child.py"


def _launch(state: Path, outs: list[Path]) -> list[tuple[int, int, dict]]:
    """Start one real process per output dir, all opening `state` at the same instant."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TESTS), str(TESTS.parent)])}
    start_at = time.time() + 1.5
    procs = [subprocess.Popen([sys.executable, str(CHILD), str(state), str(out), str(start_at)],
                              env=env) for out in outs]
    results = []
    for proc, out in zip(procs, outs, strict=True):
        code = proc.wait(timeout=120)
        lines = (out / "out.jsonl").read_text().splitlines() if code == 0 else []
        report = json.loads((out / "report.json").read_text()) if code == 0 else {}
        results.append((code, len(lines), report))
    return results


def _check_trials(tmp_path: Path, processes: int, trials: int) -> None:
    for trial in range(trials):
        state = tmp_path / f"state{trial}"
        results = _launch(state, [tmp_path / f"t{trial}-p{i}" for i in range(processes)])
        assert [(code, count) for code, count, _ in results] == [(0, 3)] * processes
        (code, count, report), = _launch(state, [tmp_path / f"t{trial}-after"])
        assert (code, count) == (0, 3)
        assert report["changes_total"] == 0 and report["state_store"] == "ok"


def test_two_simultaneous_runs_on_one_state_dir(tmp_path):
    _check_trials(tmp_path, processes=2, trials=6)


def test_three_simultaneous_runs_on_one_state_dir(tmp_path):
    _check_trials(tmp_path, processes=3, trials=4)


def test_unopenable_state_store_still_emits_failed_envelopes(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise StateStoreUnavailable("state store stayed locked")

    monkeypatch.setattr(runner, "BatchRun", refuse)
    inp = tmp_path / "in.txt"
    inp.write_text("923609016\n810034882\n")
    cfg = RunConfig(input_path=str(inp), output_path=str(tmp_path / "o.jsonl"),
                    report_path=str(tmp_path / "r.json"), quiet=True)
    assert runner.run_batch(cfg) == 0
    envs = [json.loads(line) for line in (tmp_path / "o.jsonl").read_text().splitlines()]
    assert [e["status"] for e in envs] == ["failed", "failed"]
    assert envs[0]["errors"][0]["code"] == "state_store_unavailable"
    assert json.loads((tmp_path / "r.json").read_text())["envelope_count"] == 2


def test_state_dir_that_is_a_file_still_emits_every_envelope(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    inp = tmp_path / "in.txt"
    inp.write_text("923609016\n810034882\n")
    cfg = RunConfig(input_path=str(inp), output_path=str(tmp_path / "o.jsonl"),
                    report_path=str(tmp_path / "r.json"), state_dir=str(blocker), quiet=True)
    assert runner.run_batch(cfg) == 0
    envs = [json.loads(line) for line in (tmp_path / "o.jsonl").read_text().splitlines()]
    assert len(envs) == 2
    for env in envs:
        assert "state_store_unavailable" in env["sections"]["refresh_and_changes"]["reason"]
        assert env["errors"][0]["code"] == "state_store_unavailable"
    report = json.loads((tmp_path / "r.json").read_text())
    assert report["state_store"] == "unavailable" and report["envelope_count"] == 2
