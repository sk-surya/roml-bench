# State

## Objective

Complete model-building benchmark v1: Python ROML vs PuLP/Pyomo/PyOptInterface; Python ROML vs native ROML core; generate offline HTML report; serve it on LAN/Tailscale.

## Current state

- Planning: complete
- Implementation: Tasks 1-6 complete (bootstrap, workloads, Python adapters,
  Rust core runner, validation gate, isolated orchestrator)
- Validation: passing for all 6 implementations (sparse 0.0, bess B=1
  651.993846 across all 5 Python solvers; Rust core counts verified)
- Quick profile: methodology bug caught and fixed (BESS CSR row order);
  re-run pending
- Authoritative benchmark run: not started
- Site generation: not started
- Network service: not started

## Locked decisions

- ROML source baseline: `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- Workloads: `sparse_rows`, `bess_96`
- Primary timed metric: `populate_ms`
- Standard run: 7 replicates, 120 s hard child timeout, 16 GiB child RSS ceiling
- Canonical run seed: `20260908`
- Site: static Jinja2 + offline Plotly
- Serve port: `8787`

## Next gate

Task 7 in `.planning/IMPLEMENTATION-PLAN.md`: statistical summarizer.

## Stop condition

Stop only when `.planning/IMPLEMENTATION-PLAN.md` Task 12 passes and `.planning/FINAL-REPORT.md` records a running site and authoritative benchmark evidence.
