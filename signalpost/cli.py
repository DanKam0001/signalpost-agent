"""Command line: run (batch), serve (web UI), replay (refresh demo), selfscore."""

from __future__ import annotations

import argparse
import sys


def _run(args) -> int:
    from .runner import RunConfig, run_batch

    cfg = RunConfig(
        input_path=args.input, output_path=args.output, report_path=args.report,
        state_dir=args.state_dir, run_id=args.run_id, workers=args.workers,
        time_budget_seconds=args.time_budget_seconds,
        per_company_timeout=args.per_company_timeout, resume=args.resume,
        expected_count=args.expected_count, registry_snapshot=args.registry_snapshot,
        web=not args.no_web, site_delay=args.site_delay, history_wait=args.history_wait,
        quiet=args.quiet)
    return run_batch(cfg)


def _serve(args) -> int:
    from .web.server import serve

    return serve(args.host, args.port, args.state_dir, args.batch, web=not args.no_web)


def _replay(args) -> int:
    from .replay import run_replay

    return run_replay(args.fixtures, args.output)


def _selfscore(args) -> int:
    from .selfscore import run_selfscore

    return run_selfscore(args.universe, args.count, args.seed, args.out, workers=args.workers,
                         web=not args.no_web, input_file=args.input)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signalpost",
                                     description="Registry-first company evidence agent")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="research a batch of organisation numbers")
    run.add_argument("--input", required=True, help="JSONL, JSON array or text file of numbers")
    run.add_argument("--output", required=True, help="envelopes JSONL (one line per input)")
    run.add_argument("--report", required=True, help="machine-readable run report (JSON)")
    run.add_argument("--state-dir", help="persistent state (default: <output dir>/state)")
    run.add_argument("--run-id")
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--time-budget-seconds", type=float)
    run.add_argument("--per-company-timeout", type=float, default=90.0)
    run.add_argument("--resume", action="store_true",
                     help="continue an interrupted run (same input) without redoing companies")
    run.add_argument("--expected-count", type=int)
    run.add_argument("--registry-snapshot", help="frozen Brreg bulk file for identity anchoring")
    run.add_argument("--no-web", action="store_true", help="registry sources only")
    run.add_argument("--site-delay", type=float, default=0.5,
                     help="minimum seconds between requests to one company website")
    run.add_argument("--history-wait", type=float, default=5.0,
                     help="max seconds to wait for Brreg's ~30/min filing-years endpoint; "
                          "companies beyond that get an explicit 'not fetched' claim")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=_run)

    serve = sub.add_parser("serve", help="start the web UI")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--state-dir", default="data/ui-state")
    serve.add_argument("--batch", help="envelopes JSONL to browse")
    serve.add_argument("--no-web", action="store_true")
    serve.set_defaults(func=_serve)

    replay = sub.add_parser("replay", help="deterministic refresh replay from saved snapshots")
    replay.add_argument("--fixtures", required=True)
    replay.add_argument("--output", required=True)
    replay.set_defaults(func=_replay)

    score = sub.add_parser("selfscore", help="sample the public universe, run, and score")
    score.add_argument("--universe", required=True, help="path or URL of the universe .jsonl.gz")
    score.add_argument("--count", type=int, default=100)
    score.add_argument("--seed", type=int, default=20260929)
    score.add_argument("--out", required=True)
    score.add_argument("--workers", type=int, default=8)
    score.add_argument("--input", help="use this input file instead of sampling")
    score.add_argument("--no-web", action="store_true")
    score.set_defaults(func=_selfscore)
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("Signalpost needs Python 3.11 or newer", file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
