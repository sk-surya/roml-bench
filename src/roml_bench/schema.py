"""Immutable raw-result schema for model-build benchmark v1."""

from __future__ import annotations

SCHEMA_VERSION = 1

ROML_SHA = "c590692ace5446cc20c7eb91cb8fa0d594a054b0"

IMPLEMENTATIONS = (
    "roml_python_vectorized",
    "roml_python_naive_chain",
    "roml_python_csr",
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_python",
    "pyoptinterface_scalar",
    "roml_core_rust",
    "roml_core_rust_anon",
    "roml_core_bulk",
    "jump_julia",
    "ortools_mathopt_cpp",
)

# IDs produced by older benchmark code. Accepted when validating historical
# raw files, never produced by new runs. v1 `roml_python_scalar` is the same
# code path now published as `roml_python_naive_chain`; `roml_python_bulk` was
# renamed to `roml_python_vectorized` because the BESS arm is the idiomatic
# vectorized API, not an expert-only bulk escape hatch.
LEGACY_IMPLEMENTATIONS = ("roml_python_scalar", "roml_python_bulk")

KNOWN_IMPLEMENTATIONS = IMPLEMENTATIONS + LEGACY_IMPLEMENTATIONS

VARIANTS = ("canonical", "shuffled", "duplicated")

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
    if record.get("implementation") not in KNOWN_IMPLEMENTATIONS:
        problems.append(f"unknown implementation: {record.get('implementation')}")
    if record.get("variant", "canonical") not in VARIANTS:
        problems.append(f"unknown variant: {record.get('variant')}")
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
