# Benchmark-v2 adapter / API-currency audit

Gate: no authoritative public run is accepted until every arm below is either
current, relabelled, or retired. The committed adapters predate MIR-04–08, so
continuity with v1 is **not** a reason to keep stale API usage. Historical v1
results already provide continuity.

Status legend: **CURRENT** (no change) · **UPDATED** (this tranche) ·
**STALE → TODO** (must be fixed before measurement) · **COMPETITOR**.

| Benchmark arm | Public/internal API | Current ROML API? | Formulation vs ingestion | Parameterized? | Expected lowering path | Justification / action |
| --- | --- | --- | --- | --- | --- | --- |
| `roml_core_bulk` | `add_variable_array_block` + `add_linear_rows_bulk` + `set_linear_objective_bulk` | **UPDATED** (vars are block-native; stale "no variable-bulk primitive" claim removed) | ingestion / **internal lower bound** | no (numeric) | packed variable-block op → bulk CSR rows → bulk objective | The raw L2 denominator for the abstraction-tax panel. Never a public competitor. Still to do: exercise parameter blocks / packed parametric objective where the fixture is parameterized. |
| `roml_core_rust` | `add_variable` + `add_constraint` (scalar builder) | **LEGACY DIAGNOSTIC** | formulation (internal) | no | scalar journal path | Historical scalar path only. Do not headline; not the Rust representative in competitive formulation plots. |
| `roml_core_rust_anon` | scalar builder, anonymous | **LEGACY DIAGNOSTIC** | formulation (internal) | no | scalar journal | Named-vs-anon diagnostic only. |
| `roml_core_l1` | `model.var(..).bounds(..).build()`, `model.param(..)`, slicing/array algebra, `add_row`, `maximize_array` | **CURRENT** (item 2 done) | formulation | **yes** (BESS prices are a first-class parameter) | shared L1 `LinArray` → packed rows → packed objective | Current idiomatic Rust construction arm and the Rust representative for formulation + parameterized panels. Full canonical BESS counts verified (B=1/3/300); normalized ordinal+journal fingerprints identical to an equivalent Python `Model` construction. |
| `roml_python_vectorized` | sparse: `Model.vars` + `add_linear_rows`; bess: `Model.vars` + array `Model.add` + fused `rm.dot` over a **dense numeric** `price_grid` | CURRENT (validate lowering) | **ingestion for sparse, formulation for bess** | **no** | shared `LinArray` → dense numeric coefficient family → **packed numeric** objective | Keep the efficient public path. Not a parameterized objective; item 8 exists to exercise parameter dependencies. Must not appear in the sparse *formulation* panel (item 5). |
| `roml_python_naive_chain` | `var` + `total = total + v` chaining | CURRENT (disclosed pathology) | formulation (diagnostic) | no | O(n²) scalar accumulation | Disclosed diagnostic only; never a binding-overhead claim. |
| `roml_python_csr` | `Model.vars` + `add_linear_rows` from shared CSR | CURRENT | **ingestion** (bess only) | no | packed CSR rows | Matrix/CSR ingestion; never headline vs algebraic formulation (item 5). |
| `roml_python_rules` | `Model.vars` + `add_indexed_rules` over `x[i, :]` | **CURRENT** (item 3 done) | formulation | no | one packed `BulkMixedRows` commit | `rule_rows` fixture; validated ok (counts + objective agreement). |
| `roml_core_rules` | `Model::add_indexed_rules` | **CURRENT** (item 3 done) | formulation | no | one packed mixed-row commit | `rule_rows` fixture; validated ok (counts; packed commit). |
| `pulp_python` | `add_variable_dicts` + `lpSum` | COMPETITOR | formulation | no | — | Compare only under equivalent semantics. |
| `pyomo_python` | `ConcreteModel` + indexed `Constraint` rules + `quicksum` | COMPETITOR | formulation (indexed rules) | no | — | Natural comparator for the rules arm; now also runs `rule_rows` (validated ok). |
| `pyoptinterface_python` | `add_m_variables` + matrix constraints | COMPETITOR | ingestion | no | — | Ingestion panel only. |
| `pyoptinterface_scalar` | scalar `add_variable` + `ExprBuilder` rows | COMPETITOR | formulation | no | — | Formulation panel only. |
| `jump_julia`, `ortools_mathopt_cpp` | JuMP / OR-Tools MathOpt | COMPETITOR | formulation | no | — | Kept as-is. |

## Parameterized-construction / ergonomics family (`param_bess`, ROML-only)

Fixture: B batteries × T=96; `price[b,t]` parameters, `charge`/`discharge`
variables, `maximize sum(price * (discharge - charge))`; sizes (1, 10, 300).
Serves item 8 (parameterized construction) and item 6 (ConcreteModel ergonomics).

| Arm | API | Status | Lowering evidence |
| --- | --- | --- | --- |
| `roml_core_bulk_param` | `add_variable_array_block` + `add_parameter_array_block` + `set_linear_objective_param_bulk_with_layout` | **CURRENT** | `general_affine=0`, `param_dep_blocks=2`, `param_positions_cells=0` |
| `roml_core_l1_param` | `var(..).build()` + `param(..)` + `maximize_array` | **CURRENT** | `general_affine=0`, `param_dep_blocks=2`, `param_positions_cells=0` |
| `roml_python_param` | Python `Model` parameter arrays + packed `rm.sum` | **CURRENT** | validated; objective agrees |
| `roml_python_concrete` | `ConcreteModel` + `RangeSet` axes + labeled vars/params + array algebra | **CURRENT** (item 6) | identical objective + canonical equivalence to `roml_python_param` |

`param-evidence` (rust-core bin) prints the packed-dependency lowering counters
and fingerprints for the two core arms; both match exactly
(`ordinal=8311104305927858589`). Item 6's primary number is
`roml_python_concrete median / roml_python_param median`.

## Additional ROML-only measurements to add (non-competitive)

| Measurement | Arms | Purpose |
| --- | --- | --- |
| Persistent update (item 7) | direct `Model` + params + `update`; `Template.bind`; rebuild path | Report convenience-layer overhead of `Template.bind` vs direct update; never silently pick the faster one. Separate build / update / sync / solve / end-to-end. |

## Rules of the audit

- One chart = one coherent comparison; formulation and ingestion panels stay
  separate, and raw L2 never appears beside competitor public APIs.
- Every added/updated arm must pass `roml-bench validate` (structural counts +
  cross-solver objective agreement) before its timing is published.
- Competitor arms are compared only where their public API supports the same
  workload semantics.
- No arm is added or changed to improve a ROML number; stale arms are updated
  for API currency, and any resulting performance change is reported honestly.
