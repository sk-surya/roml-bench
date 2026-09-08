"""Adapter registry."""

from __future__ import annotations

from roml_bench.adapters.pulp import PulpAdapter
from roml_bench.adapters.pyomo import PyomoAdapter
from roml_bench.adapters.pyoptinterface import PyOptInterfaceAdapter
from roml_bench.adapters.roml_python import (
    RomlPythonBulkAdapter,
    RomlPythonScalarAdapter,
)

ADAPTERS = (
    RomlPythonBulkAdapter,
    RomlPythonScalarAdapter,
    PulpAdapter,
    PyomoAdapter,
    PyOptInterfaceAdapter,
)

ADAPTER_IDS = tuple(cls.implementation_id for cls in ADAPTERS)


def get_adapter(implementation_id: str):
    for cls in ADAPTERS:
        if cls.implementation_id == implementation_id:
            return cls()
    raise ValueError(f"unknown implementation: {implementation_id}")
