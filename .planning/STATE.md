# State

## Objective

Complete model-building benchmark v1: Python ROML vs PuLP/Pyomo/PyOptInterface; Python ROML vs native ROML core; generate offline HTML report; serve it on LAN/Tailscale.

## Current state

- Planning: complete
- Implementation: Tasks 1-10 complete (bootstrap through CI gate)
- Validation: passing for all 6 implementations
- Quick profile: 72/72 ok; methodology bug (BESS CSR order) caught and fixed
- Authoritative benchmark run: starting (standard profile)
- Site generation: generator verified on quick data
- Network service: user systemd available, linger enabled; install pending

## Locked decisions

- ROML source baseline: `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- Workloads: `sparse_rows`, `bess_96`
- Primary timed metric: `populate_ms`
- Standard run: 7 replicates, 120 s hard child timeout, 16 GiB child RSS ceiling
- Canonical run seed: `20260908`
- Site: static Jinja2 + offline Plotly
- Serve port: `8787`

## Next gate

Task 11 in `.planning/IMPLEMENTATION-PLAN.md`: authoritative standard run
and publication.

## Stop condition

Stop only when `.planning/IMPLEMENTATION-PLAN.md` Task 12 passes and `.planning/FINAL-REPORT.md` records a running site and authoritative benchmark evidence.
