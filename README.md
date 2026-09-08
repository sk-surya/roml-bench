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

## Layout

- `src/roml_bench/` — workloads, adapters, orchestration, validation, site generator
- `rust-core/` — native ROML core benchmark runner (release build)
- `results/runs/<run-id>/` — immutable raw results + derived summaries
- `site/` — generated offline static report
