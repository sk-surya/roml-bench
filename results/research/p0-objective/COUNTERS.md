# P0 counter table — 1M constant objective (sparse_rows, N=1,000,000)

All ROML citations are `roml@6062398b418c4bc0c7718b2ce569da8b9e42766e`
(read-only inspection; ROML itself is unmodified).
Workload: 1M variables, 100k × 10-coefficient rows, then
`minimize(LinExpr{1.0*x_i})` with all-unique variables and a zero constant.

## Derived internal counts (exact for this controlled input)

| # | Counter | Count | Derivation |
|---|---|---:|---|
| 1 | terms | 1,000,000 | workload definition (`obj_coeff` all ones) |
| 2 | `LinExpr::simplify` calls | 1 | one call per `compile_for_objective` (`src/expr/linear.rs:212`) |
| 3 | simplify terms scanned | 1,000,000 | `simplify` consumes all terms (`linear.rs:162`) |
| 4 | `validate_expression_entities` calls | 1 | `add_objective_spec` (`linear.rs:688`) |
| 5 | terms validated | 1,000,000 | loop over `expr.terms` (`src/model/mod.rs:1929`) |
| 6 | `validate_value_expr_parameters` calls | 2,000,000 | N via validation (`mod.rs:1942`) + N via `add_objective_coefficient` (`mod.rs:2527`) |
| 7 | `ValueExpr::dependencies()` calls | 3,000,000, **all constant (empty)** | 2M from row 6 (`mod.rs:1960` iterates the returned set) + 1M new-cell `by_param` indexing (`src/model/coefficient.rs:183`); receiver is `Constant(1.0)` every time (`src/value_expr/mod.rs:166`) |
| 8 | cell-key lookups | 2,000,000 | N `for_cell` (`mod.rs:2537` → `coefficient.rs:397`) + N `by_cell.get` on the new-cell path (`coefficient.rs:125`) |
| 9 | coefficient arena allocations | 1,000,000 | one `arena.allocate` per new cell (`coefficient.rs:166`) |
| 10 | `by_var` inserts | 1,000,000 entry/insert pairs | `coefficient.rs:170`; in THIS workload the sets pre-exist (rows phase created one set per var), so 0 fresh sets — ordering-dependent (see note) |
| 11 | `by_objective` inserts | 1 map entry + 1,000,000 set inserts | `coefficient.rs:178`; one set, grows by rehashing |
| 12 | `by_cell` inserts | 1,000,000 | `coefficient.rs:188` |
| 13 | `by_param` inserts | 0 | all dependency sets empty (row 7) |
| 14 | `Change::CoefficientAdded` pushes | 1,000,000 | new-cell branch (`mod.rs:2570`); each clones a `Constant` `ValueExpr` (no heap) |
| 15 | other changelog pushes | 2 | 1 `ObjectiveAdded` (`mod.rs:2140`) + 1 `ActiveObjectiveChanged` (`mod.rs:2171`); `ObjectiveConstantChanged` is correctly **absent** (0.0 == initial, EPSILON check `mod.rs:2220`) |
| 16 | heap-allocating dependency sets | 0 | `HashSet::new()` + zero inserts never allocates |

Corroboration (measured, counting run, same code path): the 1M
`minimize` performs **63 allocator calls** total — consistent with rows
10–12 being rehash-only growth (~18 rehashes each for `by_objective` set,
`by_cell` map, and the internal `simplify` map) plus ~8 changelog-`Vec`
growths plus entry overhead. No per-term allocation exists in the constant
path; the cost is per-term CPU (hashing + cloning + pushing), not
per-term allocation.

Note on row 10: the sparse workload builds rows before the objective, so
`by_var` sets already exist at capacity ≥3 and absorb the second insert
without reallocation. A standalone objective-first ordering would show
~1M extra small-set allocations. A bulk path must handle both orderings.

## Control: 100k constant vs parameterized (single shared `Param(p)`, p=1.0)

| # | Counter | Constant | Parameterized | Source |
|---|---|---:|---:|---|
| 17 | `dependencies()` content | empty | `{p}` (1-elem set, heap-allocating) | `value_expr/mod.rs:166` |
| 18 | extra allocator calls in `minimize` | 0 | ≈300,000 (= 3N) | measured: 53 vs 300,055 calls |
| 19 | `by_param` inserts | 0 | 100,000 into one shared set | `coefficient.rs:183` |
| 20 | `simplify` path | constant `HashMap` combine | `expr_terms` Vec (no map) | `linear.rs:166` |
| 21 | insert wall time | 53.5 ms | 59.1 ms | measured (counting run; timing-runner medians 51.4 vs 49.9 ms — within noise) |

Reading: the parameter machinery is real (≈3 heap-allocating
`HashSet`s per term, one `by_param` insert per term) but costs only
≈56 ns/term (≈10%) on top of a ≈535 ns/term base both modes share.
Constant-specialization alone cannot win P0; bulk insertion attacks the
shared base. The control also proves the fast path must preserve
parameter semantics rather than assume them away: identical mathematics
(all coefficients evaluate to 1.0 — see `parameterized_objective_matches_constant_values` test) takes a measurably different index path.
