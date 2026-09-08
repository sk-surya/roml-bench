# State

## Objective

Complete model-building benchmark v1: Python ROML vs PuLP/Pyomo/PyOptInterface; Python ROML vs native ROML core; generate offline HTML report; serve it on LAN/Tailscale.

## Current state

- Planning: complete
- Implementation: Tasks 1-3 complete (bootstrap, workloads, Python adapters)
- Validation: not started
- Authoritative benchmark run: not started
- Site generation: not started
- Network service: not started

## Evidence (2026-09-08)

- `uv sync` resolves Python 3.13 with pulp 3.3.1, pyomo 6.10.1,
  pyoptinterface 0.6.1, highspy 1.15.1; `uv.lock` committed.
- ROML wheel built from `.cache/roml` at 6062398b418c4bc0c7718b2ce569da8b9e42766e
  via maturin release; `import roml` reports 0.1.0.
- `ruff check .` clean; `pytest` 22 passed (workloads, schema, adapter smoke).
- Commits: 29721fd (bootstrap), 4083900 (workloads), 0aead47 (adapters).

## Locked decisions

- ROML source baseline: `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- Workloads: `sparse_rows`, `bess_96`
- Primary timed metric: `populate_ms`
- Standard run: 7 replicates, 120 s hard child timeout, 16 GiB child RSS ceiling
- Canonical run seed: `20260908`
- Site: static Jinja2 + offline Plotly
- Serve port: `8787`

## Next gate

Task 4 in `.planning/IMPLEMENTATION-PLAN.md`: native ROML core runner.

## Stop condition

Stop only when `.planning/IMPLEMENTATION-PLAN.md` Task 12 passes and `.planning/FINAL-REPORT.md` records a running site and authoritative benchmark evidence.
