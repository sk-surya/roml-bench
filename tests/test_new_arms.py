"""Tests for the JuMP (Julia) and MathOpt (C++) benchmark arms."""

import pytest

from roml_bench.adapters import supported_workloads
from roml_bench.orchestrator import run_child
from roml_bench.schema import validate_record

JULIA = "jump_julia"
CPP = "ortools_mathopt_cpp"


def test_supported_workloads_both():
    assert supported_workloads(JULIA) == ("sparse_rows", "bess_96")
    assert supported_workloads(CPP) == ("sparse_rows", "bess_96")


def test_run_child_rejects_unknown_still():
    with pytest.raises(ValueError, match="unknown implementation"):
        run_child(
            "nope", "sparse_rows", 20, 20260908, 0, "test", "test",
            None, 30, 16 * 1024**3,
        )


def _assert_record_shape(record, workload, size, impl):
    assert validate_record(record) == []
    assert record["status"] == "ok", record.get("error")
    assert record["implementation"] == impl
    assert record["populate_ns"] > 0
    assert record["phases"]["variables"] > 0
    assert record["phases"]["constraints"] > 0
    assert record["phases"]["objective"] > 0


@pytest.mark.external
def test_jump_sparse_record():
    record = run_child(
        JULIA, "sparse_rows", 200, 20260908, 0, "test", "test",
        None, 60, 16 * 1024**3,
    )
    _assert_record_shape(record, "sparse_rows", 200, JULIA)
    assert (record["variables"], record["constraints"]) == (200, 20)
    assert record["constraint_nnz"] == 200
    assert record["objective_nnz"] == 200


@pytest.mark.external
def test_cpp_sparse_record():
    record = run_child(
        CPP, "sparse_rows", 200, 20260908, 0, "test", "test",
        None, 60, 16 * 1024**3,
    )
    _assert_record_shape(record, "sparse_rows", 200, CPP)
    assert (record["variables"], record["constraints"]) == (200, 20)


@pytest.mark.external
def test_jump_bess_record_and_counts():
    record = run_child(
        JULIA, "bess_96", 2, 20260908, 0, "test", "test",
        None, 60, 16 * 1024**3,
    )
    _assert_record_shape(record, "bess_96", 2, JULIA)
    assert record["variables"] == 2 * (3 * 96 + 1)
    assert record["constraints"] == 2 * (2 * 96 + 1)


@pytest.mark.external
def test_cpp_bess_record_and_counts():
    record = run_child(
        CPP, "bess_96", 2, 20260908, 0, "test", "test",
        None, 60, 16 * 1024**3,
    )
    _assert_record_shape(record, "bess_96", 2, CPP)
    assert record["variables"] == 2 * (3 * 96 + 1)
    assert record["constraints"] == 2 * (2 * 96 + 1)
