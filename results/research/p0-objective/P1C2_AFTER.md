# P1C-2 AFTER — packed parametric objectives end-to-end

Implementation in ROML (`perf-p0-bulk-objective` @ `d6afabd`, stacked,
unmerged). Idiomatic BESS300 source unchanged
(`rm.dot(price_grid, discharge - charge)` stays structural). Two parts:
phase 1 structural dot lowering + shared eval snapshot (`7a07f38`),
phase 2 core `set_linear_objective_param_bulk` + `Scalar::PackedSymbolic`
(`d6afabd`). No name changes, no snapshot work.

## Method

Release wheel of the P1C-2 worktree; pinned CPU 6; 5 reps
(`/tmp/p1c2_bess_param.py`: MPY-style BESS300 with `ParamArray` prices,
plus update + persistent re-solve per rep).

## Gate verdicts (BESS300 parameterized idiomatic, steady-state reps 1–4)

| Phase | BEFORE (P1C-1, general dot) | AFTER (packed-symbolic) |
|---|---|---|
| vars + naming | ~17 | ~17 |
| constraints (init/balance/mode) | ~15–17 | ~15–17 |
| dot construction | ~1.4 | **0.2** |
| objective insertion (maximize) | ~36–38 | **~6.1** |
| **construct total** | **~72–80** | **~40** |
| parameter update (28.8k) | ~39–43 | ~26–30 |
| persistent re-solve | ~7.3–8.6 s | ~4.5–4.6 s (noise/thermal, same optimum) |

| Gate | Target | Result |
|---|---|---|
| parameterized dot construction | <2 ms | **0.2 ms — PASS** |
| objective insertion total | <15 ms required, <10 desired | **~6.1 ms — PASS both** |
| idiomatic BESS total | <45 ms required (≈35–40 desired) | **~40 ms — PASS required, edge of desired** |
| raw CSR no regression | ~35 ms | **~56 ms probe total, path untouched — PASS*** |
| parameter update + persistent solve | no regression | **improved (update −30%), identical optimum 895744.1 — PASS** |
| zero semantic differences | exact | 341 native + 105 Python green, incl. 6 native param-bulk + 14 symbolic-dot locks |

\* The raw-CSR probe (`/tmp/p1c2_csr_probe.py`, numeric prices) totals
~56 ms including ~10–12 ms of probe-side NumPy CSR assembly and eager
variable naming; the ROML CSR path (`add_linear_rows`, numeric dot,
bulk objective) is byte-untouched by P1C-2 — no code on that path
changed, and the CSR/objective arms measure 26 + 0.2 + 1.8 ms.

## Where the remaining ~40 ms goes

- vars ~17 ms (eager names — parked, per P1C-2 stop rule).
- constraints ~16 ms (bulk insertion — P1/P2 scope).
- objective ~6 ms (packed parametric base + reverse index build).
- The primary modeling-performance architecture is now: fast structured
  base + fully general sparse overlay, for both constants and parameters.

Raw: `after_p1c2_bess.json` (5 reps, this directory).
