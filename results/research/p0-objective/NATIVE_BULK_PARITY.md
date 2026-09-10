# Native-bulk parity — correcting the ROML native-vs-Python comparison

Benchmark branch: `bench/model-build-v2-forensic`, this commit (see log).
Benchmark HEAD before changes: `23cadc7` (clean tree, recorded).
Frozen ROML under test: `d6afabd2988761fe9d5dd08597491a6f3fb73779`
(clean tree, verified; zero ROML modifications in this task).
Suite run: `20260908T192754Z-ai90-a645d57f`, profile `forensic`
(891 records, 889 ok, 7 reps).

Host: ai90, AMD Ryzen 9 9950X, pinned CPU per child, process-isolated
children, release builds. rustc 1.97.1, Python 3.13.14,
PuLP 3.3.1 / Pyomo 6.10.1 / PyOptInterface 0.6.1 / highspy 1.15.1 /
numpy 2.5.3 — identical to the prior forensic pass. Competitor medians
reproduced within noise (Pyomo sparse 1M 1045.8 vs 1045.5; POI-scalar
BESS300 127.1 vs 126.6), so the harness is stable. The two non-ok
events are the same methodology events as BEFORE (naive-chain 300k
timeout; one POI-matrix 100k HiGHS error).

## Losses and surprises first

None against competitors: every head-to-head still favors ROML, and no
ROML defect was found. Two observations, both disclosed rather than
optimized:

1. The new proof initially FAILED on BESS (`snapshots_equal`,
   `constraints_equal`, `constraint_cells_equal`). Root cause:
   benchmark-proof artifact — the scalar builder inserts rows
   interleaved per battery while the bulk builder inserts per group,
   so raw ConIds allocate differently and id-keyed map comparison
   cannot match. Rewrote the proof allocation-independently (row
   multisets, snapshot function/set multisets); green on both
   workloads. Per the regression rule: benchmark defect, documented,
   minimum correction, ROML untouched.
2. BESS Python-objective / core-bulk ratio is 12.8× (20.5 vs 1.6 ms).
   This is interface work the bench spelling requires (`dt * dot`
   materializes 57.6k terms, then scalar insertion), not hidden
   deferred work — itemized in the audit below. The CSR objective
   ratio, where both sides stay packed, is 1.69×.

## Arm taxonomy (use these labels; retire bare "ROML native")

- ROML core scalar (`roml_core_rust[_anon]`) — general modeling path.
- ROML core bulk (`roml_core_bulk`) — NEW, documented bulk core API.
- ROML Python bulk / idiomatic (`roml_python_bulk`).
- ROML Python CSR (`roml_python_csr`, BESS ingestion only).

The legacy core-scalar benchmark is slower than the optimized Python
bulk interface because they exercise different core APIs. The matched
native-bulk arm is the appropriate baseline for Python-interface
overhead. Historical forensic numbers are immutable and retained.

## Timing-boundary parity audit (Step 0 record)

Primary boundary identical for all arms: data pre-generated outside
the timer (`make_case` / `--prices-csv` built by the orchestrator);
`Model` creation excluded (`container_init_ns`); timer = variables +
constraints + objective phases; commit/snapshot excluded (diagnostics
only); 7 reps, pinned CPU, 120 s / 16 GiB envelope.

sparse_rows (`roml_python_bulk` vs `roml_core_bulk`): variables —
`vars("x", n)` vs scalar `add_variable` loop, same `x[i]` names and
bounds, no delta. Constraints — Python parses the pre-generated CSR
(+`rows[i]` names) and inserts via `add_linear_rows`; native derives
the identical CSR buffers from the same deterministic pattern inside
the timer and inserts via one `add_linear_rows_bulk`. Objective —
both reach `set_linear_objective_bulk` (all-ones, Minimize, 0.0).

bess_96: variables — same flat `base[i]` names and bounds. Constraints
— Python 3× `m.add` (init/balance/mode) vs native 3×
`add_linear_rows_bulk` over the same groups/rows/bounds. Objective —
same ±dt·price values in the same discharge-block-then-charge-block
order into `set_linear_objective_bulk` (Maximize, 0.0); Python pays
one materialization the native arm never needs (interface work under
test, itemized above).

Fairness: no variable-bulk primitive invented (none exists); no store
mutation, private arrays, fabricated ids, or hand-built journals —
only public `Model::` APIs; no input preassembly beyond what the
contract pre-generates. The ONE structural delta: bulk rows take no
names, so Python's row-name registration (~1.3 ms/100k rows, measured
3.6 vs 2.3 ms at 100k, linear) has no native counterpart. Disclosed.

