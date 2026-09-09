"""Plotly figure builders for the offline benchmark site.

Every trace uses measured medians with p25/p75 asymmetric error bars.
No smoothing, interpolation, or extrapolation: missing points are gaps.
"""

from __future__ import annotations

import plotly.graph_objects as go

COLORS = {
    "roml_python_bulk": "#0072B2",
    "roml_python_naive_chain": "#56B4E9",
    "roml_python_scalar": "#56B4E9",
    "roml_python_csr": "#9467BD",
    "roml_core_rust": "#009E73",
    "roml_core_rust_anon": "#2CA02C",
    "roml_core_bulk": "#17BECF",
    "pulp_python": "#D55E00",
    "pyomo_python": "#CC79A7",
    "pyoptinterface_python": "#E69F00",
    "pyoptinterface_scalar": "#8C564B",
}

LABELS = {
    "roml_python_bulk": "ROML Python (bulk)",
    "roml_python_naive_chain": "ROML Python (naive chain)",
    "roml_python_scalar": "ROML Python (scalar, v1 legacy)",
    "roml_python_csr": "ROML Python (CSR ingest)",
    "roml_core_rust": "ROML core, scalar (Rust)",
    "roml_core_rust_anon": "ROML core, anonymous (Rust)",
    "roml_core_bulk": "ROML core, bulk (Rust)",
    "pulp_python": "PuLP",
    "pyomo_python": "Pyomo",
    "pyoptinterface_python": "PyOptInterface (matrix)",
    "pyoptinterface_scalar": "PyOptInterface (scalar)",
}

FORMULATION_ORDER = [
    "roml_python_bulk",
    "roml_python_naive_chain",
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_scalar",
]

INGESTION_ORDER = [
    "roml_python_bulk",
    "roml_python_csr",
    "pyoptinterface_python",
]

CORE_ORDER = [
    "roml_python_naive_chain",
    "roml_python_bulk",
    "roml_core_rust",
    "roml_core_rust_anon",
    "roml_core_bulk",
]

# Marker symbol + line dash per arm so traces stay distinguishable
# without relying on color alone.
MARKERS = {
    "roml_python_bulk": "circle",
    "roml_python_naive_chain": "x",
    "roml_python_scalar": "x",
    "roml_python_csr": "diamond",
    "roml_core_rust": "square",
    "roml_core_rust_anon": "square-open",
    "roml_core_bulk": "triangle-up",
    "pulp_python": "cross",
    "pyomo_python": "triangle-down",
    "pyoptinterface_python": "star",
    "pyoptinterface_scalar": "hexagon",
}

DASHES = {
    "roml_python_bulk": "solid",
    "roml_python_naive_chain": "dot",
    "roml_python_scalar": "dot",
    "roml_python_csr": "dashdot",
    "roml_core_rust": "dash",
    "roml_core_rust_anon": "dash",
    "roml_core_bulk": "solid",
    "pulp_python": "dot",
    "pyomo_python": "dash",
    "pyoptinterface_python": "solid",
    "pyoptinterface_scalar": "dashdot",
}


def _trace_style(impl):
    return (
        {"color": COLORS[impl], "size": 9, "symbol": MARKERS.get(impl, "circle")},
        {"color": COLORS[impl], "dash": DASHES.get(impl, "solid")},
    )

PYTHON_ORDER = FORMULATION_ORDER  # backward-compatible alias


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
    return {
        (g["workload"], g["size"], g["implementation"], g.get("variant", "canonical")): g
        for g in summary["groups"]
    }


def _canonical_lookup(summary: dict) -> dict:
    return {
        (g["workload"], g["size"], g["implementation"]): g
        for g in summary["groups"]
        if g.get("variant", "canonical") == "canonical"
    }


def time_vs_size(
    summary: dict, workload: str, implementations: list[str], title: str
) -> go.Figure:
    lookup = _canonical_lookup(summary)
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
        marker, line = _trace_style(impl)
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines+markers", name=LABELS[impl],
                marker=marker,
                line=line,
                error_y={"type": "data", "array": hi, "arrayminus": lo, "visible": True},
                hovertext=notes, hoverinfo="text",
            )
        )
    fig.update_layout(**_layout(title, "problem size", "populate time, median ms (log)"))
    return fig


