"""Immutable raw-result schema for model-build benchmark v1."""

from __future__ import annotations

SCHEMA_VERSION = 1

ROML_SHA = "6062398b418c4bc0c7718b2ce569da8b9e42766e"

IMPLEMENTATIONS = (
    "roml_python_bulk",
    "roml_python_scalar",
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_python",
    "roml_core_rust",
)

WORKLOADS = ("sparse_rows", "bess_96")

STATUSES = ("ok", "timeout", "memory_exceeded", "error")

REQUIRED_FIELDS = (
    "schema_version",
    "run_id",
    "timestamp_utc",
    "benchmark_sha",
    "roml_sha",
    "implementation",
    "workload",
    "size",
    "variables",
    "constraints",
    "constraint_nnz",
    "objective_nnz",
    "replicate",
    "seed",
    "container_init_ns",
    "populate_ns",
    "rss_before_bytes",
    "rss_after_bytes",
    "peak_rss_bytes",
    "cpu",
    "status",
    "error",
)


def validate_record(record: dict) -> list[str]:
    """Return a list of schema violations (empty when valid)."""
    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in record:
            problems.append(f"missing field: {field}")
    if record.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    if record.get("implementation") not in IMPLEMENTATIONS:
        problems.append(f"unknown implementation: {record.get('implementation')}")
    if record.get("workload") not in WORKLOADS:
        problems.append(f"unknown workload: {record.get('workload')}")
    if record.get("status") not in STATUSES:
        problems.append(f"unknown status: {record.get('status')}")
    if record.get("roml_sha") != ROML_SHA:
        problems.append(f"roml_sha must be {ROML_SHA}")
    status = record.get("status")
    if status == "ok" and not isinstance(record.get("populate_ns"), int):
        problems.append("ok records need integer populate_ns")
    if status == "ok" and (record.get("populate_ns") or 0) <= 0:
        problems.append("ok records need populate_ns > 0")
    if status != "ok" and not record.get("error"):
        problems.append(f"{status} records need an error description")
    return problems
