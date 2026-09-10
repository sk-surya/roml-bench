# Forensic benchmark pass v2 — packet

Owner review of the v1 authoritative run (`20260908T042228Z-ai90-64615d6c`)
found real signal mixed with methodology flaws. PR #1 stays draft and is
not published as definitive. This packet defines the corrective forensic
pass. ROML itself is not modified; only `roml-bench` changes.

## Verified premises (read-only inspection of ROML @ 6062398b)

- `Expr.__add__` clones the entire `Affine` per `+`; `push_term` linearly
  scans `terms` for the variable. Naive `total = total + v` chaining is
  O(n^2). The v1 "350x binding overhead" headline measured this pathology,
  not PyO3 overhead. It is retracted as a binding-overhead claim.
- `add_linear_rows_impl` copies inputs and, per row, accumulates into a
  fresh `HashMap<VarId, f64>`, then sorts keys — even for clean CSR.
- `vars()` eagerly materializes and hash-reserves every element name.
- `rm.dot` accepts 2-D matching-shape arrays (incl. broadcast views), so a
  one-call fused BESS objective is the correct public fast path.

## Panel split (replaces the single leaderboard)

- **Formulation panel.** Input outside the timer: B, T, prices, dt, eta,
  limits (BESS) or N (sparse). Each arm derives rows/objective during
  timing. Arms: `roml_python_bulk` (fixed fused-dot BESS objective),
  `roml_python_naive_chain` (renamed v1 scalar; O(n^2) chaining disclosed),
  `pulp_python`, `pyomo_python`, `pyoptinterface_scalar` (new: scalar
  `add_variable` + per-row `ExprBuilder` formulation),
  `roml_core_rust`, `roml_core_rust_anon` (new: no `.named()` calls).
- **Matrix-ingestion panel.** Input outside the timer: shared CSR A,
  lower/upper, objective vector, variable bounds. Arms:
  `roml_python_bulk` (sparse CSR), `roml_python_csr` (new: BESS CSR via
  `add_linear_rows`), `pyoptinterface_python` (matrix). PuLP/Pyomo have no
  matrix API and are excluded here by design (stated on site, not hidden).

## Phase decomposition

Adapters may expose `populate_phases(model, case)` returning ordered
`(name, callable)` pairs (`variables`, `constraints`, `objective`). The
worker times each phase separately; `populate_ns` is the sum. The Rust
runner gains `--phase-breakdown` emitting the same. Phases required for:
ROML bulk, ROML naive chain, ROML CSR, PuLP, Pyomo, POI matrix, POI
scalar, core named/anon. Large sizes only in charts (sparse 100k/1M,
bess 100/300), but recorded for every point.

## Ingestion diagnostics (no ROML changes)

Worker flag `--csr-variant canonical|shuffled|duplicated` transforms the
shared CSR outside the timer (seeded): `shuffled` permutes in-row column
order (unique, unsorted); `duplicated` doubles every entry (exercises the
accumulation path; `constraint_nnz` records the actual built nnz).
Recorded in the optional `variant` field (default `canonical`).
Leaderboards and speedups use canonical only. Arms: ROML bulk + POI
matrix, sparse 100k/1M.

## Forensic run profile

Fresh full grid (one run, one host, one code): all arms x supported
workloads x standard sizes x 7 replicates, plus variants. `roml_python_csr`
supports bess_96 only; orchestrator skips unsupported pairs by design and
the site states panel membership. Same timeouts/RSS ceilings/pilot rule as
v1. Estimated ~800 child runs.

## Site v2 (same service, regenerated content)

- Retraction banner: 350x binding-overhead claim withdrawn; BESS v1
  leaderboard split into formulation vs ingestion.
- Formulation and ingestion sections with fixed arm lists.
- Phase-decomposition stacked bars; ingestion-diagnostics grouped bars;
  named-vs-anon core comparison.
- `data.html`: variant column + per-phase median columns.

## Acceptance

- Fused-dot BESS objective proves equivalence through the validation gate
  (cross-solver agreement, unchanged tolerance).
- All gates green (ruff, pytest, fmt, clippy, cargo tests, validate).
- Forensic run committed with site; service still serving; FINAL-REPORT v2
  addendum with corrected findings.
- PR #1 remains draft; a v2 draft PR is opened. Nothing merged.
