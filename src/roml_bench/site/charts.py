"""Plotly figure builders for the offline benchmark site.

Every trace uses measured medians with p25/p75 asymmetric error bars.
No smoothing, interpolation, or extrapolation: missing points are gaps.
"""

from __future__ import annotations

import plotly.graph_objects as go

COLORS = {
    "roml_python_bulk": "#0072B2",
    "roml_python_scalar": "#56B4E9",
    "roml_core_rust": "#009E73",
    "pulp_python": "#D55E00",
    "pyomo_python": "#CC79A7",
    "pyoptinterface_python": "#E69F00",
}

LABELS = {
    "roml_python_bulk": "ROML Python (bulk)",
    "roml_python_scalar": "ROML Python (scalar)",
    "roml_core_rust": "ROML core (Rust)",
    "pulp_python": "PuLP",
    "pyomo_python": "Pyomo",
    "pyoptinterface_python": "PyOptInterface",
}

PYTHON_ORDER = [
    "roml_python_bulk",
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_python",
]

CORE_ORDER = ["roml_python_scalar", "roml_python_bulk", "roml_core_rust"]


def _layout(title: str, xtitle: str, ytitle: str) -> dict:
    return {
        "title": title,
        "xaxis": {"title": xtitle, "type": "log"},
        "yaxis": {"title": ytitle, "type": "log"},
        "template": "plotly_white",
        "legend": {"orientation": "h", "y": -0.25},
        "margin": {"b": 100},
    }


def _group_lookup(summary: dict) -> dict:
    return {(g["workload"], g["size"], g["implementation"]): g for g in summary["groups"]}


def time_vs_size(
    summary: dict, workload: str, implementations: list[str], title: str
) -> go.Figure:
    lookup = _group_lookup(summary)
    sizes = sorted({g["size"] for g in summary["groups"] if g["workload"] == workload})
    fig = go.Figure()
    for impl in implementations:
        xs, ys, lo, hi, notes = [], [], [], [], []
        for size in sizes:
            group = lookup.get((workload, size, impl))
            if group is None or "median_ms" not in group:
                continue
            xs.append(size)
            ys.append(group["median_ms"])
            lo.append(group["median_ms"] - group["p25_ms"])
            hi.append(group["p75_ms"] - group["median_ms"])
            notes.append(
                f"{LABELS[impl]}<br>size {size}<br>"
                f"median {group['median_ms']:.3g} ms<br>"
                f"p25 {group['p25_ms']:.3g} / p75 {group['p75_ms']:.3g} ms<br>"
                f"n={group['replicates']}"
            )
        if not xs:
            continue
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines+markers", name=LABELS[impl],
                marker={"color": COLORS[impl], "size": 8},
                line={"color": COLORS[impl]},
                error_y={"type": "data", "array": hi, "arrayminus": lo, "visible": True},
                hovertext=notes, hoverinfo="text",
            )
        )
    fig.update_layout(**_layout(title, "problem size", "populate time, median ms (log)"))
    return fig


def time_vs_nnz(
    summary: dict, workload: str, implementations: list[str], nnz_of: dict, title: str
) -> go.Figure:
    lookup = _group_lookup(summary)
    fig = go.Figure()
    for impl in implementations:
        xs, ys, lo, hi, notes = [], [], [], [], []
        for (w, size, name), group in sorted(lookup.items()):
            if w != workload or name != impl or "median_ms" not in group:
                continue
            nnz = nnz_of[size]
            xs.append(nnz)
            ys.append(group["median_ms"])
            lo.append(group["median_ms"] - group["p25_ms"])
            hi.append(group["p75_ms"] - group["median_ms"])
            notes.append(f"{LABELS[impl]}<br>nnz {nnz}<br>median {group['median_ms']:.3g} ms")
        if not xs:
            continue
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines+markers", name=LABELS[impl],
                marker={"color": COLORS[impl], "size": 8},
                line={"color": COLORS[impl]},
                error_y={"type": "data", "array": hi, "arrayminus": lo, "visible": True},
                hovertext=notes, hoverinfo="text",
            )
        )
    fig.update_layout(
        **_layout(
            title,
            "model nonzeros (constraints + objective)",
            "populate time, median ms (log)",
        )
    )
    return fig


def speedup_chart(summary: dict, panel: str, title: str, subtitle: str) -> go.Figure:
    points = [s for s in summary["speedups"] if s["panel"] == panel]
    by_impl: dict[str, list] = {}
    for point in sorted(points, key=lambda s: (s["numerator"], s["size"])):
        by_impl.setdefault(point["numerator"], []).append(point)
    fig = go.Figure()
    for impl, pts in by_impl.items():
        fig.add_trace(
            go.Scatter(
                x=[p["size"] for p in pts],
                y=[p["speedup"] for p in pts],
                mode="lines+markers",
                name=f"{LABELS[impl]} / {LABELS[pts[0]['denominator']]}",
                marker={"color": COLORS[impl], "size": 8},
                line={"color": COLORS[impl]},
                hovertext=[
                    f"{LABELS[impl]} vs {LABELS[p['denominator']]}<br>"
                    f"size {p['size']}<br>speedup {p['speedup']:.3g}x"
                    for p in pts
                ],
                hoverinfo="text",
            )
        )
    fig.update_layout(
        title=title + "<br><sub>" + subtitle + "</sub>",
        xaxis={"title": "problem size", "type": "log"},
        yaxis={"title": "speedup vs baseline, median ratio (log)", "type": "log"},
        template="plotly_white",
        legend={"orientation": "h", "y": -0.3},
        margin={"b": 110},
        shapes=[{
            "type": "line", "xref": "paper", "x0": 0, "x1": 1,
            "yref": "y", "y0": 1, "y1": 1,
            "line": {"dash": "dash", "color": "#888"},
        }],
    )
    return fig


def memory_chart(summary: dict, workload: str, implementations: list[str], title: str) -> go.Figure:
    lookup = _group_lookup(summary)
    sizes = sorted({g["size"] for g in summary["groups"] if g["workload"] == workload})
    fig = go.Figure()
    for impl in implementations:
        xs, ys = [], []
        for size in sizes:
            group = lookup.get((workload, size, impl))
            if group is None or "peak_rss_median_bytes" not in group:
                continue
            xs.append(size)
            ys.append(group["peak_rss_median_bytes"] / 1024**2)
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys, mode="lines+markers", name=LABELS[impl],
                    marker={"color": COLORS[impl], "size": 8},
                    line={"color": COLORS[impl]},
                    hovertext=[
                        f"{LABELS[impl]}<br>size {s}<br>{v:.1f} MiB"
                        for s, v in zip(xs, ys)
                    ],
                    hoverinfo="text",
                )
            )
    fig.update_layout(**_layout(title, "problem size", "child peak RSS, median MiB (log)"))
    return fig


def figure_div(fig: go.Figure) -> str:
    import plotly.io as pio

    return pio.to_html(fig, include_plotlyjs=False, full_html=False)
