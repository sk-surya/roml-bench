# Benchmark v2 — post-MIR ROML (report)

Status: **in progress** — populated from the committed authoritative run and the
persistence harness. Every number below is generated from machine-readable
artifacts; no value is hand-entered.

## Pins and environment

- `roml-bench` SHA: `5ffc9b35fd2f8ca5a9acc31c2b45355286dc1308` (branch `bench/v2-post-mir`)
- ROML SHA: `f1dc3e6df181b638623f59726bd03c15729d568e` (merged PR #71 dense-array fix)
- Canonical seed: `20260908`; Python 3.13.14; HiGHS 1.15.1; serial `-j 1`, one
  pinned logical CPU, `OMP/OPENBLAS/MKL/NUMEXPR/RAYON_NUM_THREADS=1`.
- Host: AMD Ryzen 9 9950X, Linux 7.0.0-31-generic, idle.

## Adapter audit (pre-run)

`.planning/ADAPTER-AUDIT.md` — every arm is CURRENT / LEGACY DIAGNOSTIC /
COMPETITOR; no arm used in publication is TODO. Stale v1 API usage was updated
before measurement (raw-L2 block-native; the legacy Rust scalar builder is a
LABELED diagnostic, not the Rust representative).

## Panels (kept separate)

1. **High-level formulation** — equivalent user-facing APIs (ROMl Rust L1,
   ROML Python vectorized, Pyomo, PuLP, PyOptInterface scalar, JuMP,
   OR-Tools MathOpt). `bess_96`.
2. **Matrix ingestion** — CSR/matrix APIs only (ROML Python CSR, ROML
   bulk raw L2 diagnostic, PyOptInterface matrix). Never mixed with (1).
3. **ROML abstraction tax** — ROML-only (`param_bess` B=300): raw L2, Rust L1,
   Python Model, Python ConcreteModel+labels.
4. **Indexed rules** — `rule_rows` (1k/10k/100k): ROML Rust `add_indexed_rules`,
   ROML Python rules, Pyomo indexed rule.
5. **Dynamic / persistent** — direct update vs `Template.bind` vs competitor
   rebuild paths (labeled).

## Authoritative run

- Run id: _(filled from the run)_; profile `standard`; 7 replicates.
- Validation: `roml-bench validate` ok for all participating arms.

## Headline values

_(filled from `summary.json` + persistence artifact.)_

## Superseded v1 claims

- v1 “350× binding overhead” stays retracted (it measured O(n²) chaining).
- v1 BESS leaderboard stays withdrawn (preassembled CSR vs algebra).
- v1 ROML SHAs are historical; v2 is measured on `f1dc3e6`.
