"""A separate `run` process for tests/test_concurrency.py, using the saved Brreg fixtures.

Usage: python concurrency_child.py <state_dir> <out_dir> <start_at_unix_time>
"""

import sys
import time
from pathlib import Path

from conftest import brreg, make_fetcher

from signalpost.runner import BatchRun, RunConfig

ORGNRS = ["923609016", "810034882", "921326904"]


def main(state_dir: str, out_dir: str, start_at: float) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    responses = {}
    for orgnr in ORGNRS:
        responses.update(brreg(orgnr))
    inp = out / "in.txt"
    inp.write_text("\n".join(ORGNRS) + "\n")
    cfg = RunConfig(input_path=str(inp), output_path=str(out / "out.jsonl"),
                    report_path=str(out / "report.json"), state_dir=state_dir, web=False,
                    quiet=True)
    time.sleep(max(0.0, start_at - time.time()))  # all processes open the store together
    return BatchRun(cfg, fetcher=make_fetcher(responses)[0]).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], float(sys.argv[3])))
