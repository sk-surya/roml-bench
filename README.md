# ROML Model-Build Benchmark v1

Reproducible benchmark of **model construction time vs problem size** for
ROML Python vs PuLP / Pyomo / PyOptInterface, and ROML Python vs native
ROML Rust core.

Normative documents:

- `.planning/PROJECT.md`
- `.planning/BENCHMARK-CONTRACT.md`
- `.planning/IMPLEMENTATION-PLAN.md`

## Quick start

```bash
./scripts/bootstrap.sh
uv run roml-bench validate
uv run roml-bench run --profile quick
uv run roml-bench summarize results/runs/<run-id>
uv run roml-bench site results/runs/<run-id>
uv run roml-bench serve --host 0.0.0.0 --port 8787 --directory site
```

## Parallel execution

```bash
uv run roml-bench run --profile quick -j 8
uv run roml-bench run --profile standard --jobs 16
uv run roml-bench run --profile forensic -j 1
```

`-j 1` (the default) is the canonical serial timing mode: one benchmark
child at a time, pinned to the first allowed CPU. Use it for any
publication-quality comparison or historical timing.

`-j N` with N > 1 is throughput mode: up to N benchmark children run
concurrently, each pinned to a distinct CPU from the process affinity
set (refused clearly when N exceeds the available CPUs). Replicate,
pilot-cap, stopping, and result-ordering semantics are unchanged, and
each child keeps its own wall-timeout and RSS ceiling.

Parallel timings must not replace serial forensic evidence: concurrent
children share LLC, memory bandwidth, boost/thermal headroom, and NUMA
effects, so individual latencies may shift. Pick `-j` so aggregate
memory fits the machine — per-child RSS ceilings are NOT divided by
jobs (8 children at 16 GiB each can theoretically need far more than
16 GiB total). Runs record `jobs`, `cpu_pool`, and `timing_class`
(`canonical_serial` vs `parallel_throughput`) in `run.json`.

## Layout

- `src/roml_bench/` — workloads, adapters, orchestration, validation, site generator
- `rust-core/` — native ROML core benchmark runner (release build)
- `results/runs/<run-id>/` — immutable raw results + derived summaries
- `site/` — generated offline static report
