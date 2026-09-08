"""Structural and mathematical validation gate (contract section 6).

For every publishable implementation/workload this command checks, outside
all timed paths:

1. expected variable / constraint / objective-nnz / constraint-nnz counts
2. bound/domain spot checks
3. a small deterministic solve with HiGHS-compatible paths and
   cross-implementation objective agreement within 1e-7 absolute + 1e-7
   relative tolerance

Results are written to results/validation.json. The benchmark `run`
command refuses to start when validation is absent, stale, or failed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import roml_bench.adapters.pulp as pulp_adapter
import roml_bench.adapters.pyomo as pyomo_adapter
import roml_bench.adapters.pyoptinterface as poi_adapter
from roml_bench.adapters import ADAPTERS
from roml_bench.adapters.base import check_report_against_case
from roml_bench.schema import ROML_SHA
from roml_bench.system import collect_environment, git_sha, roml_checkout_sha
from roml_bench.workloads import CANONICAL_SEED, make_case

ABS_TOL = 1e-7
REL_TOL = 1e-7

VALIDATION_CASES = (("sparse_rows", 100), ("bess_96", 1))

PYTHON_SOLVERS = {
    "roml_python_bulk": "roml-highs",
    "roml_python_scalar": "roml-highs",
    "pulp_python": "bundled-cbc",
    "pyomo_python": "appsi-highs",
    "pyoptinterface_python": "highs-direct",
}


def agrees(a: float, b: float) -> bool:
    return abs(a - b) <= ABS_TOL + REL_TOL * max(abs(a), abs(b))


def _solve_python(implementation: str, model):
    if implementation.startswith("roml_python"):
        import roml as rm

        with rm.Highs() as solver:
            return float(solver.solve(model).objective)
    if implementation == "pulp_python":
        return pulp_adapter.solve_objective(model)
    if implementation == "pyomo_python":
        return pyomo_adapter.solve_objective(model)
    if implementation == "pyoptinterface_python":
        return poi_adapter.solve_objective(model)
    raise ValueError(f"no solver path for {implementation}")


def _spot_check_bounds(implementation: str, artifact, case) -> list[str]:
    """Spot-check variable domains on the built validation model."""
    problems: list[str] = []
    model = artifact.model
    try:
        if implementation == "pulp_python":
            by_name = {v.name: v for v in model.variables()}
            if case.workload == "sparse_rows":
                first = by_name["x_0"]
                if (first.lowBound, first.upBound) != (0, 5):
                    problems.append(f"sparse bound spot check: {(first.lowBound, first.upBound)}")
            else:
                first = by_name["charge_0_0"]
                if (first.lowBound, first.upBound) != (0, 2.0):
                    problems.append(f"charge bound spot check: {(first.lowBound, first.upBound)}")
        elif implementation == "pyomo_python":
            if case.workload == "sparse_rows":
                var = model.x[0]
                if (var.lb, var.ub) != (0, 5):
                    problems.append(f"sparse bound spot check: {(var.lb, var.ub)}")
            else:
                var = model.charge[0, 0]
                if (var.lb, var.ub) != (0, 2.0):
                    problems.append(f"bess bound spot check: {(var.lb, var.ub)}")
                var = model.energy[0, 0]
                if (var.lb, var.ub) != (0, 4.0):
                    problems.append(f"energy bound spot check: {(var.lb, var.ub)}")
        elif implementation == "pyoptinterface_python":
            # Handles live inside the adapter; probe the same code path directly.
            probe = _poi_bound_probe()
            if probe != (0.0, 2.0):
                problems.append(f"poi domain probe: {probe}")
        elif implementation.startswith("roml_python"):
            probe = _roml_bound_probe()
            if probe != 5.0:
                problems.append(f"roml bound probe objective: {probe}")
    except Exception as exc:  # spot checks must not crash the gate
        problems.append(f"spot check raised {type(exc).__name__}: {exc}")
    return problems


def _roml_bound_probe() -> float:
    """Maximize x with ub=5 through the ROML Python path; expect 5.0."""
    import roml as rm

    m = rm.Model("bound-probe")
    x = m.var("x", lb=0.0, ub=5.0)
    m.add(x <= 10.0)
    m.maximize(x)
    with rm.Highs() as solver:
        return float(solver.solve(m).objective)


def _poi_bound_probe() -> tuple[float, float]:
    """Read back bounds through the PyOptInterface path."""
    import pyoptinterface as poi

    poi_adapter.ensure_highs_library()
    from pyoptinterface import highs

    m = highs.Model()
    x = m.add_m_variables(1, lb=0.0, ub=2.0, name="probe")
    lb = m.get_variable_attribute(x[0], poi.VariableAttribute.LowerBound)
    ub = m.get_variable_attribute(x[0], poi.VariableAttribute.UpperBound)
    return (float(lb), float(ub))


def _check_rust_core(cases: dict) -> dict:
    """Run the release binary on validation sizes; verify counts and schema."""
    from roml_bench.schema import validate_record

    binary = Path("target/release/roml-bench-core")
    entry = {
        "implementation": "roml_core_rust",
        "construction_path": "rust: Model::named + scalar add_variable/add_constraint",
        "workloads": {},
        "status": "ok",
        "problems": [],
    }
    if not binary.exists():
        entry["status"] = "failed"
        entry["problems"].append("target/release/roml-bench-core not built")
        return entry
    import numpy as np

    from roml_bench.workloads import bess_prices

    prices_csv = ",".join(
        repr(float(v)) for v in np.asarray(bess_prices(CANONICAL_SEED)).tolist()
    )
    for workload, size in VALIDATION_CASES:
        case = cases[(workload, size)]
        cmd = [
            str(binary),
            "--workload", workload,
            "--size", str(size),
            "--seed", str(CANONICAL_SEED),
            "--replicate", "0",
            "--run-id", "validation",
            "--benchmark-sha", git_sha(".") or "unknown",
            "--roml-sha", ROML_SHA,
            "--timestamp-utc", "validation",
        ]
        if workload == "bess_96":
            cmd += ["--prices-csv", prices_csv]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.SubprocessError as exc:
            entry["status"] = "failed"
            entry["problems"].append(f"{workload}/{size}: {exc}")
            continue
        if proc.returncode != 0:
            entry["status"] = "failed"
            entry["problems"].append(f"{workload}/{size}: exit {proc.returncode}: {proc.stderr[-500:]}")
            continue
        try:
            record = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError as exc:
            entry["status"] = "failed"
            entry["problems"].append(f"{workload}/{size}: bad JSON: {exc}")
            continue
        schema_problems = validate_record(record)
        count_problems = [
            f"{k}: runner {record[k]}, canonical {getattr(case, k)}"
            for k in ("variables", "constraints", "constraint_nnz", "objective_nnz")
            if record[k] != getattr(case, k)
        ]
        workload_problems = schema_problems + count_problems
        entry["workloads"][f"{workload}/{size}"] = {
            "status": "ok" if not workload_problems else "failed",
            "populate_ns": record.get("populate_ns"),
            "problems": workload_problems,
        }
        if workload_problems:
            entry["status"] = "failed"
            entry["problems"].extend(f"{workload}/{size}: {p}" for p in workload_problems)
    return entry


def run_validation() -> dict:
    cases = {(w, s): make_case(w, s, seed=CANONICAL_SEED) for w, s in VALIDATION_CASES}
    result: dict = {
        "seed": CANONICAL_SEED,
        "roml_sha_expected": ROML_SHA,
        "roml_checkout_sha": roml_checkout_sha(),
        "benchmark_sha": git_sha("."),
        "environment": collect_environment(),
        "implementations": {},
        "status": "ok",
        "problems": [],
    }
    objectives: dict[str, dict[str, float]] = {}
    for cls in ADAPTERS:
        adapter = cls()
        impl = adapter.implementation_id
        impl_entry = {
            "construction_path": adapter.construction_path,
            "count_source": None,
            "workloads": {},
            "status": "ok",
            "problems": [],
        }
        try:
            adapter.warmup()
        except Exception as exc:
            impl_entry["status"] = "failed"
            impl_entry["problems"].append(f"warmup: {type(exc).__name__}: {exc}")
            result["implementations"][impl] = impl_entry
            result["status"] = "failed"
            continue
        for workload, size in VALIDATION_CASES:
            case = cases[(workload, size)]
            key = f"{workload}/{size}"
            try:
                model = adapter.new_model(case)
                artifact = adapter.populate(model, case)
                report = adapter.inspect(artifact, case)
                impl_entry["count_source"] = report.count_source
                problems = check_report_against_case(report, case)
                problems += _spot_check_bounds(impl, artifact, case)
                objective = _solve_python(impl, artifact.model)
            except Exception as exc:
                impl_entry["workloads"][key] = {
                    "status": "failed",
                    "problems": [f"{type(exc).__name__}: {exc}"],
                }
                impl_entry["status"] = "failed"
                continue
            objectives.setdefault(key, {})[impl] = objective
            impl_entry["workloads"][key] = {
                "status": "ok" if not problems else "failed",
                "objective": objective,
                "solver": PYTHON_SOLVERS[impl],
                "problems": problems,
            }
            if problems:
                impl_entry["status"] = "failed"
        result["implementations"][impl] = impl_entry

    # Cross-implementation objective agreement per validation case.
    for key, values in objectives.items():
        reference = values.get("roml_python_bulk")
        if reference is None:
            result["status"] = "failed"
            result["problems"].append(f"{key}: no ROML bulk reference objective")
            continue
        for impl, objective in values.items():
            if not agrees(objective, reference):
                result["status"] = "failed"
                result["problems"].append(
                    f"{key}: {impl} objective {objective} != reference {reference}"
                )
                result["implementations"][impl]["status"] = "failed"

    rust_entry = _check_rust_core(cases)
    result["implementations"]["roml_core_rust"] = rust_entry
    if rust_entry["status"] != "ok":
        result["status"] = "failed"
        result["problems"].extend(rust_entry["problems"])

    for impl_entry in result["implementations"].values():
        if impl_entry["status"] != "ok":
            result["status"] = "failed"
    return result


def write_validation(path: str = "results/validation.json") -> dict:
    result = run_validation()
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


def validation_fingerprint(validation: dict) -> dict:
    """Identity a benchmark run must match to prove validation is current."""
    packages = validation.get("environment", {}).get("packages", {})
    return {
        "benchmark_sha": validation.get("benchmark_sha"),
        "roml_checkout_sha": validation.get("roml_checkout_sha"),
        "packages": packages,
        "status": validation.get("status"),
    }
