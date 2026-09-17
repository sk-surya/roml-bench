# Benchmark v2 — post-MIR ROML (authoritative report)

All values are generated from committed machine-readable artifacts; none is
hand-entered. Plots are produced by `scripts/make_readme_plots.py` from
`results/runs/20260917T190702Z-ai90-116c1be9/summary.json` and
`results/v2/persistent.json`.

## Pins and environment

- `roml-bench` measured SHA: `116c1be902bd5d0d277f54e5a3c091c0c1a1a292`
- ROML SHA: `f1dc3e6df181b638623f59726bd03c15729d568e` (merged PR #71)
- Canonical seed `20260908`; profile `standard`, 7 replicates per point;
  serial `-j 1`, one pinned logical CPU, `OMP/OPENBLAS/MKL/NUMEXPR/RAYON_NUM_THREADS=1`.
- Python 3.13.14, NumPy 2.5.3, HiGHS 1.15.1, PuLP 3.3.1, Pyomo 6.10.1,
  PyOptInterface 0.6.1, rustc/cargo 1.97.1.
- Host: AMD Ryzen 9 9950X (16C/32T), 59.5 GiB, Linux 7.0.0-31-generic, idle.
  Absolute times are host-specific; compare medians/ratios.

## Validation

`roml-bench validate` ok for all 19 participating arms at the measured SHA
(structural counts exact; cross-arm objective agreement within 1e-7 abs+rel;
bound spot checks; IR-28-analogue replay proof retained). The authoritative
run: **176/176 canonical groups ok, 0 errors/timeouts.**

## Panels (methodologically separated)

### 1. High-level formulation — BESS B=300, T=96 (medians, ms)

| arm | median |
| --- | ---: |
| ROML Rust L1 (current array API) | **14.59** |
| OR-Tools MathOpt (C++) | 33.19 |
| ROML Python vectorized (fused `rm.dot`) | 33.78 |
| PyOptInterface (scalar formulation) | 124.78 |
| JuMP | 156.27 |
| Pyomo (indexed rules + quicksum) | 336.41 |
| PuLP | 470.41 |
| _(raw L2 block, internal lower bound)_ | _11.84_ |

Ratios: ROML Rust L1 is **23.1×** Pyomo, **9.9×** on the Python vectorized path
(vs Pyomo), and **2.3×** the internal raw-L2 bound. Current-ROM ROML is the
fastest compared user-facing formulation at this point.

### 2. Matrix / CSR ingestion (separate panel)

`sparse_rows` N=1M: ROML Python CSR (`add_linear_rows`) **128.70 ms**; ROML
raw-L2 bulk `97.56`; PyOptInterface matrix `1534.02`. These are ingestion
numbers and are never mixed with the formulation chart.

### 3. ROML abstraction tax — `param_bess` B=300 (normalized to raw L2 = 1.00)

| arm | ratio |
| --- | ---: |
| raw L2 (block vars + parameter block + packed objective) | 1.00 |
| Rust L1 (array API) | 0.92 |
| Python `Model` (parameter arrays) | 1.21 |
| Python `ConcreteModel` + labels/Sets | 1.21 |

**ConcreteModel / Python Model = 1.00** — the labeled/Set ergonomics surface
costs no measurable overhead over plain `Model`. Lowering evidence (from
`param-evidence`): both core arms `general_affine=0`, `param_dep_blocks=2`,
`param_positions_cells=0`, identical canonical fingerprints
(`8311104305927858589`) — the packed dependency representation, not per-cell
positions.

### 4. Indexed rules — `rule_rows` (N rows × 10), medians (ms)

| N | ROML Rust `add_indexed_rules` | ROML Python rules | Pyomo indexed rule |
| ---: | ---: | ---: | ---: |
| 1,000 | **3.01** | 5.63 | 7.92 |
| 10,000 | **29.53** | 55.19 | 93.75 |
| 100,000 | **407.70** | 573.67 | 1384.87 |

ROML Rust is 3.4× Pyomo at 100k; ROML Python 2.4×. Scaling is smooth (no
superlinear blow-up beyond the workload's own growth).

### 5. Dynamic / persistent — 4-product × 24-period plan, 50 cycles (ms)

| arm | mechanism | end-to-end p50 | rebuild? |
| --- | --- | ---: | --- |
| ROML direct `Model.update` | persistent | **0.290** | no |
| ROML `Template.bind` (same structure) | persistent | 0.306 | no |
| PuLP | rebuild + solve | 3.230 | **yes** |
| Pyomo | rebuild + solve | 7.713 | **yes** |

ROML persistent update is **26.6×** faster per cycle than Pyomo's rebuild+solve
and **11.1×** PuLP's. Retention is disclosed per arm (`model_retained`,
`solver_object_retained`, `backend_solver_model_retained`). Rebuild arms are
never presented as equivalent to a persistent update.

## Plot inventory (generated, no hand values)

| plot | source artifact |
| --- | --- |
| `competitive_formulation.svg` | run `summary.json` (bess_96/300) |
| `abstraction_tax.svg` | run `summary.json` (param_bess/300) |
| `rules_scaling.svg` | run `summary.json` (rule_rows 1k/10k/100k) |
| `persistent.svg` | `results/v2/persistent.json` |
| `scale_curve.svg` | run `summary.json` (bess_96 1..300) |

## Superseded v1 claims

- The v1 **“350× binding overhead”** headline remains **retracted** (it
  measured O(n²) expression chaining, not PyO3 overhead).
- The v1 **BESS single leaderboard** remains **withdrawn** (preassembled CSR
  for one arm vs algebra for another). v2 keeps formulation and ingestion
  panels separate.
- All v1 ROML numbers were measured on `6062398`/`c590692`; v2 supersedes them
  on `f1dc3e6`.

## Known limitations

- Absolute timings are single-host; only same-run medians/ratios are meaningful.
- PuLP validation solves use bundled CBC; Pyomo uses appsi_highs; ROML uses
  bundled HiGHS — construction isolated from solve; cross-solver objective
  agreement is checked in validation.
- `roml_core_rust` / `roml_core_rust_anon` are **LEGACY DIAGNOSTIC** (scalar
  builder), excluded from the formulation headline.
- `roml_python_naive_chain` is a disclosed pathology arm (O(n²)), not a
  binding-overhead claim.

## Artifacts

- Run: `results/runs/20260917T190702Z-ai90-116c1be9/` (raw.jsonl, run.json,
  summary.json, summary.csv).
- Persistence: `results/v2/persistent.json`.
- Plots: `results/v2/plots/*.svg`.
- Adapter audit: `.planning/ADAPTER-AUDIT.md`.
