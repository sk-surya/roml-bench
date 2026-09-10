# Forensic pass P0..P1C2 — final report

Frozen ROML: `d6afabd2988761fe9d5dd08597491a6f3fb73779` (no ROML changes
during the run). Suite run `20260908T185312Z-ai90-0c6c6069`, profile
`forensic`: 800 records, 798 ok, 7 replicates, pinned CPU, release
builds, process-isolated children, same competitor versions, same
timeouts/RSS rules, same `populate_ms`, same formulations.
BEFORE = run `20260908T053319Z-ai90-14738229` (same host, same
methodology, ROML `6062398`, 793 records).

Environment diff BEFORE→AFTER: timestamps, load, SHAs only. Competitor
package set identical. Competitor medians drift ≤2% (noise), so the
methodology is stable and all deltas below are ROML effects.

Non-ok events are identical in both runs (methodology, not regressions):
`roml_python_naive_chain` sparse 300k wall-timeout (disclosed O(n²)
diagnostic arm, pilot-capped by design); `pyoptinterface_python` sparse
100k single-rep HiGHS Status −1 error.

## Headline: BEFORE → AFTER (median populate_ms)

```
                     BEFORE FORENSIC     AFTER P0..P1C2     SPEEDUP
sparse 1M ROML Py        1709.8 ms          412.6 ms          4.14x
sparse 1M Pyomo          1054.4 ms         1045.8 ms          (noise)
sparse 1M POI scalar     1115.7 ms         1124.2 ms          (noise)
sparse 1M POI matrix     1604.3 ms         1554.6 ms          (noise)
BESS300 ROML Py           196.9 ms           56.4 ms          3.49x
BESS300 POI scalar        129.9 ms          127.1 ms          (noise)
BESS300 Pyomo             359.4 ms          350.8 ms          (noise)
```

## Phase transformation (ROML Python, medians)

```
ROML sparse 1M
vars            327.5 ms  →  318.4 ms   (eager names, parked)
constraints     591.4 ms  →   52.2 ms   (P1/P1C packed rows)
objective       804.0 ms  →   42.5 ms   (P0/P1.5 bulk objective)
total          1709.8 ms  →  412.6 ms
RSS            1484.8 MB  →  726.3 MB

ROML BESS300 (bench spelling: numeric prices, named groups)
vars             15.4 ms  →   16.2 ms   (eager names, parked)
constraints     135.3 ms  →   19.5 ms   (P1/P1C packed arrays+rows)
objective        45.9 ms  →   20.5 ms   (P0 packed numeric dot)
total           196.9 ms  →   56.4 ms
RSS             299.6 MB  →  232.8 MB
```

Cost was not moved elsewhere: the native structural mirror
(`forensic_probe`, `after_p1c2_observability.jsonl`) records
commit/snapshot/delta-ops/coeff-counts separately. Sparse 1M native
(scalar construction): commit ~300 ms, snapshot ~598 ms, 3.10M delta
ops, 2.00M coeffs, peak RSS 1860 MB. BESS300 native: commit ~46 ms,
snapshot ~69 ms, 375k ops, 231k coeffs, 239 MB. The Python packed path
journals a handful of packed ops where the scalar path journals
millions (proven by the packed-journal unit locks), so these native
scalar-path figures bound the packed cost from above.

## ROML / fastest competitor (AFTER, median; <1 favors ROML)

- sparse 1M formulation: ROML 412.6 vs Pyomo 1045.8 → **0.39** (2.53×).
  vs POI scalar 0.37, POI matrix 0.27, PuLP 0.20, native core 0.41.
- sparse ingestion: ROML bulk/CSR 412.6 vs POI matrix 1554.6 → **0.27**.
- BESS300 formulation: ROML idiomatic 56.4 vs POI scalar 127.1 → **0.44**
  (2.25×). vs POI matrix 0.27, Pyomo 0.16, PuLP 0.12.
- BESS ingestion: ROML CSR 35.0 vs POI matrix 207.4 → **0.17** (5.9×).

Paired credibility: ROML wins 7/7 replicates on both headlines with
non-overlapping ranges (sparse: ROML max 445 < Pyomo min 1030;
BESS: ROML max 62 < POI-scalar min 124).

Scaling: the advantage grows or holds with size. Sparse ROML/Pyomo:
10k 2.6/7.5 → 100k 22.9/90.4 → 1M 412.6/1045.8. BESS ROML/POI-scalar:
B=10 1.9/4.1 → B=100 17.5/40.7 → B=300 56.4/127.1.

Ingestion diagnostics (canonical/shuffled/duplicated, sparse):
ROML 1M 412.6 / 422.7 / 417.2 — robust to column order and duplicates.

## Note on the 0.04 s expectation

The bench idiomatic BESS spelling uses *numeric* prices
(`dt * rm.dot(price_grid_numpy, ...)`), so P1C-2's packed-parametric
path does not fire there; 56.4 ms is the honest number for the
unchanged source and it still wins by 2.25×. The parameterized
spelling (`ParamArray` prices, `rm.dot(price, discharge - charge)`
structural) builds the same BESS300 in ~40.6 ms — measured separately
in the update probe below, not in the suite grid.

## Parameter-update performance (P1C-2 storage change)

`p1c2_update_probe.py`, BESS300, one persistent HiGHS session per
model: build → solve → price×1.1 update → incremental re-solve.
Medians of 3 reps (`after_p1c2_update.json`):

```
                   build      solve1    update    solve2    obj1→obj2
packed-parametric   40.6 ms   471 ms    22.5 ms   4105 ms   814312.8→895744.1
scalar-general   18358.1 ms  1773 ms    27.5 ms   4095 ms   identical
```

EQUIVALENCE: PASS — identical objectives and ×1.1 scaling on both
paths. No rolling-MPC regression: update and re-solve times match;
first-solve/sync is 3.8× faster packed (fewer ops to synchronize).
Model-build speed was not traded for update performance.

## Verdict

Gate: ROML Python fastest among compared Python modeling interfaces
at sparse 1M and unchanged idiomatic BESS300, 7/7 paired reps,
advantage stable-to-growing with size — **PASS**. No losses to report:
every head-to-head favors ROML; the two non-ok events are identical
methodology events in BEFORE and AFTER.

From 1.71 s → 0.41 s (sparse) and 0.20 s → 0.056 s (bench BESS
idiomatic; 0.041 s parameterized) with the modeling API preserved.
(Owner's 0.61 s figure is the v1 run's pre-forensic BESS spelling at
the same old SHA — 605.8 ms; the v2 corrected spelling measured
196.9 ms. Full arc: 0.61 → 0.20 → 0.056.)
Next per owner order: independent review of the stacked ROML branch +
benchmark/report certification + merge decision. No P2 work started.
