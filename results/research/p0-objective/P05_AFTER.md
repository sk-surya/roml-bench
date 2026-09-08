# P0.5 AFTER — projection linearization

Follows `P0_AFTER.md`. Implementation in ROML (`perf-p0-bulk-objective`
branch, stacked on the P0 commit, unmerged): one-pass aggregation for
`DeltaBatch` F2 function reconstruction (`src/delta.rs`) and snapshot
semantic-function reconstruction (`src/snapshot.rs`). Output format and
semantics identical; no new public API; no cache/second authority.

## Method

Native probe `bulk_objective_probe` (release, pinned CPU 5):
`rows` arm = rows-only `commit()` (isolates DeltaBatch reconstruction);
`snapshot` arm = `take_snapshot()` on the sparse model. BEFORE measured
pre-change on the same binary recipe; AFTER post-change.

## Scaling (the gate)

| N (rows×10) | rows-commit BEFORE | AFTER | snapshot BEFORE | AFTER |
|---|---|---|---|---|
| 10k×10 | 34.7 ms | **1.8 ms** (19×) | 12.9 ms | **2.9 ms** (4.4×) |
| 50k×10 | 799 ms | **12.5 ms** (64×) | 271 ms | **21.3 ms** (12.7×) |
| 100k×10 | ~5700 ms | **26.1 ms** (218×) | ~1090 ms | **39.5 ms** (28×) |

| Gate | Target | Result |
|---|---|---|
| rows-only 100k commit | <2 s (stretch <1 s) | **26 ms — PASS (38× inside stretch)** |
| 100k snapshot | <2 s (stretch <1 s) | **39.5 ms — PASS (25× inside stretch)** |
| scaling | approximately linear | commit 1.8→12.5→26.1 (6.9×, 2.1×); snapshot 2.9→21.3→39.5 (7.3×, 1.9×) — linear within hash-growth noise |
| exact snapshot equality | identical outputs | 6 output-lock tests (parameterized corpus, add→update→remove, sparse IDs) green before AND after |
| exact DeltaBatch.functions equality | identical | same locks + commuting-square suites unchanged, green |
| parameterized cells in corpus | included | `param * 2.0`, `param + 1.0` symbolic forms asserted exactly |
| add→update→remove same batch | tested | add→bounds-fold→update→remove→exclusion asserted exactly |
| sparse/non-dense IDs | tested | indices 7/57/1001, cons 7/900/100 |
| no semantic cache | none | groups are function-local temporaries; authority unchanged (coefficient index) |

## Residuals (not P0.5 scope)

- Per-cell dependency `Vec` allocs in `Model::take_snapshot`'s cell
  collection remain (linear, small share at 100k).
- `take_snapshot`'s debug-only cross-check loop stays quadratic in
  debug builds by design (compiled out in release); release gates
  unaffected.
- 1M commit/snapshot re-measurement left for the full forensic rerun;
  at current scaling rows-only 1M commit projects to ~3 s (was 32 min).

Raw: `after_p05_scaling.json` (this directory).
