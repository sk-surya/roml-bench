# FINAL CERTIFICATION — P0 bulk-objective stack (perf-p0-bulk-objective)

- Candidate reviewed: `2a66b808b97540a3ddb8429c12b09894e4c1b32a`
  (branch `perf-p0-bulk-objective`, 11 commits ahead of baseline, not behind;
  `git merge-base 6062398 2a66b808` == `6062398`)
- Baseline: `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- Benchmark repo: `sk-surya/roml-bench`, branch `bench/model-build-v2-forensic`,
  frozen at `f9b45d3b55bef1238843116a027c3e6499ca606f`; certification evidence
  on bench review branch `review/p0-final-cert` (retarget-only commits
  `c402753`, `a2f016a` + this artifact; methodology untouched)
- ROML under final test (candidate + certification fixes, see §3):
  `9cea1642508693238562d1f1be2edb95bacaf488` (branch `review/cert-fixes`,
  pushed, never merged)
- Final forensic run: `results/runs/20260908T224657Z-ai90-a2f016a7`
  (profile `forensic`, 7 replicates; run-time fingerprint
  benchmark `a2f016a`, ROML `9cea164`)
- Host/toolchain: AMD Ryzen 9 9950X (32 logical), pinned CPU 6
  (`taskset -c 6`), process-isolated children, release builds;
  rustc/cargo 1.97.1; Python 3.13.14; PuLP 3.3.1 / Pyomo 6.10.1 /
  PyOptInterface 0.6.1 / highspy 1.15.1 / numpy 2.5.3 / scipy 1.18.1 —
  identical host family and package set to the prior forensic passes
  (competitor medians reproduce within noise: Pyomo sparse 1M 1045.5 vs
  1045.8; POI-scalar BESS300 129.4 vs 127.1 — run-to-run jitter +1–2%).
- Methodology: UNCHANGED from the frozen harness (data pre-generated
  outside the timer; `Model` creation excluded; timer = variables +
  constraints + objective phases; commit/snapshot excluded from the
  headline by design; 120 s / 16 GiB envelope). Only the pinned ROML SHA
  was retargeted (`d6afabd` → `9cea164` in `scripts/bootstrap.sh`,
  `src/roml_bench/schema.py`, `rust-core/Cargo.toml` + embedded consts).
- Arm taxonomy (no bare "ROML native"): ROML core scalar
  (`roml_core_rust[_anon]`, general modeling path), ROML core bulk
  (`roml_core_bulk`, documented bulk core API), ROML Python bulk/idiomatic
  (`roml_python_bulk`), ROML Python CSR (`roml_python_csr`, BESS ingestion
  only), Pyomo (`pyomo_python`), PyOptInterface scalar
  (`pyoptinterface_scalar`), PyOptInterface matrix (`pyoptinterface_python`),
  PuLP (`pulp_python`).

## 1. Verdict

**CERTIFIED — safe to merge**, subject to the normal (non-bypass) merge
sequence in §11. Two correctness defects found during certification are
fixed on `review/cert-fixes` with regressions and full revalidation
(§3); no other blockers; no optimization performed.

## 2. Provenance and surface audit

- 11 commits `6062398..2a66b808`: `49e4f14` (P0 bulk constant objective) →
  `9ddeb02` (P0.5 DeltaBatch/snapshot linearization) → `f9e89c8` (P1.5B
  packed-base+overlay store) → `d174d75` (P1A/P1B bulk rows) → `420d9fa`
  (P1C-1 packed array exprs) → `7a07f38` (P1C-2 phase 1 dot lowering) →
  `d6afabd` (P1C-2 packed parametric objectives) → `74a9b85` (P1D
  persistent lazy scalars) → `0fff552` (P1E sink classifier) → `10ffdbe`
  (P2A structural naming) → `2a66b80` (P2A view-ordinal fix).
- Diff surface: 29 files, +8667/−829. No submodule or workspace
  dependency changes. `cargo fmt --check` / `git diff --check`: clean.

### 2.1 Public Rust API changes (exhaustive)

Exactly ONE signature change (intentional, documented break):
- `Model::coefficient(CoeffId)`: `Option<&CoefficientData>` →
  `Option<CoefficientData>` (owned snapshot; packed-base cells have no
  per-cell record to borrow). Documented in `MIGRATION.md` ("Unreleased
  breaking changes"), `CHANGELOG.md`, and the method rustdoc.
  `CoefficientData` is unchanged and still public via
  `roml::model::coefficient::CoefficientData`; field reads work as before.

Additive only: `Model::set_linear_objective_bulk`,
`Model::add_linear_rows_bulk`, `Model::set_linear_objective_param_bulk`,
`ModelError::MismatchedBulkLengths`, `ModelError::MismatchedRowBlock`,
`ModelOp::SetObjectiveCells`, `ModelOp::SetObjectiveParamCells`,
`ModelOp::AddLinearRows`, `Change::BulkObjectiveCoefficients`,
`Change::BulkObjectiveParamCoefficients`, `Change::BulkLinearRows`,
`LinearRowBlock`, `ParamCoeffCell`, `ValueExpr::scaled_param`.
(`CoefficientIndex` churn is `pub(crate)`-only.)

Result: 1 intentional documented break, 15 additive, 0 unintentional
breaks. Minor non-blocking gap: `MIGRATION.md`'s additive list omits the
P1C-2 APIs (all covered in `CHANGELOG.md`).

### 2.2 Public Python API changes

None: no new `pyclass`/`pymethods`/exports (`__init__.py`, `_native.pyi`
unchanged); new `set_objective_*`/`insert_*` helpers are private Rust
methods. 147 passed / 2 legitimate skips on release-built wheels for
BOTH Python 3.14 and 3.13 (skips: highspy oracle absent; debug-only
namespace probe absent in release — both expected).

## 3. Review findings (with fixes)

### Finding 1 (Severity A — FIXED): lazy packed variable-index staleness

`CoefficientIndex::var_index` was built once and never invalidated, so
packed cells appended after the first `for_var` call were invisible to
later `remove_variable` cascades → orphaned live coefficients on removed
variables. Proven: bulk objective → remove var (builds index) → bulk rows
→ remove new-block var → `num_coefficients` 7, expected 6. Fix:
invalidate on both constant-base append paths + completeness assert in
`check_consistency` (locks the class via `validate_invariants`).

### Finding 2 (Severity A — FIXED): overlay propagation zero-clobber

`Model::apply_parameter_change` pre-wrote overlay cached values to `0.0`
before re-evaluation and skipped the restore on sub-`EPSILON` deltas →
silently zeroed canonical cached values (packed path and baseline were
correct). Proven: `0.1*p` overlay cell + value shift of `0.5*EPSILON` →
`objective_expression` read `0` instead of `~0.1`. Fix: read-only `get`
first (baseline semantics), write only on significant change.

Both fixed on `review/cert-fixes` (`9cea164`) with
`tests/certification_regressions.rs` (3 tests) and full revalidation (§5).
No other blockers. No optimization performed.

### Non-blocking observations (Severity C — recorded, code unchanged)

- Nested numeric scales fold in a different association order on the
  classifier fast path vs flatten (≤1 ulp; solves identically).
- Merged-overflow strictness: bulk canonicalization rejects merged-infinite
  sums the scalar combine keeps (safe direction; needs ~1e308 inputs).
- `DeltaBatch.functions` (unconsumed derived view) doesn't merge scalar
  `SetCell` terms for same-batch block rows; compiler/backends consume ops.
- Same-var/same-param zero-sum parametric bulk keeps one zero-scale cell
  where scalar keeps one zero-valued combined cell (same counts/values).
- Parked items confirmed still true and non-blocking: eager `ParamArray`
  namespace strings; large deliberately-scalar lazy trees carry transient
  sink memory; snapshot/general diagnostic paths slower than packed paths;
  negative slice steps unsupported.

## 4. Architecture review (by invariant — all verified from code)

A. Packed store: uniform overlay-first authority across all seven read
   paths; identity-preserving shadowing via arena repointing;
   generation-bumped removal (stale → `None`/typed); fresh identity on
   re-add. Clean except Findings 1–2 (fixed).
B. Bulk objectives: fresh-objective insertion; fused validate-before-mutate;
   duplicates → general fallback pre-mutation; near-zero drop matches
   `LinExpr::simplify`; parametric same-var/same-param sums, multi-param
   groups to overlay with the combined expression.
C. Bulk rows: shape→bounds→values→vars validation, pure per-row
   canonicalization, then identities + single journal entry. Empty/
   singleton/empty-interior rows probed. One intentional alignment:
   sub-`EPSILON` CSR coefficients now drop like scalar rows
   (CHANGELOG-noted).
D. Delta/snapshot/replay: 1:1 change→op mapping in journal order;
   snapshot from the unified iterator; compiler expands bulk ops with
   identical row-id order, origins, bounds folding, and WR-03 tracking;
   reference backend reaches identical end states (commuting-square tests
   + new mixed snapshot-completeness regression).
E. Lazy trees: `Arc`-shared immutable nodes; iterative flatten/teardown;
   `has_vars` nonlinearity rejection as before; `Sym×Sym→Gen` folding
   re-verified against siblings (`(p*x)*q`, `p*(p*(q*x))`, `2*(p*x)`,
   `-(p*x)`, `(p+q)*x`, shared-subtree cancellation) — all solve exactly.
F. Classifier: mixed/param-constant trees always take general `Affine`;
   `0*p`/non-finite scales degrade to general (safe direction).
G. Naming: structural reservations + reverse explicit index; canonical
   suffix parsing; constraint-name asymmetry preserved; atomic rejection.
H. Views: roots carry `ordinals: None` (sole root constructor verified);
   slices compose root ordinals; identity flows by `VarId` (view-of-view
   and multidim probes pass).

## 5. Correctness validation (gates — all on the final `9cea164` state)

- `cargo fmt --all -- --check`: clean. `git diff --check`: clean.
- `cargo clippy -p roml --all-targets -- -D warnings`: clean.
  (`--workspace --all-features` fails on PRE-EXISTING out-of-stack issues:
  `roml-highs` bundled/system exclusivity, `roml-xpress` build.rs
  `if_same_then_else` — untouched by this stack.)
- `cargo test -p roml --all-targets`: **1302 passed, 0 failed** (incl. 3
  new regressions + all P0–P2A suite files).
- Python release wheels (NOT editable), 3.14 + 3.13: **147 passed,
  2 skipped** each.
- `RUSTDOCFLAGS='-D warnings' cargo doc -p roml --no-deps`: clean.
- `cargo package --list -p roml`: 190 entries, no scaffolding leakage.
- Adversarial probes (release wheel): view-of-view/multidim identity +
  display, namespace collisions (index 0/len-1/len/huge, ugly spellings,
  cross-kind, zero-length), 20k deep chain (build 0.08 s, sink 0.00 s),
  shared-subtree cancellation, param nesting — all pass.

## 6. Solver semantic certification (HiGHS + reference, final code)

- 2-var LP across SIX spellings (scalar / lazy chain / packed
  `rm.sum`+`rm.dot` / CSR `add_linear_rows` / parameterized packed /
  general symbolic fallback): all exactly **9.0**.
- Parameterized build→solve→×1.1 update→resolve in ONE persistent session
  (9.0 → 9.9) agrees bit-for-bit with a fresh build at new values.
- Sparse 1k seeded: CSR-bulk vs scalar-row solves bit-agree
  (453.2793895337246).
- Bench validation gate at the final pin: **10/10 implementations `ok`**.
- Sole suite error (POI-matrix `duplicated` 100k HiGHS Status −1) is the
  identical competitor-side methodology event as the prior run.
- Prior timeout event (naive-chain sparse 300k >120 s) is GONE (308.8 ms).

## 7. Headline performance (final run `20260908T224657Z-ai90-a2f016a7`)

Medians of 7 (p25–p75 in brackets), total = populate timer
(vars+constraints+objective phases); peak RSS median.

### sparse_rows 1M (8 nnz/row; objective 1M ones)

| implementation | total ms | vars | constr | obj | peak RSS |
|---|---|---|---|---|---|
| ROML core bulk | 155.6 [153.8,156.6] | 75.9 | 33.6 | 45.0 | 463 MB |
| ROML Python bulk | 155.3 [154.3,156.2] | 54.5 | 53.9 | 46.8 | 626 MB |
| ROML core scalar | 1086.0 [1047.5,1111.4] | 71.5 | 431.4 | 582.2 | 1013 MB |
| ROML Python naive chain | 1155.0 [1146.4,1169.4] | 523.2 | 334.5 | 289.7 | 1146 MB |
| Pyomo | 1067.6 [1059.6,1078.2] | 461.3 | 483.1 | 122.3 | 486 MB |
| POI scalar | 1112.4 [1103.4,1184.4] | 909.5 | 150.5 | 52.8 | 497 MB |
| POI matrix | 1642.6 [1581.1,1680.2] | 1230.2 | 303.5 | 111.7 | 551 MB |
| PuLP | 2069.1 [2043.8,2134.8] | 1187.1 | 688.8 | 193.3 | 728 MB |

Matched ratios (total): Python/core-bulk **1.00×**; Python/fastest
competitor (Pyomo) **0.15× (6.9× faster)**; core-bulk/fastest **0.15×**.

### bess_96 B=300 (numeric prices; 28.8k vars class, 86.7k constraints)

| implementation | total ms | vars | constr | obj | peak RSS |
|---|---|---|---|---|---|
| ROML core bulk | 16.2 | 5.8 | 8.8 | 1.6 | 55 MB |
| ROML Python bulk (idiomatic) | 26.7 | 4.6 | 19.9 | 2.2 | 199 MB |
| ROML Python CSR | 25.7 | 5.3 | 17.9 | 2.5 | 207 MB |
| ROML core scalar | 97.0 [91.4,100.5] | 6.8 | 61.9 | 28.3 | 128 MB |
| POI scalar | 129.4 [128.8,133.1] | 68.0 | 58.3 | 3.6 | 179 MB |
| POI matrix | 217.2 [212.0,220.4] | 92.8 | 118.4 | 5.9 | 182 MB |
| Pyomo | 339.6 [338.3,374.4] | 41.1 | 198.3 | 100.7 | 213 MB |
| PuLP | 488.5 [480.4,491.2] | 117.5 | 305.5 | 65.0 | 231 MB |
| ROML naive chain | 175.8 | 27.5 | 107.5 | 40.6 | 258 MB |

Matched ratios (total): Python/core-bulk **1.65×**; Python/fastest
competitor (POI scalar) **0.21× (4.8× faster)**; core-bulk/fastest
**0.13× (8.0× faster)**. Python objective phase is now 2.2 ms vs
core-bulk 1.6 ms (was 20.5 vs 1.6 at `d6afabd` — the P1E classifier
removed the `dt*dot` materialization).

### Scaling snapshot (median totals, ms)

sparse_rows (Python bulk): 10k 1.6 / 100k 13.0 / 300k 43.2 / 1M 155.3 —
at parity with core bulk at every size (1.3 / 12.9 / 42.5 / 155.6):
matched interface overhead ≈ **1.0×** end to end.
bess_96 (Python bulk): B10 1.0 / B30 2.5 / B100 8.1 / B300 26.7 —
Python/core ≈ 2.0× / 1.8× / 1.6× / 1.65×.

### Historical before/after (same host + harness family)

- sparse 1M ROML Python: original baseline evidence ~1710 ms → **155 ms**.
- BESS300 ROML Python: original baseline evidence ~197 ms → **27 ms**.
- Same-harness `d6afabd`→`9cea164` (isolates P1D/P1E/P2A+fixes):
  BESS300 idiomatic 55.1→26.7, CSR 36.1→25.7, naive chain 4676.6→175.8;
  sparse 1M Python bulk 411.7→155.3 (RSS 727→626 MB),
  naive-chain 300k timeout→308.8 ms. Core-bulk and competitor arms
  reproduce within noise (core bulk 151.5→155.6 / 16.2→16.2; Pyomo
  1045.5→1067.6 / 335.1→339.6; POI scalar 1145.1→1112.4 / 126.6→129.4).
  Core scalar BESS 92.6→97.0 sits inside the new IQR [91.4,100.5]: noise.

## 8. Parameterized BESS diagnostic (final code, B=100, persistent session)

| spelling | build | solve1 | update ×1.1 | solve2 | obj1 | obj2 |
|---|---|---|---|---|---|---|
| packed-parametric (`rm.dot`) | 14.5 ms | 134.6 ms | 6.8 ms | 464.5 ms | 274603.166431452 | 302063.4830745966 |
| classified-param (lazy `p*x` chain) | 112.6 ms | 128.8 ms | 6.7 ms | 464.9 ms | identical | identical |
| general-symbolic (`(p+q)*x` chain) | 164.9 ms | 208.5 ms | 16.8 ms | 464.7 ms | identical | identical |

Objectives bit-identical across spellings; `obj2 == obj1 × 1.1`
exactly; all optimal. Semantics identical; only build/update speed
differs by path (packed fastest, general slowest — expected).

## 9. Documentation/claims audit

- CHANGELOG taxonomy is clean: P2A "1M vars ~330→70 ms" is the Python
  `m.vars` path (harness vars phase now 54.5 ms — consistent direction);
  P1E "1M scalar chain inserts ~81 ms" is the sink phase (implementation-
  measured; harness naive-chain 1M objective phase 289.7 ms covers chain
  build + sink together); P1D build figures are construction-labeled;
  P1A sub-`EPSILON` CSR alignment is code-verified.
- One wording looseness (non-blocking): P0 "duplicates fall back to
  algebraic combine" — the mechanism is fallback to the general path
  (which combines); outcomes verified identical by probe.
- Bench reports (`NATIVE_BULK_PARITY.md` + site): taxonomy explicit,
  matched-formulation comparisons, no diagnostic-chain-as-overhead claims
  (the 12.8× BESS objective ratio at `d6afabd` is itemized as interface
  work — and is now 1.4× after P1E).
- No unmatched-formulation Rust-vs-Python claims; no slower-ROM-arms
  omissions (core scalar + naive chain reported alongside bulk).

## 10. Known limitations (non-blocking) and post-merge opportunities

§3 observations + parked items; MIGRATION additive-list gap (§2.1);
P1D 1M-chain BUILD ~3.3 s remains (documented; sink is fast). Not started
per mission: parameter-name laziness, tree compaction, snapshot/journal
optimization, namespace unification, more bulk APIs.

## 11. Recommended merge sequence (normal process, no bypass)

1. Merge `perf-p0-bulk-objective` (`2a66b808`) to `main` via the standard
   PR + independent review (this certification is the review record).
2. Immediately merge `review/cert-fixes` (`9cea164`) to `main` (2 small
   correctness fixes + 3 regression tests; revalid
...[truncated 911 chars]