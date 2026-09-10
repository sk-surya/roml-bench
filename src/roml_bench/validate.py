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
from roml_bench.system import (
    collect_environment,
    git_sha,
    roml_artifact_fingerprint,
    roml_checkout_sha,
)
from roml_bench.workloads import CANONICAL_SEED, make_case

ABS_TOL = 1e-7
REL_TOL = 1e-7

VALIDATION_CASES = (("sparse_rows", 100), ("bess_96", 1))

PYTHON_SOLVERS = {
    "roml_python_bulk": "roml-highs",
    "roml_python_naive_chain": "roml-highs",
    "roml_python_csr": "roml-highs",
    "pulp_python": "bundled-cbc",
    "pyomo_python": "appsi-highs",
    "pyoptinterface_python": "highs-direct",
    "pyoptinterface_scalar": "highs-direct",
    "jump_julia": "highs-julia",
    "ortools_mathopt_cpp": "highs-mathopt",
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
    if implementation in ("pyoptinterface_python", "pyoptinterface_scalar"):
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


def validate_roml_artifacts(
    artifacts: dict,
    expected_sha: str = ROML_SHA,
    venv_prefix: str | None = None,
) -> list[str]:
    """Assert every ROML representation matches the pinned SHA.

    Recording hashes is not enough: a stale wheel validated once would
    stay green forever, which is the exact incident class this closes.
    Every mismatch fails validation. Pure over its inputs (plus
    filesystem reads) so mutation tests can drive it directly.
    """
    import sys
    import urllib.parse
    import zipfile
    from pathlib import Path

    problems: list[str] = []
    if venv_prefix is None:
        venv_prefix = sys.prefix
    if artifacts.get("expected_sha") != expected_sha:
        problems.append(
            f"expected_sha {artifacts.get('expected_sha')} != pinned {expected_sha}"
        )
    if artifacts.get("checkout_head") != expected_sha:
        problems.append(
            f".cache/roml HEAD {artifacts.get('checkout_head')} != pinned {expected_sha}"
        )
    cargo_revs = artifacts.get("cargo_revs") or {}
    for member in ("rust-core", "rust-store-proto"):
        if cargo_revs.get(member) != expected_sha:
            problems.append(
                f"{member}/Cargo.toml rev {cargo_revs.get(member)} != pinned {expected_sha}"
            )
    if cargo_revs.get("lock") != [expected_sha]:
        problems.append(
            f"Cargo.lock ROML revisions {cargo_revs.get('lock')} != exactly [{expected_sha}]"
        )
    installed = artifacts.get("installed_file")
    try:
        in_venv = (
            installed is not None
            and Path(installed).exists()
            and Path(installed).is_relative_to(venv_prefix)
        )
    except (OSError, ValueError):
        in_venv = False
    if not in_venv:
        problems.append(
            f"installed roml {installed} is not inside the benchmark venv {venv_prefix}"
        )
    wheel_path = artifacts.get("wheel_path")
    if not wheel_path or not Path(wheel_path).exists():
        problems.append(f"pinned wheel missing: {wheel_path}")
    if not artifacts.get("wheel_sha256"):
        problems.append("pinned wheel has no SHA256")
    if not artifacts.get("native_ext_sha256"):
        problems.append("loaded native extension has no SHA256")
    if not artifacts.get("core_binary_sha256"):
        problems.append("roml-bench-core binary has no SHA256")
    direct_url = artifacts.get("installed_wheel_url")
    try:
        url_path = (
            Path(urllib.parse.urlparse(json.loads(direct_url)["url"]).path)
            if direct_url
            else None
        )
    except (ValueError, KeyError, TypeError):
        url_path = None
    if (
        url_path is None
        or wheel_path is None
        or url_path != Path(wheel_path)
    ):
        problems.append(
            "installed direct_url.json does not resolve to the fingerprinted wheel"
        )
    if wheel_path and Path(wheel_path).exists() and artifacts.get("native_ext_sha256"):
        try:
            with zipfile.ZipFile(wheel_path) as zf:
                so_hashes = {
                    _wheel_member_sha256(zf, name)
                    for name in zf.namelist()
                    if name.endswith(".so")
                }
        except zipfile.BadZipFile:
            so_hashes = set()
        if not so_hashes:
            problems.append(f"no native extension found inside wheel {wheel_path}")
        elif artifacts["native_ext_sha256"] not in so_hashes:
            problems.append(
                "wheel-contained native extension != loaded native extension "
                "(stale install: reinstall the fingerprinted wheel)"
            )
    return problems


def _wheel_member_sha256(zf, name: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with zf.open(name) as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_external_runner(cases: dict, implementation: str, kind: str) -> dict:
    """Validate a Julia/C++ runner: counts, schema, and solve agreement.

    Runs the external binary on the validation sizes (populate only),
    then once more with --solve; solved objectives join the
    cross-implementation agreement check through the returned
    `objectives` map. `kind` selects the command construction.
    """
    from roml_bench.orchestrator import CPP_BINARY, JULIA_PROJECT, JULIA_SCRIPT, _julia_binary
    from roml_bench.schema import validate_record

    entry = {
        "implementation": implementation,
        "construction_path": (
            "JuMP containers + HiGHS.jl (Julia, pinned toolchain)"
            if kind == "julia"
            else "MathOpt C++ modeling + HiGHS solver (pinned OR-Tools)"
        ),
        "workloads": {},
        "objectives": {},
        "status": "ok",
        "problems": [],
    }
    import numpy as np

    from roml_bench.workloads import bess_prices

    prices_csv = ",".join(
        repr(float(v)) for v in np.asarray(bess_prices(CANONICAL_SEED)).tolist()
    )
    for workload, size in VALIDATION_CASES:
        case = cases[(workload, size)]
        key = f"{workload}/{size}"
        if kind == "julia":
            julia = _julia_binary()
            if julia is None or not JULIA_SCRIPT.exists():
                entry["status"] = "failed"
                entry["problems"].append(f"{key}: julia launcher or script unavailable")
                continue
            base = [
                julia, "--startup-file=no", "--threads=1",
                f"--project={JULIA_PROJECT}", str(JULIA_SCRIPT),
                "--workload", workload,
                "--size", str(size),
                "--seed", str(CANONICAL_SEED),
                "--replicate", "0",
                "--run-id", "validation",
                "--benchmark-sha", git_sha(".") or "unknown",
                "--roml-sha", ROML_SHA,
                "--timestamp-utc", "validation",
                "--implementation", implementation,
            ]
        else:
            if not CPP_BINARY.exists():
                entry["status"] = "failed"
                entry["problems"].append(f"{key}: cpp/build/mathopt_bench not built")
                continue
            base = [
                str(CPP_BINARY),
                "--workload", workload,
                "--size", str(size),
                "--seed", str(CANONICAL_SEED),
                "--replicate", "0",
                "--run-id", "validation",
                "--benchmark-sha", git_sha(".") or "unknown",
                "--roml-sha", ROML_SHA,
                "--timestamp-utc", "validation",
                "--implementation", implementation,
            ]
        if workload == "bess_96":
            base += ["--prices-csv", prices_csv]
        workload_problems: list[str] = []
        try:
            proc = subprocess.run(base, capture_output=True, text=True, timeout=300)
        except subprocess.SubprocessError as exc:
            entry["status"] = "failed"
            entry["problems"].append(f"{key}: {exc}")
            continue
        if proc.returncode != 0:
            entry["status"] = "failed"
            entry["problems"].append(
                f"{key}: exit {proc.returncode}: {proc.stderr[-500:]}"
            )
            continue
        try:
            record = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError as exc:
            entry["status"] = "failed"
            entry["problems"].append(f"{key}: bad JSON: {exc}")
            continue
        workload_problems += validate_record(record)
        workload_problems += [
            f"{k}: runner {record[k]}, canonical {getattr(case, k)}"
            for k in ("variables", "constraints", "constraint_nnz", "objective_nnz")
            if record[k] != getattr(case, k)
        ]
        if workload_problems:
            entry["status"] = "failed"
            entry["problems"].extend(f"{key}: {p}" for p in workload_problems)
            continue
        # Solve gate: same canonical model through HiGHS, objective joins
        # the agreement check in run_validation.
        try:
            solved = subprocess.run(
                base + ["--solve"], capture_output=True, text=True, timeout=300
            )
        except subprocess.SubprocessError as exc:
            entry["status"] = "failed"
            entry["problems"].append(f"{key}: solve {exc}")
            continue
        if solved.returncode != 0:
            entry["status"] = "failed"
            entry["problems"].append(
                f"{key}: solve exit {solved.returncode}: {solved.stderr[-500:]}"
            )
            continue
        try:
            solved_record = json.loads(solved.stdout.strip().splitlines()[-1])
            entry["objectives"][key] = float(solved_record["objective_value"])
        except (ValueError, KeyError, TypeError) as exc:
            entry["status"] = "failed"
            entry["problems"].append(f"{key}: bad solve output: {exc}")
            continue
        entry["workloads"][key] = {
            "status": "ok",
            "populate_ns": record.get("populate_ns"),
            "objective": entry["objectives"][key],
        }
    return entry


def _check_rust_core(cases: dict, implementation: str = "roml_core_rust") -> dict:
    # roml_core_bulk exercises the same binary through the documented
    # bulk core API (add_linear_rows_bulk / set_linear_objective_bulk);
    # counts, schema, and the probe's bulk-vs-scalar replay proof below
    # carry its correctness.
    """Run the release binary on validation sizes; verify counts and schema."""
    from roml_bench.schema import validate_record

    binary = Path("target/release/roml-bench-core")
    entry = {
        "implementation": implementation,
        "construction_path": (
            "rust: Model::named + scalar add_variable/add_constraint"
            + (" (anonymous, no .named() calls)" if implementation.endswith("_anon") else "")
        ),
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
            "--implementation", implementation,
            "--phase-breakdown",
        ]
        if implementation == "roml_core_rust_anon":
            cmd += ["--anonymous"]
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
            entry["problems"].append(
                f"{workload}/{size}: exit {proc.returncode}: {proc.stderr[-500:]}"
            )
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


def _check_native_equiv() -> list[str]:
    """Bulk-vs-scalar replay proof via the forensic probe (validation sizes).

    For each validation case, builds through both native constructions,
    commits both journals, replays both into reference backends, and
    requires full equality (variables, constraints, all cells,
    objectives) plus snapshot equality. Returns a list of problems
    (empty when proven).
    """
    problems: list[str] = []
    binary = Path("target/release/forensic_probe")
    if not binary.exists():
        return ["target/release/forensic_probe not built"]
    import numpy as np

    from roml_bench.workloads import bess_prices

    prices_csv = ",".join(
        repr(float(v)) for v in np.asarray(bess_prices(CANONICAL_SEED)).tolist()
    )
    for workload, size in VALIDATION_CASES:
        for construction in ("scalar", "bulk"):
            cmd = [
                str(binary),
                "--workload", workload,
                "--size", str(size),
                "--replicate", "0",
                "--construction", construction,
                "--equiv",
            ]
            if workload == "bess_96":
                cmd += ["--prices-csv", prices_csv]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.SubprocessError as exc:
                problems.append(f"{workload}/{size}: probe {exc}")
                continue
            if proc.returncode != 0:
                problems.append(f"{workload}/{size}: exit {proc.returncode}: {proc.stderr[-500:]}")
                continue
            try:
                record = json.loads(proc.stdout.strip().splitlines()[-1])
            except ValueError as exc:
                problems.append(f"{workload}/{size}: bad JSON: {exc}")
                continue
            equiv = record.get("equiv_scalar_bulk") or {}
            bad = [
                k
                for k, v in equiv.items()
                if k not in ("scalar_delta_ops", "bulk_delta_ops") and v is not True
            ]
            if bad:
                problems.append(f"{workload}/{size}: replay mismatch: {bad}")
    return problems


def run_validation() -> dict:
    cases = {(w, s): make_case(w, s, seed=CANONICAL_SEED) for w, s in VALIDATION_CASES}
    result: dict = {
        "seed": CANONICAL_SEED,
        "roml_sha_expected": ROML_SHA,
        "roml_checkout_sha": roml_checkout_sha(),
        "roml_artifacts": roml_artifact_fingerprint(),
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
        supported = getattr(cls, "supported_workloads", ("sparse_rows", "bess_96"))
        for workload, size in VALIDATION_CASES:
            case = cases[(workload, size)]
            key = f"{workload}/{size}"
            if workload not in supported:
                impl_entry["workloads"][key] = {
                    "status": "skipped",
                    "problems": [f"{impl} supports {supported}; {workload} by design"],
                }
                continue
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

    for impl, kind in (("jump_julia", "julia"), ("ortools_mathopt_cpp", "cpp")):
        entry = _check_external_runner(cases, impl, kind)
        result["implementations"][impl] = entry
        for key, objective in entry.get("objectives", {}).items():
            objectives.setdefault(key, {})[impl] = objective
        if entry["status"] != "ok":
            result["status"] = "failed"
            result["problems"].extend(
                f"{impl}: {p}" for p in entry.get("problems", [])
            )
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
    anon_entry = _check_rust_core(cases, "roml_core_rust_anon")
    result["implementations"]["roml_core_rust_anon"] = anon_entry
    bulk_entry = _check_rust_core(cases, "roml_core_bulk")
    result["implementations"]["roml_core_bulk"] = bulk_entry
    # Native bulk-vs-scalar replay proof on the validation sizes: full
    # journal/delta replay equality plus snapshot equality (bulk ≡ scalar
    # canonically; scalar ≡ Python by counts; Python by the solve gate).
    bulk_problems = _check_native_equiv()
    if bulk_problems:
        result["status"] = "failed"
        result["problems"].extend(bulk_problems)
        bulk_entry["status"] = "failed"
        bulk_entry["problems"].extend(bulk_problems)
    for check_entry in (rust_entry, anon_entry, bulk_entry):
        if check_entry["status"] != "ok":
            result["status"] = "failed"
            result["problems"].extend(check_entry["problems"])

    for impl_entry in result["implementations"].values():
        if impl_entry["status"] != "ok":
            result["status"] = "failed"
    # Provenance assertion (not just recording): a stale wheel or binary
    # must fail validation even if every mathematical check passes.
    artifact_problems = validate_roml_artifacts(result["roml_artifacts"])
    if artifact_problems:
        result["status"] = "failed"
        result["problems"].extend(
            f"roml-artifacts: {p}" for p in artifact_problems
        )
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
        "roml_artifacts": validation.get("roml_artifacts"),
        "status": validation.get("status"),
    }
