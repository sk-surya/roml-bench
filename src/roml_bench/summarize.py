"""Deterministic summaries and paired speedups from raw JSONL only.

For every successful (workload, size, implementation) group compute median,
p25, p75, min, max, MAD, and replicate count over populate_ms. Censored or
error groups are preserved without statistics. Speedups are emitted only
for paired points completed by both implementations; never extrapolated.
"""

from __future__ import annotations

import csv
import datetime
import json
import statistics
from pathlib import Path

PYTHON_PANEL = (
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_python",
    "pyoptinterface_scalar",
)
PYTHON_BASELINE = "roml_python_bulk"
CORE_BASELINE = "roml_core_rust"
CORE_BULK_BASELINE = "roml_core_bulk"

# Formulation panel (high-level modeling from B/T/prices or N).
FORMULATION_ARMS = (
    "roml_python_bulk",
    "roml_python_naive_chain",
    "roml_python_scalar",  # legacy v1 ID, present in historical runs only
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_scalar",
    "roml_core_rust",
    "roml_core_rust_anon",
    "roml_core_bulk",
    "jump_julia",
    "ortools_mathopt_cpp",
)
# Matrix-ingestion panel (shared canonical CSR input).
INGESTION_ARMS = (
    "roml_python_bulk",
    "roml_python_csr",
    "pyoptinterface_python",
)


def _stats_ms(values_ms: list[float]) -> dict:
    ordered = sorted(values_ms)
    median = statistics.median(ordered)
    if len(ordered) >= 4:
        q1, _, q3 = statistics.quantiles(ordered, n=4)
    else:
        q1, q3 = ordered[0], ordered[-1]
    mad = statistics.median(sorted(abs(v - median) for v in ordered))
    return {
        "median_ms": median,
        "p25_ms": q1,
        "p75_ms": q3,
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "mad_ms": mad,
        "replicates": len(ordered),
    }


