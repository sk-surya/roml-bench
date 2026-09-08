# P0 research report — constant 1M objective

Research-only; no ROML changes (all work in `roml-bench`,
branch `bench/model-build-v2-forensic`). Timing evidence: `roml-bench-core`
release, pinned CPU 4, `roml@6062398b`. Counting evidence: `roml-ops-probe`
(counting global allocator; its timings are NOT authoritative). Raw records:
`timings.jsonl` (15, all schema-valid), `probes.jsonl` (3), `environment.json`.
Method detail: `COUNTERS.md`. Host: AMD Ryzen 9 9950X, 59 GiB RAM,
rustc 1.97.1.

## 1. Release microbenchmarks (authoritative)

sparse_rows, named, medians:

| N | vars | constraints (N/10 rows × 10) | objective (N terms) | total |
|---|---:|---:|---:|---:|
| 1,000,000 (n=3) | 72.0 ms | 523.8 ms | **694.7 ms** | ~1291 ms |
| 100,000 (n=5) | 7.3 ms | 38.7 ms | 51.4 ms | ~96 ms |

Context: 1M anon objective 650.9 ms (n=1); BESS-300 core 107.9 ms
(vars 6.9 + constraints 68.4 + objective 32.2). Peak RSS at 1M: ~1.0 GiB
(after: 1032 MiB named, 998 MiB anon). This reproduces the forensic
premise on this host: the native-core 1M objective (~650–695 ms) is the
single largest phase, and it is not a Python artifact.

## 2. Objective sub-phase split (counting run, 1M constant)

| Sub-phase | Time (indicative) | Allocator calls | Bytes allocated |
|---|---:|---:|---:|
| expression build (1M `term` pushes) | 14.2 ms | 19 | 64.0 MiB |
| standalone `simplify` (throwaway copy) | 66.2 ms | 40 | 162.5 MiB |
| `minimize` insertion (validates + re-simplifies + 1M inserts) | 645.5 ms | 63 | 412.0 MiB |

## 3. Attribution of objective cost

For the 1M constant objective (≈726 ms counting-run scale):

- **Expression build ≈ 2%.** One `Vec` push per term; negligible.
- **`simplify` ≈ 10%.** One 1M-entry `HashMap<VarId, f64>` build
  (66 ms standalone, 40 rehash allocs, 162 MB churn) — paid twice in
  effect (standalone measurement + the identical map rebuilt inside
  `minimize`), but even once is a tenth of the phase.
- **Validation ≈ 5–10% (estimated).** One linear scan: per term an
  `eval` (constant → copy), two arena-`contains` checks, and one empty
  `dependencies()` construction. No isolated hook exists (private
  method); bounded by subtracting the measured simplify from the
  insert residual and by the per-term rate math below.
- **Per-term indexed insertion + journaling ≈ 80–85%.** Per term:
  `eval`, `validate_value_expr_parameters` (2nd `dependencies()`),
  `for_cell` + `by_cell` lookups, arena slot, `by_var`/`by_objective`
  entry + set inserts, canonical-expr clone, `Change::CoefficientAdded`
  push — i.e. the full general-purpose mutation stack, 1M times, for
  inputs that are all unique constants. Effective rate ≈ 580–650 ns/term.

Supporting evidence:

- The insert performs only 63 allocator calls for 1M terms (rehash
  growth + changelog-`Vec` growth); the disease is per-term CPU over
  hot hash indexes, not per-term allocation — except in the
  parameterized mode, where 3 heap-allocating 1-elem `HashSet`s per
  term add ≈300k allocator calls per 100k terms (measured).
- 100k parameterized vs constant: identical mathematics, insert time
  within noise (timing-runner medians 49.9 vs 51.4 ms), +10% in the
  counting run. Base machinery ≈ 535 ns/term shared; parameter content
  ≈ +56 ns/term. A constants-only fast path that keeps the per-term
  stack would save ~10% at best.
- Scaling is slightly superlinear (100k→1M: 10× terms, ~13.5× time),
  consistent with hash-index rehash growth — a bulk reserve-once build
  removes exactly this.
- Memory: ~1 GiB peak at 1M is retained structure (1M arena cells +
  1M `by_cell` entries + 1M-entry `by_objective` set + 1M `by_var`
  sets + 1M changelog entries), not transient churn. The bulk journal
  entry (one semantic operation vs 1M `CoefficientAdded`) addresses
  both time and retained memory on the write path; the index layout
  itself is the later P1.5 question, untouched here.

## 4. What this gates

- The P0 bulk-objective design is confirmed in the efficient order:
  **bulk insertion first** (collapses validation + indexing +
  journaling per term — the ~90%), **constant specialization second**
  (removes the ~10% dependency/by_param content and its allocator
  churn). Constant-specialization alone is insufficient by measurement.
- API lock remains open per instruction, but evidence constrains it:
  the winner must (a) validate finite/ID inputs in bulk scans, (b)
  reserve index/changelog storage once, (c) build `by_var` /
  `by_objective` / `by_cell` without per-term hashing where inputs are
  known-unique (with a combining fallback preserving the canonical-cell
  invariant), (d) journal one bulk semantic operation replayable by
  existing delta/sync consumers, (e) route the parameterized control
  through the same bulk path with `by_param` built once.
- Parked (re-measured, not blocking): eager variable names (72 vs
  43 ms at 1M vars, ~40% of var phase, ~2% of total), scalar chaining,
  row layout.

## 5. Reproduction

```
cargo build --release -p roml-bench-core --offline
./scripts/p0_research.sh   # pins CPU 4 (override P0_CPU), writes this directory
```

`validate` gate untouched (new `objective_mode` field defaults to
`constant`; all emitted timing records pass `validate_record`).
No publication, no merges, no ROML modification.
