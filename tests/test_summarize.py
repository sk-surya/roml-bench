"""Tests for the statistical summarizer, incl. censored/missing points."""

import json

from roml_bench.summarize import summarize_run, write_summary


def _record(workload, size, implementation, populate_ms=None, status="ok", replicate=0):
    return {
        "schema_version": 1,
        "run_id": "fixture",
        "timestamp_utc": "2026-09-08T00:00:00Z",
        "benchmark_sha": "abc",
        "roml_sha": "6062398b418c4bc0c7718b2ce569da8b9e42766e",
        "implementation": implementation,
        "workload": workload,
        "size": size,
        "variables": 10,
        "constraints": 1,
        "constraint_nnz": 10,
        "objective_nnz": 10,
        "replicate": replicate,
        "seed": 20260908,
        "container_init_ns": 1000,
        "populate_ns": int(populate_ms * 1e6) if populate_ms is not None else 0,
        "rss_before_bytes": 1,
        "rss_after_bytes": 2,
        "peak_rss_bytes": 3,
        "cpu": None,
        "status": status,
        "error": "boom" if status != "ok" else None,
    }


def _fixture_dir(tmp_path):
    run_dir = tmp_path / "fixture-run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "fixture", "profile": "quick", "seed": 20260908,
        "benchmark_sha": "abc", "roml_sha": "x", "stopped": [],
    }))
    records = [
        _record("sparse_rows", 100, "roml_python_bulk", 10.0, replicate=0),
        _record("sparse_rows", 100, "roml_python_bulk", 12.0, replicate=1),
        _record("sparse_rows", 100, "roml_python_bulk", 14.0, replicate=2),
        _record("sparse_rows", 100, "pulp_python", 20.0, replicate=0),
        _record("sparse_rows", 100, "pulp_python", 24.0, replicate=1),
        _record("sparse_rows", 100, "pyomo_python", status="timeout", replicate=0),
        # roml_core_rust missing entirely at this point: no extrapolation.
    ]
    (run_dir / "raw.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return run_dir


def test_summary_statistics(tmp_path):
    summary = summarize_run(_fixture_dir(tmp_path))
    bulk = next(
        g for g in summary["groups"]
        if g["implementation"] == "roml_python_bulk"
    )
    assert bulk["median_ms"] == 12.0
    assert bulk["min_ms"] == 10.0
    assert bulk["max_ms"] == 14.0
    assert bulk["replicates"] == 3
    assert bulk["mad_ms"] == 2.0


def test_censored_group_preserved_without_stats(tmp_path):
    summary = summarize_run(_fixture_dir(tmp_path))
    pyomo = next(
        g for g in summary["groups"] if g["implementation"] == "pyomo_python"
    )
    assert pyomo["status"] == "timeout"
    assert "median_ms" not in pyomo
    assert pyomo["errors"] == ["boom"]


def test_no_extrapolated_speedup_for_missing_or_censored(tmp_path):
    summary = summarize_run(_fixture_dir(tmp_path))
    pairs = {(s["numerator"], s["size"]) for s in summary["speedups"]}
    assert ("pulp_python", 100) in pairs
    assert not any(n == "pyomo_python" for n, _ in pairs)
    assert not any(n == "roml_core_rust" for n, _ in pairs)
    pulp = next(s for s in summary["speedups"] if s["numerator"] == "pulp_python")
    assert pulp["speedup"] == 22.0 / 12.0
    assert pulp["denominator"] == "roml_python_bulk"


def test_write_summary_outputs_json_and_csv(tmp_path):
    run_dir = _fixture_dir(tmp_path)
    summary = write_summary(run_dir)
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "summary.csv").exists()
    text = (run_dir / "summary.csv").read_text()
    assert text.splitlines()[0].startswith("workload,size,implementation")
    assert "pyomo_python" in text
    assert len(summary["groups"]) == 3
