# P1 AFTER — packed rows + Python CSR

Implementation in ROML (`perf-p0-bulk-objective` branch, stacked, unmerged).
Only gate reruns here: native 100k×10 rows, Python CSR sparse/BESS, 1M
commit/RSS. No array lowering (P1C untouched).

## Method

- Native: ROML `bulk_objective_probe rowsbulk` (release, pinned CPU 5):
  scalar vars + `add_linear_rows_bulk` + commit + snapshot. Store-only
  component via ignored in-crate probe (`perf_probe_append_rows_100k`).
- Python: release wheel of the P1 worktree; scripts mirror
  `roml_python_bulk` (sparse) and `roml_python_csr` (BESS) recipes
  exactly. Formulation only, pinned CPU 6.
- BEFORE medians: forensic run `20260908T053319Z-ai90-14738229`
  (roml_python_bulk, n=7) and P1.5B-era probes.

## Gate verdicts

| Metric | Required | Desired | AFTER |
|---|---|---|---|
| native 100k×10 row insertion | <100 ms | <50 ms | **27–28 ms — PASS both** (store append 2.5 ms) |
| Python add_linear_rows (100k rows) | <150 ms | <100 ms | **~54 ms — PASS both** (10k rows: 5.1 ms) |
| Python sparse-1M total | <600 ms | <500 ms | **~440 ms — PASS both** (vars ~350 + rows ~54 + obj ~40) |
| BESS300 CSR total | <100 ms | <80 ms | **~38 ms — PASS both** (16 + 19 + 2.6) |
| 1M commit | no regression, ideally <150 ms | — | **92.9 ms — PASS** (one packed op; no cell explosion) |
| construction RSS | materially below 714 MB | <500 MB | Python 581 MB (below 714 ✓ / 500 ✗ — eager names parked); native rowsbulk 323 MB |

BEFORE→AFTER: Python sparse constraints 591→54 ms (11×); sparse total
1710→440 ms (3.9×); BESS constraints 135→19 ms; native row path ~19× vs
per-row LinExpr construction (524 ms forensic core, recipe-equivalent).

## Required breakdown (native 100k rows / 1M cells)

| Stage | Time | Notes |
|---|---|---|
| CSR parse/map (Python side) | ~25 ms | inferred: 54 Python − 28.5 native; NumPy parse + validation + flat pack |
| row validation + canonicalization + constraint alloc + store append + journal | 28.5 ms total | store append 2.5 ms measured; journal = 1 push |
| commit | 92.9 ms | one packed op; F2-linear reconstruction |
| snapshot | 391.2 ms | residual per-cell dep-`Vec` + fat sort (P1.5 note) |
| RSS | 323 MB construction / 846 MB peak | peak still row-journal + snapshot temporaries |

## Raw CSR vs idiomatic BESS (the P1C decision input)

- Raw CSR (`roml_python_csr` recipe): **~38 ms** total.
- Idiomatic array syntax (`roml_python_bulk` recipe): ~185 ms total.
- Gap ≈ **5×**, concentrated in ComparisonArray lowering + parameterized
  dot (~150 ms) vs CSR parse (~19 ms). That is the measured P1C prize.

## Test matrix for rows

Core: canonical/shuffled/duplicated/cancellation-to-zero/empty rows,
stale VarId, bad pointers, invalid bounds, merged-overflow, atomic
rejection (no partial rows/slices/identities), snapshot-equality vs
scalar, packed commuting square (`tests/p1_rows.rs` + store unit tests).
Python: full suite incl. malformed-CSR/duplicate/all-or-none battery
unchanged and green (84 passed). CSR variants at 10k rows: canonical
3.5 / shuffled 4.4 / duplicated 4.1 ms.

## Behavior note (committed to CHANGELOG)

CSR rows with sub-`EPSILON` nonzero coefficients now drop exactly like
scalar-built rows (previously only exact zeros dropped on the CSR path).
Cancellation-to-zero and duplicate accumulation unchanged.

Raw: `after_p1_native.json`, `after_p1_python.json` (this directory).
