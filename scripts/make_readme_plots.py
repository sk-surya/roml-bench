#!/usr/bin/env python3
"""Benchmark v2 — generate README SVG plots from machine-readable evidence.

Every value is read from committed benchmark artifacts (a run's ``summary.json``
and the persistence harness JSON). No value is hand-entered. Output SVGs are
static, white-backed (readable in GitHub light and dark mode), and sized for
README/mobile widths.

Usage:
  python scripts/make_readme_plots.py --run results/runs/<id> \
      --persist <persist.json> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import math
import os

W = 760
PAD_L, PAD_R, PAD_T, PAD_B = 200, 90, 58, 34
BLUE = "#2563eb"
DARK = "#111827"
GRAY = "#6b7280"
LIGHT = "#9ca3af"
TEXT = "#1f2937"
SUB = "#6b7280"
GRID = "#e5e7eb"
FG = "#ffffff"


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def header(title: str, subtitle: str, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" font-family="-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">',
        f'<rect width="{W}" height="{height}" fill="{FG}"/>',
        f'<text x="16" y="26" font-size="17" font-weight="700" fill="{TEXT}">{esc(title)}</text>',
        f'<text x="16" y="46" font-size="12" fill="{SUB}">{esc(subtitle)}</text>',
    ]


def hbar_chart(title: str, subtitle: str, items: list[dict], unit: str) -> str:
    """items: [{label, value, lo, hi, color}] — lower is better."""
    row_h = 30
    height = PAD_T + row_h * len(items) + PAD_B
    vmax = max(i["hi"] for i in items) * 1.02
    plot_w = W - PAD_L - PAD_R
    out = header(title, subtitle, height)
    # axis
    out.append(
        f'<line x1="{PAD_L}" y1="{height - PAD_B}" x2="{PAD_L + plot_w}" '
        f'y2="{height - PAD_B}" stroke="{GRID}" stroke-width="1"/>'
    )
    for idx, it in enumerate(items):
        y = PAD_T + idx * row_h
        bw = max(2.0, plot_w * it["value"] / vmax)
        out.append(
            f'<text x="{PAD_L - 10}" y="{y + 19}" font-size="13" fill="{TEXT}" '
            f'text-anchor="end">{esc(it["label"])}</text>'
        )
        out.append(
            f'<rect x="{PAD_L}" y="{y + 5}" width="{bw:.1f}" height="18" rx="3" '
            f'fill="{it["color"]}"/>'
        )
        # p25..p75 whisker
        x1 = PAD_L + plot_w * it["lo"] / vmax
        x2 = PAD_L + plot_w * it["hi"] / vmax
        out.append(
            f'<line x1="{x1:.1f}" y1="{y + 14}" x2="{x2:.1f}" y2="{y + 14}" '
            f'stroke="{DARK}" stroke-width="1" opacity="0.35"/>'
        )
        label = f'{it["value"]:.2f}'
        out.append(
            f'<text x="{PAD_L + bw + 8:.1f}" y="{y + 19}" font-size="12" '
            f'fill="{TEXT}">{label} {unit}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def line_chart(title: str, subtitle: str, x_labels: list[int], series: list[dict],
               unit: str) -> str:
    """series: [{label, values, color}]; log10 y-axis; x evenly spaced."""
    height = 360
    plot_w = W - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    vals = [v for s in series for v in s["values"] if v and v > 0]
    lo = math.log10(min(vals) * 0.8)
    hi = math.log10(max(vals) * 1.25)

    def px(i: int) -> float:
        if len(x_labels) == 1:
            return PAD_L + plot_w / 2
        return PAD_L + plot_w * i / (len(x_labels) - 1)

    def py(v: float) -> float:
        return PAD_T + plot_h * (1 - (math.log10(v) - lo) / (hi - lo))

    out = header(title, subtitle, height)
    for g in range(5):
        lv = lo + (hi - lo) * g / 4
        y = py(10**lv)
        out.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L + plot_w}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" font-size="11" fill="{SUB}" '
            f'text-anchor="end">{10**lv:.0f}</text>'
        )
    for i, xl in enumerate(x_labels):
        out.append(
            f'<text x="{px(i):.1f}" y="{height - PAD_B + 18}" font-size="11" '
            f'fill="{SUB}" text-anchor="middle">{xl}</text>'
        )
    for s in series:
        pts = [
            (px(i), py(v))
            for i, v in enumerate(s["values"])
            if v and v > 0
        ]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        out.append(
            f'<polyline points="{path}" fill="none" stroke="{s["color"]}" '
            f'stroke-width="2.2"/>'
        )
        for x, y in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{s["color"]}"/>')
    # legend
    lx = PAD_L
    for s in series:
        out.append(f'<rect x="{lx}" y="{PAD_T - 26}" width="12" height="12" rx="2" fill="{s["color"]}"/>')
        out.append(f'<text x="{lx + 17}" y="{PAD_T - 15}" font-size="12" fill="{TEXT}">{esc(s["label"])}</text>')
        lx += 22 + 8 * len(s["label"])
    out.append(f'<text x="{W - 16}" y="{height - 8}" font-size="11" fill="{SUB}" text-anchor="end">{esc(unit)} (log scale)</text>')
    out.append("</svg>")
    return "\n".join(out)


def groups(summary: dict, workload: str, size: int, variant: str = "canonical"):
    return {
        g["implementation"]: g
        for g in summary["groups"]
        if g["workload"] == workload
        and g["size"] == size
        and g.get("variant", "canonical") == variant
        and g["status"] == "ok"
    }


# Formulation arms (equivalent user-facing formulation APIs). Ingestion arms
# (roml_python_csr, pyoptinterface_python, roml_core_bulk) are excluded.
FORMULATION = [
    ("roml_core_l1", "ROML Rust L1 (array API)", BLUE),
    ("roml_python_vectorized", "ROML Python vectorized", "#1d4ed8"),
    ("pyomo_python", "Pyomo", GRAY),
    ("pulp_python", "PuLP", LIGHT),
    ("pyoptinterface_scalar", "PyOptInterface (scalar)", "#4b5563"),
    ("jump_julia", "JuMP", "#7c3aed"),
    ("ortools_mathopt_cpp", "OR-Tools MathOpt", "#0891b2"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--persist", default=None)
    ap.add_argument("--out", default="plots")
    ap.add_argument("--bess-size", type=int, default=300)
    ap.add_argument("--rule-sizes", nargs="*", type=int, default=None)
    ap.add_argument("--sparse-sizes", nargs="*", type=int, default=None)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    with open(os.path.join(args.run, "summary.json")) as f:
        summary = json.load(f)
    roml_sha = summary.get("roml_sha", "unknown")
    bench_sha = summary.get("benchmark_sha", "unknown")

    def write(name: str, svg: str) -> None:
        with open(os.path.join(args.out, name), "w") as f:
            f.write(svg + "\n")
        print("wrote", name)

    # 1. Competitive formulation (bess_96 B=300)
    gs = groups(summary, "bess_96", args.bess_size)
    items = []
    for impl, label, color in FORMULATION:
        if impl in gs:
            g = gs[impl]
            items.append(
                {
                    "label": label,
                    "value": g["median_ms"],
                    "lo": g["p25_ms"],
                    "hi": g["p75_ms"],
                    "color": color,
                }
            )
    if items:
        write(
            "competitive_formulation.svg",
            hbar_chart(
                f"Formulation construction — BESS B={args.bess_size}, T=96",
                f"median model-construction time, identical model, box = p25–p75 "
                f"(roml {roml_sha[:8]}, bench {bench_sha[:8]}); lower is better",
                sorted(items, key=lambda i: i["value"]),
                "ms",
            ),
        )

    # 2. ROML abstraction tax (param_bess B=300; raw L2 = 1.00)
    gs = groups(summary, "param_bess", args.bess_size)
    tax_arms = [
        ("roml_core_bulk_param", "raw L2 (block + packed)", DARK),
        ("roml_core_l1_param", "Rust L1 (array API)", BLUE),
        ("roml_python_param", "Python Model", "#1d4ed8"),
        ("roml_python_concrete", "Python ConcreteModel + labels", "#60a5fa"),
    ]
    if all(impl in gs for impl, _, _ in tax_arms):
        base = gs["roml_core_bulk_param"]["median_ms"]
        items = []
        for impl, label, color in tax_arms:
            g = gs[impl]
            items.append(
                {
                    "label": label,
                    "value": g["median_ms"] / base,
                    "lo": g["p25_ms"] / base,
                    "hi": g["p75_ms"] / base,
                    "color": color,
                }
            )
        write(
            "abstraction_tax.svg",
            hbar_chart(
                f"ROML modeling-layer overhead — parameterized BESS B={args.bess_size}",
                "median construction, normalized to the raw L2 block path = 1.00 "
                "(same fixture; box = p25–p75); lower is better",
                items,
                "x",
            ),
        )

    # 3. Indexed-rules scaling
    rs = args.rule_sizes
    if rs is None:
        rs = sorted({g["size"] for g in summary["groups"] if g["workload"] == "rule_rows"})
    if rs:
        rule_arms = [
            ("roml_core_rules", "ROML Rust add_indexed_rules", BLUE),
            ("roml_python_rules", "ROML Python rules API", "#1d4ed8"),
            ("pyomo_python", "Pyomo indexed rule", GRAY),
        ]
        series = []
        for impl, label, color in rule_arms:
            vals = [groups(summary, "rule_rows", s).get(impl, {}).get("median_ms") for s in rs]
            if any(vals):
                series.append({"label": label, "values": vals, "color": color})
        if series:
            write(
                "rules_scaling.svg",
                line_chart(
                    "Indexed-rule construction — N rows x 10 variables",
                    "median construction time vs rows (sum_j x[i,j] <= cap[i]); lower is better",
                    rs,
                    series,
                    "ms",
                ),
            )

    # 4. Persistent optimization
    if args.persist and os.path.exists(args.persist):
        with open(args.persist) as f:
            pj = json.load(f)
        arms = pj["arms"]
        order = [
            ("roml_direct", "ROML direct update", BLUE),
            ("roml_template", "ROML Template.bind", "#1d4ed8"),
            ("pulp_rebuild", "PuLP rebuild + solve", LIGHT),
            ("pyomo_rebuild", "Pyomo rebuild + solve", GRAY),
        ]
        items = []
        for key, label, color in order:
            a = arms.get(key)
            if not a:
                continue
            e = a["end_to_end_ms"]
            items.append(
                {
                    "label": label,
                    "value": e["median"],
                    "lo": e["min"],
                    "hi": e["max"],
                    "color": color,
                }
            )
        if items:
            write(
                "persistent.svg",
                hbar_chart(
                    "Models that change — update + re-solve per cycle",
                    f"{pj['shape'][0]}-product x {pj['shape'][1]}-period plan, "
                    f"{pj['cycles']} cycles; ROML is persistent update, competitors "
                    "are rebuild + solve (whisker = min–max); lower is better",
                    sorted(items, key=lambda i: i["value"]),
                    "ms",
                ),
            )

    # 5. Scale curve — BESS formulation panel (the coherent comparison with a
    # current ROML formulation arm). Sparse_rows is an ingestion panel and is
    # deliberately not mixed with competitor algebraic formulations here.
    bs = sorted({g["size"] for g in summary["groups"] if g["workload"] == "bess_96"})
    if len(bs) >= 2:
        scale_arms = [
            ("roml_core_l1", "ROML Rust L1", BLUE),
            ("roml_python_vectorized", "ROML Python vectorized", "#1d4ed8"),
            ("pyoptinterface_scalar", "PyOptInterface (scalar)", "#4b5563"),
            ("pyomo_python", "Pyomo", GRAY),
            ("pulp_python", "PuLP", LIGHT),
        ]
        series = []
        for impl, label, color in scale_arms:
            vals = [groups(summary, "bess_96", s).get(impl, {}).get("median_ms") for s in bs]
            if any(vals):
                series.append({"label": label, "values": vals, "color": color})
        if series:
            write(
                "scale_curve.svg",
                line_chart(
                    "Scale — BESS formulation construction",
                    "median construction time vs batteries B (T=96); lower is better",
                    bs,
                    series,
                    "ms",
                ),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
