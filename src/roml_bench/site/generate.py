"""Offline static site generator for the model-build benchmark."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from plotly.offline import get_plotlyjs

from roml_bench.site.charts import (
    CORE_ORDER,
    LABELS,
    PYTHON_ORDER,
    figure_div,
    memory_chart,
    speedup_chart,
    time_vs_nnz,
    time_vs_size,
)
from roml_bench.workloads import make_case

TEMPLATE_DIR = Path(__file__).parent / "templates"

IMPLEMENTATION_NOTES = {
    "roml_python_bulk": (
        "ROML Python shaped/bulk path: Model.vars + add_linear_rows CSR "
        "(sparse_rows) or vectorized Model.add (bess_96); roml.sum/roml.dot objectives."
    ),
    "roml_python_scalar": (
        "ROML Python scalar path: Model.var + scalar expressions + Model.add. "
        "Diagnostic track for binding-overhead comparison."
    ),
    "roml_core_rust": (
        "Native ROML core (roml crate, release build): scalar construction in Rust; "
        "same variables, constraints, coefficients, bounds, objective, and naming "
        "policy as roml_python_scalar."
    ),
    "pulp_python": (
        "PuLP: LpProblem.add_variable_dicts + lpSum helpers. "
        "Validation solves use the bundled CBC binary."
    ),
    "pyomo_python": (
        "Pyomo: ConcreteModel + indexed Var/Constraint rules + quicksum. "
        "Validation solves use appsi_highs."
    ),
    "pyoptinterface_python": (
        "PyOptInterface: add_m_variables per family + add_m_linear_constraints "
        "per sense group + ExprBuilder objective, backed directly by HiGHS "
        "(see methodology)."
    ),
}


def _load_run(run_dir: Path) -> dict:
    summary = json.loads((run_dir / "summary.json").read_text())
    run_meta = json.loads((run_dir / "run.json").read_text())
    environment = json.loads((run_dir / "environment.json").read_text())
    validation_path = run_dir.parent.parent / "validation.json"
    if not validation_path.exists():
        validation_path = Path("results/validation.json")
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
    return {
        "summary": summary,
        "run_meta": run_meta,
        "environment": environment,
        "validation": validation,
    }


def _nnz_map(seed: int) -> dict[str, dict[int, int]]:
    from roml_bench.workloads import sizes_for

    nnz: dict[str, dict[int, int]] = {}
    for workload in ("sparse_rows", "bess_96"):
        nnz[workload] = {}
        for size in sizes_for(workload, "standard") + sizes_for(workload, "quick"):
            case = make_case(workload, size, seed=seed)
            nnz[workload][size] = case.constraint_nnz + case.objective_nnz
    return nnz


def _largest_paired(summary: dict, workload: str, implementations: list[str]) -> dict | None:
    ok = {
        (g["size"], g["implementation"])
        for g in summary["groups"]
        if g["workload"] == workload and "median_ms" in g
    }
    sizes = sorted(
        {size for size, _ in ok if all((size, impl) in ok for impl in implementations)}
    )
    if not sizes:
        return None
    size = sizes[-1]
    medians = {
        g["implementation"]: g["median_ms"]
        for g in summary["groups"]
        if g["workload"] == workload and g["size"] == size
        and g["implementation"] in implementations and "median_ms" in g
    }
    if not medians:
        return None
    ordered = sorted(medians.items(), key=lambda kv: kv[1])
    return {"size": size, "medians": dict(ordered), "fastest": ordered[0][0]}


def _finding_text(summary: dict, run_meta: dict) -> list[str]:
    findings = []
    for workload in ("sparse_rows", "bess_96"):
        paired = _largest_paired(summary, workload, PYTHON_ORDER)
        if paired is None:
            findings.append(
                f"{workload}: no size was completed by all four Python implementations; "
                "curves below stop where each implementation stopped."
            )
            continue
        size = paired["size"]
        meds = paired["medians"]
        base = meds.get("roml_python_bulk")
        parts = []
        for impl in PYTHON_ORDER:
            if impl in meds and impl != "roml_python_bulk" and base:
                parts.append(f"{LABELS[impl]} {meds[impl] / base:.2f}x vs ROML bulk")
        fastest = LABELS[paired["fastest"]]
        findings.append(
            f"{workload} at paired size {size}: fastest Python construction was "
            f"{fastest} (median {meds[paired['fastest']]:.3g} ms); "
            + "; ".join(parts)
            + "."
        )
    core_sparse = _largest_paired(summary, "sparse_rows", CORE_ORDER)
    if core_sparse is not None:
        meds = core_sparse["medians"]
        findings.append(
            f"ROML binding overhead at sparse_rows {core_sparse['size']}: "
            f"Python scalar {meds['roml_python_scalar'] / meds['roml_core_rust']:.2f}x "
            f"vs native core; Python bulk {meds['roml_python_bulk'] / meds['roml_core_rust']:.2f}x "
            "vs native core (median ratios, paired points only)."
        )
    stopped = run_meta.get("stopped", [])
    if stopped:
        kinds = sorted({s["status"] for s in stopped})
        findings.append(
            f"Censored points are shown as gaps, never extrapolated "
            f"({len(stopped)} stop events: {', '.join(kinds)}; see Data)."
        )
    return findings


def generate_site(run_dir: str | Path, out_dir: str | Path = "site") -> Path:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    data = _load_run(run_dir)
    summary, run_meta, environment = data["summary"], data["run_meta"], data["environment"]
    seed = run_meta.get("seed", 20260908)
    nnz = _nnz_map(seed)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "static").mkdir(parents=True)
    (out_dir / "data").mkdir(parents=True)
    (out_dir / "static" / "plotly.min.js").write_text(get_plotlyjs())
    for name in ("raw.jsonl", "summary.json", "summary.csv", "run.json", "environment.json"):
        shutil.copy(run_dir / name, out_dir / "data" / name)
    validation_src = run_dir.parent.parent / "validation.json"
    if not validation_src.exists():
        validation_src = Path("results/validation.json")
    if validation_src.exists():
        shutil.copy(validation_src, out_dir / "data" / "validation.json")

    packages = environment.get("packages", {})
    provenance = {
        "run_id": summary["run_id"],
        "timestamp": environment.get("timestamp_utc"),
        "host": environment.get("platform"),
        "python": environment.get("python"),
        "cpu": environment.get("cpu_model"),
        "memory_gb": (
            round(environment["memory_total_bytes"] / 1024**3, 1)
            if environment.get("memory_total_bytes") else None
        ),
        "benchmark_sha": summary.get("benchmark_sha"),
        "roml_sha": summary.get("roml_sha"),
        "packages": packages,
        "profile": summary.get("profile"),
        "seed": summary.get("seed"),
    }
    findings = _finding_text(summary, run_meta)

    python_impls = [i for i in PYTHON_ORDER if _has_points(summary, i)]
    core_impls = [i for i in CORE_ORDER if _has_points(summary, i)]
    all_impls = [i for i in PYTHON_ORDER + ["roml_python_scalar", "roml_core_rust"] if _has_points(summary, i)]

    ctx_common = {
        "provenance": provenance,
        "findings": findings,
        "labels": LABELS,
        "impl_notes": IMPLEMENTATION_NOTES,
    }
    pages = {
        "index": {
            "charts": [
                ("Python construction time vs size (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", python_impls,
                                         "Python model construction: sparse_rows"))),
                ("Python construction time vs size (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", python_impls,
                                         "Python model construction: bess_96"))),
                ("ROML Python vs native core (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", core_impls,
                                         "ROML binding overhead: sparse_rows"))),
            ],
        },
        "python": {
            "charts": [
                ("Construction time vs size (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", python_impls,
                                         "sparse_rows: populate time vs N"))),
                ("Construction time vs size (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", python_impls,
                                         "bess_96: populate time vs batteries"))),
                ("Construction time vs model nonzeros (sparse_rows)",
                 figure_div(time_vs_nnz(summary, "sparse_rows", python_impls,
                                        nnz["sparse_rows"],
                                        "sparse_rows: populate time vs nonzeros"))),
                ("Construction time vs model nonzeros (bess_96)",
                 figure_div(time_vs_nnz(summary, "bess_96", python_impls,
                                        nnz["bess_96"],
                                        "bess_96: populate time vs nonzeros"))),
                ("Speedup vs ROML Python bulk (paired sizes only)",
                 figure_div(speedup_chart(
                     summary, "python",
                     "Speedup vs ROML Python bulk",
                     "competitor median / ROML-bulk median; paired points only"))),
                ("Child peak RSS vs size (sparse_rows, secondary metric)",
                 figure_div(memory_chart(summary, "sparse_rows", python_impls,
                                         "Memory (RSS-based, secondary): sparse_rows"))),
                ("Child peak RSS vs size (bess_96, secondary metric)",
                 figure_div(memory_chart(summary, "bess_96", python_impls,
                                         "Memory (RSS-based, secondary): bess_96"))),
            ],
        },
        "roml-core": {
            "charts": [
                ("ROML scalar vs bulk vs native core (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", core_impls,
                                         "ROML binding overhead: sparse_rows"))),
                ("ROML scalar vs bulk vs native core (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", core_impls,
                                         "ROML binding overhead: bess_96"))),
                ("Overhead vs native core (paired sizes only)",
                 figure_div(speedup_chart(
                     summary, "roml-core",
                     "Python overhead vs native ROML core",
                     "scalar-vs-scalar isolates binding overhead; "
                     "bulk-vs-core is the practical fast-path gap"))),
            ],
        },
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    groups_sorted = sorted(
        summary["groups"], key=lambda g: (g["workload"], g["size"], g["implementation"])
    )
    ctx_common["groups"] = groups_sorted
    ctx_common["speedups"] = sorted(
        summary["speedups"], key=lambda s: (s["panel"], s["workload"], s["size"], s["numerator"])
    )
    ctx_common["stopped"] = run_meta.get("stopped", [])
    ctx_common["environment"] = environment
    ctx_common["validation"] = data["validation"]
    ctx_common["all_impls"] = all_impls

    for name, extra in pages.items():
        template = env.get_template(f"{name}.html.j2")
        (out_dir / f"{name}.html").write_text(
            template.render(page=name, charts=extra["charts"], **ctx_common)
        )
    for name in ("methodology", "data"):
        template = env.get_template(f"{name}.html.j2")
        (out_dir / f"{name}.html").write_text(
            template.render(page=name, charts=[], **ctx_common)
        )
    # index.html is the landing page; keep the canonical filename.
    return out_dir


def _has_points(summary: dict, implementation: str) -> bool:
    return any(
        g["implementation"] == implementation and "median_ms" in g
        for g in summary["groups"]
    )
