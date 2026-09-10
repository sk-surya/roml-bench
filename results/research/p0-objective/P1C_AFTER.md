# P1C-1 AFTER — packed array expressions → bulk rows

Implementation in ROML (`perf-p0-bulk-objective` branch, stacked, unmerged).
Idiomatic BESS300 source unchanged; only the representation between
operators and `m.add()` changed. No P1C-2 (parameterized dot), no name
changes, no snapshot work.

## Method

Release wheel of the P1C-1 worktree; pinned CPU 6; 3 reps. Breakdown
splits expression construction from `m.add()` insertion per group
(`/tmp/p1c_bess.py` recipe mirrors `roml_python_bulk` exactly).

## Gate verdicts (BESS300 idiomatic, medians)

| Phase | BEFORE (general arrays) | AFTER (packed) |
|---|---|---|
| vars | ~16 | ~16 |
| init expr / add | 0.1 / 0.1 | 0.1 / 0.1 |
| balance expr | ~17 | **0.2** |
| balance add | ~48 | **~7.2** |
| mode expr / add | 0.0 / ~9 | 0.0 / ~9 |
| objective expr (dot, general — P1C-2) | ~9 | ~9 |
| objective add | ~19 | ~19 |
| **total** | **~185–202** | **~60** |

| Gate | Target | Result |
|---|---|---|
| constraint-array construction + insertion | <35 ms | **~17 ms — PASS** (0.2 + 7.4 + 9) |
| idiomatic BESS300 total | <100 ms (desired <75) | **~60 ms — PASS both** |
| raw CSR unchanged | ~38 ms ± noise | **~35 ms — PASS** |
| zero semantic differences | exact | 87 passed + 1 env skip, incl. 7 packed locks + full CSR battery |

## Where the remaining ~60 ms goes

- objective (parameterized dot, general path): ~28 ms — the P1C-2 prize.
- element-name registration inside `m.add(balance/mode)`: ~3 ms per
  28.8k-row group (named vs unnamed: 8.9 vs 5.6 ms) — parked for P2.
- vars ~16 ms (eager names — parked), flatten + core bulk ~5 ms.

Raw CSR (~35 ms) vs idiomatic (~60 ms): gap closed from 5× to 1.7×
without touching syntax. The residual gap is exactly P1C-2 + names.

Raw: `after_p1c_bess.json` (3 reps, this directory).
