"""roml-bench command line interface."""

from __future__ import annotations

import argparse
import json
import sys


def _cmd_validate(_args: argparse.Namespace) -> int:
    from roml_bench.validate import write_validation

    result = write_validation()
    print(json.dumps(
        {
            "status": result["status"],
            "benchmark_sha": result.get("benchmark_sha"),
            "roml_checkout_sha": result.get("roml_checkout_sha"),
            "problems": result.get("problems", []),
            "implementations": {
                impl: entry.get("status")
                for impl, entry in result.get("implementations", {}).items()
            },
        },
        indent=2,
    ))
    return 0 if result["status"] == "ok" else 1


def _cmd_run(args: argparse.Namespace) -> int:
    from roml_bench.orchestrator import run_profile

    try:
        run_dir = run_profile(args.profile, run_id=args.run_id)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(str(run_dir))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roml-bench")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="run the structural/equivalence validation gate")
    run_parser = sub.add_parser("run", help="run a benchmark profile")
    run_parser.add_argument("--profile", choices=["quick", "standard"], required=True)
    run_parser.add_argument("--run-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "run":
        return _cmd_run(args)
    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