## Headline table (median populate_ms, 7 reps)

```
                         populate_ms    vs core bulk
Sparse 1M
ROML core scalar              1066.2          7.04x
ROML core bulk                 151.5          1.00x
ROML Python bulk               411.7          2.72x
Pyomo                         1045.5          6.90x
POI scalar                    1145.1          7.56x
POI matrix                    1590.9         10.50x
PuLP                          2032.5         13.42x
BESS300
ROML core scalar                92.6          5.72x
ROML core bulk                  16.2          1.00x
ROML Python idiomatic           55.1          3.40x
ROML Python CSR                 36.1          2.23x
POI scalar                     126.6          7.81x
POI matrix                     212.3         13.10x
Pyomo                          335.1         20.69x
PuLP                           469.4         28.98x
```

## Component tables (median ms / MB, 7 reps)

```
Sparse 1M              vars   constraints   objective   total   RSS
core scalar            72.0      413.0        575.6    1066.2  1012.9
core bulk              76.3       31.8         42.8     151.5   463.0
Python bulk           318.8       49.6         44.3     411.7   727.0

Python / core-bulk: vars 4.18, constraints 1.56, objective 1.04,
total 2.72, RSS 1.57.
```

The sparse objective ratio is 1.04 — same primitive, ~zero interface
overhead. The Python cost is variables (4.18×: eager element names +
per-var handles — parked P2-names territory) then constraints (CSR
parsing + row names). Scalar-vs-Python must never again be called
binding overhead; Python-vs-bulk is the overhead.

```
BESS300                vars   constraints   objective   total   RSS
core scalar             7.2       60.5         26.1      92.6   128.2
core bulk               5.7        8.7          1.6      16.2    54.8
Python idiomatic       15.5       19.5         20.5      55.1   232.7
Python CSR             15.0       18.6          2.7      36.1   215.6

Python-idiomatic / core-bulk: vars 2.72, constraints 2.24,
objective 12.81 (materialization, see §Losses), total 3.40, RSS 4.25.
Python-CSR / core-bulk: vars 2.63, constraints 2.14, objective 1.69,
total 2.23, RSS 3.93.
```

## Observability (bulk construction; `after_native_bulk_probe.jsonl`)

Per-arm commit/snapshot/delta-op/coeff/RSS diagnostics (probe, 3 reps,
pinned CPU, single-model runs; suite peak-RSS in the component tables
above remains authoritative). Sparse 1M bulk: commit ~90 ms, snapshot
~457 ms, 1,000,004 delta ops (1M `AddVariable` + 4: rows, objective
cells, objective, activation — the 100k rows ride one packed op),
2.0M coeffs. Scalar same size: commit ~288 ms, snapshot ~596 ms,
3.10M ops. BESS300 bulk: commit ~10 ms, snapshot ~60 ms, 86,706 ops;
scalar: ~44/~67 ms, 375,302 ops. Equiv proof attached to every probe
record: bulk≡scalar replay equality + snapshot equality on all sizes
(the validation gate runs it on validation sizes).

## Parametric diagnostic (native vs Python packed-parametric)

Native `bess_96_param` probe (`after_native_param.jsonl`, canonical
prices): 57,600 `scale·param` cells built via
`set_linear_objective_param_bulk` (~110 ms including scalar structure
rows), cells exactly `scale·price` to the digit (e.g. 18.1224069755022
= 0.25 × 72.4896279020088); ×1.1 update propagates to all 57,600
cells in ~19 ms with exact ×1.1 values. Python side
(`after_p1c2_update.json`, prior evidence): packed-parametric and
scalar-general spellings solve identically (814312.8 → 895744.1) with
matching update/re-solve times. Construction parity (exact cell
values), update parity (exact ×1.1 on all cells), solve parity
(identical objectives) — no rolling-MPC regression from the packed
parametric store.

## Validation and test evidence

`cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D
warnings`, benchmark pytest (51 passed, 1 skipped), suite validation
`ok` (all 11 implementations incl. `roml_core_bulk` counts/schema,
bulk-vs-scalar replay proof, Python solve agreement),
`git diff --check`, clean worktree. Raw records:
`results/runs/20260908T192754Z-ai90-a645d57f/raw.jsonl`.

## Confirmation

ROML source untouched (frozen `d6afabd`, verified clean). No
competitor, timing-definition, workload, or historical-result changes.
No merge. No P2. No snapshot optimization.
