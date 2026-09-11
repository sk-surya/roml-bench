"""Offline static site generator for the model-build benchmark."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from plotly.offline import get_plotlyjs

from roml_bench.site.charts import (
    CORE_ORDER,
    FORMULATION_ORDER,
    INGESTION_ORDER,
    LABELS,
    figure_div,
    headline_bars,
    memory_chart,
    phase_breakdown_chart,
    speedup_chart,
    time_vs_nnz,
    time_vs_size,
    variant_chart,
)
from roml_bench.workloads import make_case

TEMPLATE_DIR = Path(__file__).parent / "templates"

IMPLEMENTATION_NOTES = {
    "roml_python_vectorized": (
        "ROML Python vectorized path: Model.vars + add_linear_rows CSR "
        "(sparse_rows) or vectorized Model.add with one fused rm.dot "
        "objective call (bess_96, corrected in the forensic pass)."
    ),
    "roml_python_naive_chain": (
        "Naive scalar chain: Model.var + repeated `total = total + v`. "
        "Each `+` clones the accumulated expression and linearly scans "
        "its terms (O(n^2)); measures the naive path, not binding overhead."
    ),
    "roml_python_csr": (
        "BESS matrix ingestion: one flat Model.vars with exact per-element "
        "bounds + add_linear_rows from the shared canonical CSR; flat "
        "v[i] namespace (ingestion diagnostic, bess_96 only)."
    ),
    "roml_core_rust": (
        "Native ROML core scalar path (roml crate, release build): "
        "per-variable/per-row/per-term construction in Rust with full "
        "naming. Measures the general modeling path, not the fastest "
        "native API."
    ),
    "roml_core_bulk": (
        "Native ROML core through the documented bulk API "
        "(add_linear_rows_bulk, set_linear_objective_bulk): the matched "
        "baseline for Python-interface overhead."
    ),
    "roml_core_rust_anon": (
        "Native ROML core without any .named() calls: isolates eager "
        "name-registration cost."
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
        "PyOptInterface matrix ingestion: add_m_variables per family + "
        "add_m_linear_constraints per sense group + ExprBuilder objective, "
        "backed directly by HiGHS (see methodology)."
    ),
    "pyoptinterface_scalar": (
        "PyOptInterface formulation: scalar add_variable loop + per-row "
        "ScalarAffineFunction constraints + ExprBuilder objective, driven "
        "from B/T/prices with no shared CSR."
    ),
    "jump_julia": (
        "JuMP (Julia, pinned toolchain): idiomatic containers + HiGHS.jl. "
        "Each replicate is a fresh Julia process with an unrecorded JIT "
        "warmup outside the timer."
    ),
    "ortools_mathopt_cpp": (
        "OR-Tools MathOpt C++ (pinned source build) + HiGHS solver: "
        "idiomatic Model/AddVariable/AddLinearConstraint construction."
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
        and g.get("variant", "canonical") == "canonical"
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
        and g.get("variant", "canonical") == "canonical"
    }
    if not medians:
        return None
    ordered = sorted(medians.items(), key=lambda kv: kv[1])
    return {"size": size, "medians": dict(ordered), "fastest": ordered[0][0]}


def _largest_paired_subset(
    summary: dict, workload: str, candidates: list[str], minimum: int = 2
) -> dict | None:
    """Largest size where at least `minimum` candidates have canonical points."""
    ok = {
        (g["size"], g["implementation"])
        for g in summary["groups"]
        if g["workload"] == workload and "median_ms" in g
        and g.get("variant", "canonical") == "canonical"
    }
    sizes = sorted({
        size for size, _ in ok
        if sum((size, impl) in ok for impl in candidates) >= minimum
    })
    if not sizes:
        return None
    size = sizes[-1]
    medians = {
        g["implementation"]: g["median_ms"]
        for g in summary["groups"]
        if g["workload"] == workload and g["size"] == size
        and g["implementation"] in candidates and "median_ms" in g
        and g.get("variant", "canonical") == "canonical"
    }
    ordered = sorted(medians.items(), key=lambda kv: kv[1])
    return {"size": size, "medians": dict(ordered), "fastest": ordered[0][0]}


def _finding_text(summary: dict, run_meta: dict) -> list[str]:
    findings = []
    for workload in ("sparse_rows", "bess_96"):
        paired = _largest_paired(summary, workload, FORMULATION_ORDER)
        if paired is None:
            findings.append(
                f"{workload} formulation: no size was completed by all "
                "formulation arms; curves below stop where each arm stopped."
            )
        else:
            size = paired["size"]
            meds = paired["medians"]
            base = meds.get("roml_python_vectorized")
            parts = []
            for impl in FORMULATION_ORDER:
                if impl in meds and impl != "roml_python_vectorized" and base:
                    parts.append(f"{LABELS[impl]} {meds[impl] / base:.2f}x vs ROML vectorized")
            fastest = LABELS[paired["fastest"]]
            findings.append(
                f"{workload} formulation at paired size {size}: fastest was "
                f"{fastest} (median {meds[paired['fastest']]:.3g} ms); "
                + "; ".join(parts)
                + "."
            )
        ingested = _largest_paired_subset(summary, workload, INGESTION_ORDER)
        if ingested is not None:
            meds = ingested["medians"]
            order = ", ".join(
                f"{LABELS[i]} {meds[i]:.3g} ms" for i in INGESTION_ORDER if i in meds
            )
            findings.append(
                f"{workload} matrix ingestion at paired size {ingested['size']}: {order}."
            )
    core_sparse = _largest_paired(summary, "sparse_rows", CORE_ORDER)
    if core_sparse is not None:
        meds = core_sparse["medians"]
        named = meds.get("roml_core_rust")
        anon = meds.get("roml_core_rust_anon")
        extra = ""
        if named and anon:
            extra = f" Named vs anonymous core: {named / anon:.2f}x."
        findings.append(
            f"ROML core named vs anonymous at sparse_rows {core_sparse['size']}:"
            + extra
            + " (median ratios, paired points only)."
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

    python_impls = [i for i in FORMULATION_ORDER if _has_points(summary, i)]
    ingest_impls = [i for i in INGESTION_ORDER if _has_points(summary, i)]
    core_impls = [i for i in CORE_ORDER if _has_points(summary, i)]
    panel = FORMULATION_ORDER + ["roml_python_csr", "pyoptinterface_python"]
    all_impls = [i for i in panel if _has_points(summary, i)]
    retraction = (
        "Correction to the v1 report: the 350x figure was naive O(n^2) "
        "expression chaining, not Python binding overhead, and the v1 BESS "
        "leaderboard mixed matrix ingestion (PyOptInterface) against "
        "high-level formulation (ROML). This report splits formulation "
        "from ingestion and renames the scalar arm accordingly."
    )

    ctx_common = {
        "provenance": provenance,
        "findings": findings,
        "retraction": retraction,
        "labels": LABELS,
        "impl_notes": IMPLEMENTATION_NOTES,
    }
    pages = {
        "index": {
            "charts": [
                ("Formulation time vs size (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", python_impls,
                                         "Formulation: sparse_rows"))),
                ("Formulation time vs size (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", python_impls,
                                         "Formulation: bess_96"))),
                ("Matrix ingestion time vs size (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", ingest_impls,
                                         "Ingestion: sparse_rows"))),
                ("ROML Python vs native core (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", core_impls,
                                         "ROML core paths: sparse_rows"))),
            ],
        },
        "python": {
            "charts": [
                ("Headline: sparse_rows 1M, median ms (linear)",
                 figure_div(headline_bars(
                     summary, "sparse_rows", 1000000,
                     python_impls + [i for i in core_impls if i not in python_impls],
                     "Headline sparse_rows 1M"))),
                ("Headline: bess_96 B=300, median ms (linear)",
                 figure_div(headline_bars(
                     summary, "bess_96", 300,
                     python_impls + [i for i in core_impls if i not in python_impls],
                     "Headline bess_96 B=300"))),
                ("A. Formulation time vs size (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", python_impls,
                                         "sparse_rows formulation: populate time vs N"))),
                ("A. Formulation time vs size (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", python_impls,
                                         "bess_96 formulation: populate time vs batteries"))),
                ("A. Formulation time vs model nonzeros (sparse_rows)",
                 figure_div(time_vs_nnz(summary, "sparse_rows", python_impls,
                                        nnz["sparse_rows"],
                                        "sparse_rows formulation: time vs nonzeros"))),
                ("A. Formulation time vs model nonzeros (bess_96)",
                 figure_div(time_vs_nnz(summary, "bess_96", python_impls,
                                        nnz["bess_96"],
                                        "bess_96 formulation: time vs nonzeros"))),
                ("B. Matrix ingestion time vs size (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", ingest_impls,
                                         "sparse_rows ingestion: shared CSR input"))),
                ("B. Matrix ingestion time vs size (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", ingest_impls,
                                         "bess_96 ingestion: shared CSR input"))),
                ("Speedup vs ROML Python vectorized, formulation (paired sizes only)",
                 figure_div(speedup_chart(
                     summary, "formulation",
                     "Speedup vs ROML Python vectorized (formulation)",
                     "competitor median / ROML-bulk median; paired points only"))),
                ("Speedup vs ROML Python vectorized, ingestion (paired sizes only)",
                 figure_div(speedup_chart(
                     summary, "ingestion",
                     "Speedup vs ROML Python vectorized (ingestion)",
                     "median ratio on shared CSR input; paired points only"))),
                ("Phase decomposition (sparse_rows, 100k)",
                 figure_div(phase_breakdown_chart(
                     summary, "sparse_rows", 100000, python_impls + ingest_impls,
                     "Phase medians at sparse_rows 100k"))),
                ("Phase decomposition (sparse_rows, 1M)",
                 figure_div(phase_breakdown_chart(
                     summary, "sparse_rows", 1000000, python_impls + ingest_impls,
                     "Phase medians at sparse_rows 1M"))),
                ("Phase decomposition (bess_96, B=100)",
                 figure_div(phase_breakdown_chart(
                     summary, "bess_96", 100, python_impls + ingest_impls,
                     "Phase medians at bess_96 B=100"))),
                ("Phase decomposition (bess_96, B=300)",
                 figure_div(phase_breakdown_chart(
                     summary, "bess_96", 300, python_impls + ingest_impls,
                     "Phase medians at bess_96 B=300"))),
                ("CSR ingestion diagnostics (sparse_rows, 100k)",
                 figure_div(variant_chart(
                     summary, "sparse_rows", 100000,
                     ["roml_python_vectorized", "pyoptinterface_python"],
                     "Canonical vs shuffled vs duplicated CSR at 100k"))),
                ("CSR ingestion diagnostics (sparse_rows, 1M)",
                 figure_div(variant_chart(
                     summary, "sparse_rows", 1000000,
                     ["roml_python_vectorized", "pyoptinterface_python"],
                     "Canonical vs shuffled vs duplicated CSR at 1M"))),
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
                ("ROML naive chain vs bulk vs native core (sparse_rows)",
                 figure_div(time_vs_size(summary, "sparse_rows", core_impls,
                                         "ROML overhead: sparse_rows"))),
                ("ROML naive chain vs bulk vs native core (bess_96)",
                 figure_div(time_vs_size(summary, "bess_96", core_impls,
                                         "ROML core paths: bess_96"))),
                ("Overhead vs matched native bulk core (paired sizes only)",
                 figure_div(speedup_chart(
                     summary, "roml-core",
                     "Python overhead vs native bulk ROML core",
                     "naive-chain-vs-bulk-core shows expression-chaining cost, not "
                     "binding overhead; python-bulk-vs-bulk-core is the interface "
                     "overhead; scalar-core-vs-bulk-core shows the general-path "
                     "cost; named-vs-anon isolates name registration"))),
                ("Core phase decomposition (sparse_rows, 1M)",
                 figure_div(phase_breakdown_chart(
                     summary, "sparse_rows", 1000000, core_impls,
                     "Core phase medians at sparse_rows 1M"))),
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