def summarize_run(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    run_meta = json.loads((run_dir / "run.json").read_text())
    records = [
        json.loads(line)
        for line in (run_dir / "raw.jsonl").read_text().splitlines()
        if line.strip()
    ]
    ok_groups: dict[tuple[str, int, str, str], list[dict]] = {}
    censored: dict[tuple[str, int, str, str], list[dict]] = {}
    for record in records:
        key = (
            record["workload"], record["size"], record["implementation"],
            record.get("variant", "canonical"),
        )
        if record["status"] == "ok":
            ok_groups.setdefault(key, []).append(record)
        else:
            censored.setdefault(key, []).append(record)

    groups = []
    medians: dict[tuple[str, int, str], float] = {}
    for (workload, size, implementation, variant) in sorted(
        set(ok_groups) | set(censored),
        key=lambda k: (k[0], k[1], k[2], k[3]),
    ):
        ok_recs = ok_groups.get((workload, size, implementation, variant), [])
        bad_recs = censored.get((workload, size, implementation, variant), [])
        statuses = sorted({r["status"] for r in bad_recs})
        entry: dict = {
            "workload": workload,
            "size": size,
            "implementation": implementation,
            "variant": variant,
            "status": "ok" if ok_recs and not bad_recs else (
                "ok" if ok_recs else statuses[0]
            ),
            "statuses": sorted({r["status"] for r in ok_recs} | set(statuses)),
            "errors": [r["error"] for r in bad_recs if r.get("error")],
        }
        if ok_recs:
            populate_ms = [r["populate_ns"] / 1e6 for r in ok_recs]
            init_ms = [r["container_init_ns"] / 1e6 for r in ok_recs]
            entry.update(_stats_ms(populate_ms))
            entry["container_init_median_ms"] = statistics.median(init_ms)
            entry["user_build_total_median_ms"] = (
                entry["median_ms"] + entry["container_init_median_ms"]
            )
            entry["peak_rss_median_bytes"] = statistics.median(
                [r.get("peak_rss_bytes") or 0 for r in ok_recs]
            )
            phased = [r.get("phases") for r in ok_recs if r.get("phases")]
            if phased and len(phased) == len(ok_recs):
                names = phased[0].keys()
                if all(set(p.keys()) == set(names) for p in phased):
                    entry["phase_median_ms"] = {
                        name: statistics.median([p[name] / 1e6 for p in phased])
                        for name in names
                    }
            if variant == "canonical":
                medians[(workload, size, implementation)] = entry["median_ms"]
        groups.append(entry)

    speedups = []
    for (workload, size, implementation), median in sorted(medians.items()):
        if implementation in PYTHON_PANEL + ("roml_python_naive_chain", "roml_python_scalar"):
            base = medians.get((workload, size, PYTHON_BASELINE))
            if base:
                speedups.append(
                    {
                        "panel": "formulation",
                        "workload": workload,
                        "size": size,
                        "numerator": implementation,
                        "denominator": PYTHON_BASELINE,
                        "speedup": median / base,
                    }
                )
        # roml-core panel baseline is the matched bulk arm: scalar-vs-Python
        # compares different core APIs, so only bulk-vs-bulk ratios measure
        # interface overhead. The scalar arm keeps its trace (general-path cost).
        if implementation in (
            "roml_python_naive_chain",
            "roml_python_bulk",
            "roml_core_rust",
            "roml_core_rust_anon",
        ):
            base = medians.get((workload, size, CORE_BULK_BASELINE))
            if base:
                speedups.append(
                    {
                        "panel": "roml-core",
                        "workload": workload,
                        "size": size,
                        "numerator": implementation,
                        "denominator": CORE_BULK_BASELINE,
                        "speedup": median / base,
                    }
                )
        if implementation in ("roml_python_csr", "pyoptinterface_python"):
            base = medians.get((workload, size, PYTHON_BASELINE))
            if base and implementation != PYTHON_BASELINE:
                speedups.append(
                    {
                        "panel": "ingestion",
                        "workload": workload,
                        "size": size,
                        "numerator": implementation,
                        "denominator": PYTHON_BASELINE,
                        "speedup": median / base,
                    }
                )

    return {
        "run_id": run_meta["run_id"],
        "profile": run_meta.get("profile"),
        "seed": run_meta.get("seed"),
        "benchmark_sha": run_meta.get("benchmark_sha"),
        "roml_sha": run_meta.get("roml_sha"),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "groups": groups,
        "speedups": speedups,
        "stopped": run_meta.get("stopped", []),
    }


def write_summary(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    summary = summarize_run(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    speedup_lookup = {
        (s["workload"], s["size"], s["numerator"]): s["speedup"]
        for s in summary["speedups"]
    }
    with open(run_dir / "summary.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "workload", "size", "implementation", "variant", "status", "replicates",
                "median_ms", "p25_ms", "p75_ms", "min_ms", "max_ms", "mad_ms",
                "container_init_median_ms", "user_build_total_median_ms",
                "peak_rss_median_bytes", "speedup_vs_baseline",
                "phase_variables_ms", "phase_constraints_ms", "phase_objective_ms",
            ]
        )
        for group in summary["groups"]:
            if group["implementation"] in ("roml_python_bulk", CORE_BASELINE):
                speedup = 1.0 if group.get("median_ms") is not None else ""
            else:
                speedup = speedup_lookup.get(
                    (group["workload"], group["size"], group["implementation"]), ""
                )
            phases = group.get("phase_median_ms", {})
            writer.writerow(
                [
                    group["workload"], group["size"], group["implementation"],
                    group.get("variant", "canonical"),
                    group["status"], group.get("replicates", ""),
                    _fmt(group.get("median_ms")), _fmt(group.get("p25_ms")),
                    _fmt(group.get("p75_ms")), _fmt(group.get("min_ms")),
                    _fmt(group.get("max_ms")), _fmt(group.get("mad_ms")),
                    _fmt(group.get("container_init_median_ms")),
                    _fmt(group.get("user_build_total_median_ms")),
                    group.get("peak_rss_median_bytes", ""),
                    _fmt(speedup) if speedup != "" else "",
                    _fmt(phases.get("variables")), _fmt(phases.get("constraints")),
                    _fmt(phases.get("objective")),
                ]
            )
    return summary


def _fmt(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