def time_vs_nnz(
    summary: dict, workload: str, implementations: list[str], nnz_of: dict, title: str
) -> go.Figure:
    lookup = _canonical_lookup(summary)
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
        marker, line = _trace_style(impl)
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines+markers", name=LABELS[impl],
                marker=marker,
                line=line,
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
    lookup = _canonical_lookup(summary)
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


def headline_bars(
    summary: dict, workload: str, size: int, implementations: list[str], title: str
) -> go.Figure:
    """Linear-scale bar chart: median populate ms per implementation at one point.

    Head-to-head at a fixed size reads better linear than log; the
    scaling curves keep their log axes. Bars carry p25/p75 whiskers and
    exact medians as text.
    """
    lookup = _canonical_lookup(summary)
    names, vals, lo, hi, notes = [], [], [], [], []
    for impl in implementations:
        group = lookup.get((workload, size, impl))
        if group is None or "median_ms" not in group:
            continue
        names.append(LABELS[impl])
        vals.append(group["median_ms"])
        lo.append(group["median_ms"] - group["p25_ms"])
        hi.append(group["p75_ms"] - group["median_ms"])
        notes.append(
            f"{LABELS[impl]}<br>median {group['median_ms']:.3g} ms<br>"
            f"p25 {group['p25_ms']:.3g} / p75 {group['p75_ms']:.3g} ms<br>"
            f"n={group['replicates']}"
        )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=names, y=vals,
            marker={"color": [
                COLORS[i]
                for i in implementations
                if (workload, size, i) in lookup
                and "median_ms" in lookup[(workload, size, i)]
            ]},
            error_y={"type": "data", "array": hi, "arrayminus": lo, "visible": True},
            text=[f"{v:.3g}" for v in vals],
            textposition="outside",
            hovertext=notes, hoverinfo="text",
        )
    )
    layout = _layout(title, "", "populate time, median ms (linear)")
    layout["xaxis"] = {"tickangle": -25, "automargin": True}
    layout["yaxis"] = {"type": "linear"}
    layout["margin"] = {"b": 160}
    layout["showlegend"] = False
    fig.update_layout(**layout)
    return fig


def figure_div(fig: go.Figure) -> str:
    import plotly.io as pio

    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def phase_breakdown_chart(
    summary: dict, workload: str, size: int, implementations: list[str], title: str
) -> go.Figure:
    """Stacked variables/constraints/objective medians for one point."""
    lookup = _canonical_lookup(summary)
    phases = ["variables", "constraints", "objective"]
    fig = go.Figure()
    for phase in phases:
        xs, ys, notes = [], [], []
        for impl in implementations:
            group = lookup.get((workload, size, impl))
            if group is None or phase not in group.get("phase_median_ms", {}):
                continue
            value = group["phase_median_ms"][phase]
            xs.append(LABELS[impl])
            ys.append(value)
            notes.append(f"{LABELS[impl]}<br>{phase} median {value:.3g} ms")
        if xs:
            fig.add_trace(go.Bar(x=xs, y=ys, name=phase, hovertext=notes, hoverinfo="text"))
    fig.update_layout(
        title=title,
        barmode="stack",
        xaxis={"title": "implementation"},
        yaxis={"title": "phase median ms (log)", "type": "log"},
        template="plotly_white",
        margin={"b": 110},
    )
    return fig


def variant_chart(
    summary: dict, workload: str, size: int, implementations: list[str], title: str
) -> go.Figure:
    """Grouped canonical/shuffled/duplicated medians for CSR arms."""
    lookup = _group_lookup(summary)
    fig = go.Figure()
    for variant in ("canonical", "shuffled", "duplicated"):
        xs, ys, notes = [], [], []
        for impl in implementations:
            group = lookup.get((workload, size, impl, variant))
            if group is None or "median_ms" not in group:
                continue
            xs.append(LABELS[impl])
            ys.append(group["median_ms"])
            notes.append(f"{LABELS[impl]}<br>{variant} median {group['median_ms']:.3g} ms")
        if xs:
            fig.add_trace(go.Bar(x=xs, y=ys, name=variant, hovertext=notes, hoverinfo="text"))
    fig.update_layout(
        title=title
        + "<br><sub>diagnostic only: not a leaderboard; "
        "duplicated rows carry 2x nnz</sub>",
        barmode="group",
        xaxis={"title": "implementation"},
        yaxis={"title": "populate median ms (log)", "type": "log"},
        template="plotly_white",
        margin={"b": 110},
    )
    return fig
