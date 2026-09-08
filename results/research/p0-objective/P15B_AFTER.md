# P1.5B AFTER — packed coefficient store

Follows `P15A_GATE.md` (prototype verdict: B wins, retain arena).
Implementation in ROML (`perf-p0-bulk-objective` branch, stacked, unmerged).
Only gate rerun here: **1M native constant objective**, broken down as
required, plus Python formulation totals and RSS.

## Required breakdown (sparse 1M, release, pinned CPU)

| 1M objective | BEFORE (P0 store) | AFTER (packed store) |
|---|---|---|
| Model validation (fused finite/liveness/unique) | in 410 ms API | in 43.7 ms API |
| ID/duplicate validation | in API (uniqueness HashSet) | in API (same) |
| store construction | ~390 ms (5 hash ops/term) | **6.8 ms** (release in-crate probe; prototype predicted 7–9) |
| journal construction | 1 push (µs) | 1 push (µs) |
| objective API total | ~410 ms (370–410) | **43.7 ms** (35–44 across reps) |
| commit() | ~32 min (= rows-only) | **221 ms** (with P0.5 linearization) |
| snapshot compile | ~258 s (pre-P0.5 path) | **507 ms** (with P0.5 linearization) |
| peak RSS | construction 1015 MB | construction **714 MB**; post-commit 1432 MB (journal still holds per-cell row ops — P1 rows) |

Scalar general path on the new store: 601 ms total (was ~694 ms) —
the overlay path is no slower than the old topology.

## Gate verdicts

- storage component <25 ms → **6.8 ms: PASS**.
- full objective <120 ms required → **43.7 ms: PASS**; <100 ms desired → **PASS**.
- RSS materially below ~1 GiB → construction 1015 → 714 MB PASS;
  post-commit peak still 1.4 GB, dominated by per-cell ROW journal
  entries (unchanged P1 scope — rows still journal per cell).
- semantic corpus exact → 77 core targets (incl. ported store tests +
  10 adversarial equivalence tests), roml-highs suites, 80 Python +
  1 env skip: all green.
- No validation optimization performed (unnecessary at 44 ms).

## Python formulation (release wheel, pinned CPU)

- sparse 1M total: 1710 (pre-P0) → 1331 (P0) → **~890 ms**
  (vars ~350 + rows ~512 + objective ~38). The P0 <1.1 s stretch goal
  falls as a side effect.
- BESS300: ~202 → **~185 ms** (constraint path slightly faster on the
  new store; objective unchanged and parameterized by design).

## What was NOT done (per scope)

No CSR rows, no `CoefficientValue` redesign (parameterized cells stay
overlay-only), no validation fast paths, no row-store generalization
beyond multi-slice directory support already present. The one
mechanical test adaptation: two lines in the ported `by_var_index`
test (`for_var` returns an owned `Vec` — laziness requires `&mut`;
documented in place).

Raw: `after_p15b_native.json`, `after_p15b_python.json` (this directory).
