# P0 AFTER — bulk constant-objective insertion

Follow-up to `REPORT.md` + `COUNTERS.md` (research, BEFORE).
Implementation lives in ROML (`perf-p0-bulk-objective` branch, unmerged):
bulk core primitive + packed journal/delta op + Python packed handoff.
ROML itself was modified there; this repo holds only evidence + probes.

## Method

- Native: ROML `examples/bulk_objective_probe` (release, pinned CPU 5),
  same sparse recipe as `rust-core` (1M vars, 100k×10 rows, 1M-term
  objective). Scalar arm = BEFORE path; bulk arm = AFTER path.
- Python: `/tmp/p0_python_after.py` mirrors `roml_python_bulk` recipes
  exactly (CSR sparse + fused-dot BESS) against a release wheel of the
  P0 worktree. Formulation only (no solve), pinned CPU 6.
- BEFORE medians: forensic run `20260908T053319Z-ai90-14738229`
  (roml_python_bulk, n=7) and P0 research probes.

## Gate verdicts

| Gate | Target | AFTER | Verdict |
|---|---|---|---|
| sparse 1M native objective | <200 ms (stretch <100) | **~400 ms** (370/392/406/406) | MISS — residual is ~5 hash ops/term floor of the current store; needs P1.5 layout |
| sparse 1M Python total | beat 1.71 s, pref. <1.1 s | **1331 ms** (334+603+394) | materially beats ✓ / <1.1 s ✗ (blocked by parked eager names + P1 rows) |
| BESS300 Python | <150 ms (stretch <120) | **~202 ms** (18+137+47) | MISS by design — parameterized objective + array constraints untouched in P0 |
| identical snapshot / solve / delta replay | exact | proven (core equiv. tests + probe asserts + reference commuting square) | PASS |
| scalar + parameterized corpus unchanged | green | 75 core targets, roml-highs suites, 80 Python passed + 1 env skip | PASS |
| no deferred cost at commit()/sync | no explosion | bulk commit ≤ scalar at every scale; objective-attributable commit → ~0 | PASS |
| peak RSS | improve or neutral | 1015 → 1009 MB construction; journal 3.1M → 2.1M ops | PASS |

Python-overhead note: BEFORE Python objective exceeded native by 109 ms
(804 vs 695); AFTER by 18 ms (394 vs ~400 incl. host variance) — the
packed handoff removed the Python-side normalization almost entirely.

## Required BEFORE/AFTER table (sparse 1M, native core)

| 1M objective | BEFORE | AFTER |
|---|---|---|
| expression build | 12.8 ms | 0 (no expression) |
| simplify | 62.8 ms | 0 |
| validation + insertion | in `minimize` 618.3 ms | fused, in API total |
| objective API total | ~694 ms | **~400 ms** |
| commit() | ~60 min (extrapolated: rows-only 32 min measured + objective share) | ~32 min (= rows-only; objective share → ~0) |
| snapshot compile | ~258 s | ~258 s (path-independent; same canonical state) |
| peak RSS (construction) | 1015 MB | 1009 MB |

100k corroboration (fully measured): scalar commit 13.6 s vs bulk
5.8 s vs rows-only 5.7 s — objective-attributable commit 7.9 s → ~0.1 s.

## Dominant residual (pre-existing, out of P0 scope)

- `DeltaBatch` F2 function reconstruction is O(constraints × ops):
  100k rows-only commit 5.7 s → 1M rows-only **32 min measured**.
  Blocks all 1M solve flows regardless of P0; P1 must linearize it
  (output-preserving pre-grouping) or rows bulk must bypass it.
- `take_snapshot` ≈ 258 s at 2M cells (per-cell dep `Vec` allocs, fat
  sort, function reconstruction) — path-independent, P1.5 territory.
- Insert floor ≈ 250–300 ns/term (arena + 3 maps + 2 sets) — P1.5
  packed-base layout territory. The <100 ms stretch is unreachable
  without it; <200 ms needs it or a bulk row-store rethink.

Raw: `after_native_{bulk,scalar}_1m.json`, `after_native_100k.json`,
`after_python_{sparse,bess}.json` (this directory).
