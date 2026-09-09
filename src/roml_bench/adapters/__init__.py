"""Adapter registry."""

from __future__ import annotations

from roml_bench.adapters.pulp import PulpAdapter
from roml_bench.adapters.pyomo import PyomoAdapter
from roml_bench.adapters.pyoptinterface import (
    PyOptInterfaceAdapter,
    PyOptInterfaceScalarAdapter,
)
from roml_bench.adapters.roml_python import (
    RomlPythonBulkAdapter,
    RomlPythonCsrAdapter,
    RomlPythonScalarAdapter,
)

ADAPTERS = (
    RomlPythonBulkAdapter,
    RomlPythonScalarAdapter,
    RomlPythonCsrAdapter,
    PulpAdapter,
    PyomoAdapter,
    PyOptInterfaceAdapter,
    PyOptInterfaceScalarAdapter,
)

ADAPTER_IDS = tuple(cls.implementation_id for cls in ADAPTERS)


def get_adapter(implementation_id: str):
    for cls in ADAPTERS:
        if cls.implementation_id == implementation_id:
            return cls()
    raise ValueError(f"unknown implementation: {implementation_id}")


def supported_workloads(implementation_id: str) -> tuple[str, ...]:
    if implementation_id in (
        "roml_core_rust",
        "roml_core_rust_anon",
        "roml_core_bulk",
        "jump_julia",
        "ortools_mathopt_cpp",
    ):
        return ("sparse_rows", "bess_96")
    for cls in ADAPTERS:
        if cls.implementation_id == implementation_id:
            return getattr(cls, "supported_workloads", ("sparse_rows", "bess_96"))
    raise ValueError(f"unknown implementation: {implementation_id}")
