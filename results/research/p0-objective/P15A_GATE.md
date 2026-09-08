# P1.5A prototype gate — packed coefficient store

Prototype only; no ROML changes. Code: `rust-store-proto/` (this repo).
Runner: `store-proto --kernel <a|b|c> --n <cells>` (release, pinned CPU,
one process per kernel for clean VmHWM). Workload is identical across
kernels (seeded xorshift): 1M constant objective cells (`(i%97)+0.5`),
100k random lookups, full iteration with checksum, 10k removes +
10k updates (half re-parameterized).

## Kernels

- **A** — verbatim copy of the current P0 topology (`CoefficientIndex` +
  `IdArena`, import-rewritten to `roml::`, visibility lifted; diff is
  mechanical only) built via `add_constant_unique_block`. Baseline.
- **B** — approved spec: `IdArena<CellLocation>` identity, packed
  `vars[]/values[]/coeff_ids[]` + target slice/directory + shadow/dead
  bitsets, sparse overlay (`by_cell`, per-var/per-target/per-param delta
  lists), lazy global var index (unbuilt in the timed runs — none of the
  gate ops needs it), parameterized cells in overlay only.
- **C** — raw packed arrays, positional IDs, no arena (known gaps: no
  generations/stale detection; update-in-place without invalidation).

## Results (1M cells, release)

| kernel | build | lookup 100k | iterate 1M | remove/update 20k | peak RSS |
|---|---|---|---|---|---|
| A | 283–321 ms | ~19 ms | ~8.7 ms | ~11.5 ms | 349 MB |
| B | **7–9 ms** | ~27 ms | ~5 ms | ~12 ms | **112 MB** |
| C | 7–8 ms | ~15 ms | ~4.5 ms | ~3.5 ms | 111 MB |

Checksums identical across kernels (53360124.0); live-after identical
(990,000); sampled read-back assertions (update identity preserved,
removal visible, parameterized shadow readable) pass in-run; 15 unit
tests green (ported A tests + B semantics incl. lazy index + tombstones).

## Gate verdict

- Storage construction <100 ms required, <50 ms desired → **B at
  7–9 ms: PASS by ~13×/~6×.**
- B ≈ C on build (7.3 vs 7.2, noise) → **retain the identity arena**
  per the decision rule. C's mutate edge (0.4 µs/op) is irrelevant at
  sparse-mutation rates and costs stale-ID safety. No ID redesign on
  intuition — measurement settles it.
- Lookups trade hash probes for binary search + one overlay probe
  (269 ns vs 196 ns): fine for rare post-build mutation, as designed.
- RSS 349 → 112 MB (3.1×): the forest of per-var hash sets is gone.

## Production projection (honest deltas, not promises)

B's 7 ms is storage only. A production 1M bulk objective still pays the
Model-layer fused validation scans (finite + liveness + uniqueness,
order ~80–100 ms today), one packed journal entry (~10 ms scale), and
unchanged snapshot/commit paths. Projected full operation ≈ ~100 ms —
at the target boundary. The next structural saving after conversion is
the validation scans (e.g. verified-sorted fast path), not the store.

## Design points confirmed for P1.5B

1. Rows must be canonicalized by VarId (prototype asserts sorted input
   in debug). CSR rows may arrive unsorted — P1.5B needs a measured
   canonicalization step, not an assumption.
2. Tombstone records join the overlay delta lists (flag-filtered); a
   later re-add needs no list surgery and mints fresh identity via the
   arena — unit-tested, matches current remove→add semantics.
3. `for_var` reverse-mapping is a linear slice scan per hit in the
   prototype; acceptable for rare use, revisit only on profiling.
4. Parameterized cells live in the overlay from day one; no
   `CoefficientValue` redesign needed.

## Stop

No ROML conversion performed — P1.5B production cutover awaits explicit
trigger. Suggested first slice when triggered: port `CoefficientIndex`
behavioral tests unchanged, then swap the store behind them.
