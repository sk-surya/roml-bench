# State

## Objective

Complete model-building benchmark v1: Python ROML vs PuLP/Pyomo/PyOptInterface; Python ROML vs native ROML core; generate offline HTML report; serve it on LAN/Tailscale.

## Current state

- Planning: complete
- Implementation: Tasks 1-11 complete (bootstrap through authoritative run)
- Validation: passing for all 6 implementations
- Authoritative benchmark run: `20260908T042228Z-ai90-64615d6c` (533 records,
  532 ok + 1 timeout), summarized, inspected, committed with site
- Site generation: `site/` generated from the authoritative run, offline
  (bundled Plotly), committed
- Network service: `roml-bench-site.service` active; localhost, LAN, and
  Tailscale URLs verified via curl

## Locked decisions

- ROML source baseline: `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- Workloads: `sparse_rows`, `bess_96`
- Primary timed metric: `populate_ms`
- Standard run: 7 replicates, 120 s hard child timeout, 16 GiB child RSS ceiling
- Canonical run seed: `20260908`
- Site: static Jinja2 + offline Plotly
- Serve port: `8787`

## Current state

- v1: authoritative run + site committed; PR #1 draft, unmerged (headlines
  withdrawn after owner review)
- Forensic pass: implementation + forensic run
  `20260908T053319Z-ai90-14738229` (793 records) + v2 site committed;
  validation green for all 9 arms
- Network service: `roml-bench-site.service` active, serving v2 site

## Stop condition

Stop only when `.planning/IMPLEMENTATION-PLAN.md` Task 12 passes and `.planning/FINAL-REPORT.md` records a running site and authoritative benchmark evidence.
