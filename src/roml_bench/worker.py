"""Single-replicate measurement child (one fresh process per record).

Invoked by the orchestrator; never by users directly. Emits exactly one
JSON object on a dedicated stdout line and exits. Process startup, imports,
and canonical data generation are outside the internal timer by
construction: the timer brackets `populate()` only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roml-bench-worker")
    parser.add_argument("--implementation", required=True)
    parser.add_argument("--workload", required=True)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--replicate", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--benchmark-sha", required=True)
    parser.add_argument("--cpu", default=None)
    return parser


def _rss_now() -> tuple[int, int]:
    """Return (rss_bytes, peak_rss_bytes) for this process."""
    import resource

    import psutil

    rss = int(psutil.Process().memory_info().rss)
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    return rss, peak


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Defensive thread limits; the orchestrator sets these first, but the
    # worker must never depend on ambient shell state for timing hygiene.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    from roml_bench.adapters import get_adapter
    from roml_bench.schema import ROML_SHA
    from roml_bench.workloads import make_case

    case = make_case(args.workload, args.size, seed=args.seed)
    record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "timestamp_utc": _utc_now(),
        "benchmark_sha": args.benchmark_sha,
        "roml_sha": ROML_SHA,
        "implementation": args.implementation,
        "workload": args.workload,
        "size": args.size,
        "variables": case.variables,
        "constraints": case.constraints,
        "constraint_nnz": case.constraint_nnz,
        "objective_nnz": case.objective_nnz,
        "replicate": args.replicate,
        "seed": args.seed,
        "container_init_ns": 0,
        "populate_ns": 0,
        "rss_before_bytes": 0,
        "rss_after_bytes": 0,
        "peak_rss_bytes": 0,
        "cpu": int(args.cpu) if args.cpu is not None else None,
        "status": "ok",
        "error": None,
    }
    try:
        adapter = get_adapter(args.implementation)
        adapter.warmup()
        start = time.perf_counter_ns()
        model = adapter.new_model(case)
        record["container_init_ns"] = time.perf_counter_ns() - start
        record["rss_before_bytes"], _ = _rss_now()
        start = time.perf_counter_ns()
        adapter.populate(model, case)
        record["populate_ns"] = time.perf_counter_ns() - start
        rss_after, peak = _rss_now()
        record["rss_after_bytes"] = rss_after
        record["peak_rss_bytes"] = peak
    except Exception as exc:  # failures are data, never silent
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
