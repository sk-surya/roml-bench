"""Tests for the raw-result schema."""

from roml_bench.schema import ROML_SHA, validate_record


def _ok_record() -> dict:
    return {
        "schema_version": 1,
        "run_id": "20260908T000000Z-test-deadbeef",
        "timestamp_utc": "2026-09-08T00:00:00Z",
        "benchmark_sha": "deadbeef",
        "roml_sha": ROML_SHA,
        "implementation": "roml_python_bulk",
        "workload": "sparse_rows",
        "size": 1000,
        "variables": 1000,
        "constraints": 100,
        "constraint_nnz": 1000,
        "objective_nnz": 1000,
        "replicate": 0,
        "seed": 20260908,
        "container_init_ns": 100,
        "populate_ns": 200,
        "rss_before_bytes": 1,
        "rss_after_bytes": 2,
        "peak_rss_bytes": 3,
        "cpu": None,
        "status": "ok",
        "error": None,
    }


def test_valid_record_passes():
    assert validate_record(_ok_record()) == []


def test_missing_field_and_bad_enums_flagged():
    record = _ok_record()
    del record["populate_ns"]
    record["implementation"] = "nope"
    record["status"] = "nope"
    problems = validate_record(record)
    assert any("populate_ns" in p for p in problems)
    assert any("nope" in p for p in problems)


def test_censored_record_requires_error():
    record = _ok_record()
    record["status"] = "timeout"
    record["populate_ns"] = 0
    assert validate_record(record) != []
    record["error"] = "wall timeout after 120s"
    assert validate_record(record) == []


def test_wrong_roml_sha_rejected():
    record = _ok_record()
    record["roml_sha"] = "0" * 40
    assert validate_record(record) != []
