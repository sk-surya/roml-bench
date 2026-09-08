"""Tests for the process-isolated orchestrator."""

import json
import subprocess
import sys

import pytest

from roml_bench.orchestrator import (
    ALL_IMPLEMENTATIONS,
    censored_record,
    check_validation_gate,
    make_run_id,
    run_child,
    shuffled_order,
)
from roml_bench.schema import validate_record


def test_make_run_id_format():
    run_id = make_run_id("abcdef123456")
    assert run_id.endswith("-abcdef12")
    assert "T" in run_id and run_id.endswith("Z-abcdef12") is False
    assert make_run_id(None).endswith("-unknown")


def test_shuffled_order_deterministic_and_mixed():
    first = shuffled_order(ALL_IMPLEMENTATIONS, "sparse_rows", 1000, 0, 20260908)
    assert shuffled_order(ALL_IMPLEMENTATIONS, "sparse_rows", 1000, 0, 20260908) == first
    assert sorted(first) == sorted(ALL_IMPLEMENTATIONS)
    orders = {
        tuple(shuffled_order(ALL_IMPLEMENTATIONS, "sparse_rows", 1000, r, 20260908))
        for r in range(5)
    }
    assert len(orders) > 1


def test_censored_record_schema_valid():
    record = censored_record(
        "pulp_python", "sparse_rows", 1000, 0, "run", "sha",
        20260908, None, "timeout", "wall timeout",
    )
    assert validate_record(record) == []
    assert record["status"] == "timeout"


def test_check_validation_gate_refuses_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="absent"):
        check_validation_gate(".")


def test_worker_smoke_subprocess():
    cmd = [
        sys.executable, "-m", "roml_bench.worker",
        "--implementation", "roml_python_bulk",
        "--workload", "sparse_rows",
        "--size", "20",
        "--seed", "20260908",
        "--replicate", "0",
        "--run-id", "test",
        "--benchmark-sha", "test",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    record = json.loads(proc.stdout.strip().splitlines()[-1])
    assert validate_record(record) == []
    assert record["status"] == "ok"
    assert record["populate_ns"] > 0
    assert (record["variables"], record["constraints"]) == (20, 2)


def test_run_child_rejects_unknown_implementation():
    with pytest.raises(ValueError, match="unknown implementation"):
        run_child(
            "nope", "sparse_rows", 20, 20260908, 0, "test", "test",
            None, 30, 16 * 1024**3,
        )


def test_run_child_rust_core_smoke():
    record = run_child(
        "roml_core_rust", "sparse_rows", 20, 20260908, 0, "test", "test",
        None, 30, 16 * 1024**3,
    )
    assert record["status"] == "ok", record.get("error")
    assert validate_record(record) == []
    assert (record["variables"], record["constraints"]) == (20, 2)
