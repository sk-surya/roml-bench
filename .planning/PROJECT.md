# ROML Benchmark — Model-Building v1

## Objective

Build a reproducible, publication-quality benchmark suite in `sk-surya/roml-bench` that measures **model construction time as problem size grows** and produces an offline static HTML report that can be served on the local network or Tailscale.

The first benchmark milestone answers two questions only:

1. How does the current ROML Python modeling API compare with PuLP, Pyomo, and PyOptInterface for equivalent LP model construction workloads?
2. How much overhead remains between ROML Python and ROML native Rust core for the same mathematical construction work?

Do not expand this milestone into solve-time, incremental-update, extraction, warm-start, or solver-quality benchmarking. Those are later milestones.

## Source baseline

The baseline ROML source is pinned to:

- repository: `sk-surya/roml`
- commit: `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- significance: merge of PR #53, the completed PyO3 + maturin Python interface

Never benchmark a moving `main` implicitly. Every result must identify the exact ROML SHA and benchmark-repository SHA.

Initial Python comparison pins for the first authoritative run:

- Python: 3.13.x (ROML Python requires >=3.13)
- PuLP: 3.3.1 stable
- Pyomo: 6.10.1 stable
- PyOptInterface: 0.6.1 stable

Resolve supporting dependencies with `uv` and commit `uv.lock`. The generated report must display the actually installed versions. If an exact initial pin proves incompatible with the host, use the newest compatible stable release, document the deviation in `.planning/DEVIATIONS.md`, and keep the lockfile exact thereafter. Do not use prereleases unless required and explicitly documented.

## Benchmark thesis

The benchmark must distinguish two kinds of comparison instead of collapsing them into one misleading number:

### A. Python user-facing construction

Compare the documented, efficient public modeling path of each Python library. The primary chart is the elapsed construction API time from an empty model through variables, constraints, and objective installation. Imports, benchmark-data generation, solver solution time, serialization, and report generation are excluded.

This is intentionally a user-observable API benchmark, not a claim that all libraries share the same internal architecture. In particular, PyOptInterface is a thin direct wrapper around an optimizer model while ROML/PuLP/Pyomo have different deferred/in-memory boundaries. The methodology page must state that distinction prominently.

### B. ROML binding overhead

Compare mathematically identical ROML construction paths:

- `roml_python_scalar`
- `roml_python_bulk`
- `roml_core_rust`

The scalar-vs-scalar comparison isolates Python/binding/modeling overhead most cleanly. The bulk-vs-core comparison answers the practical user question: how close can the public Python fast path get to native core construction?

## End state

The milestone is complete only when all of the following exist and pass:

- deterministic canonical workload generators
- Python adapters for ROML, PuLP, Pyomo, and PyOptInterface
- a native Rust ROML-core benchmark runner
- structural/equivalence validation outside the timed path
- process-isolated benchmark orchestration with raw immutable results
- environment/provenance capture
- summary/statistical derivation from raw measurements
- polished offline HTML pages with interactive charts and raw-data links
- reproducible quick and standard benchmark profiles
- tests and CI smoke coverage that do not performance-gate on noisy CI
- an authoritative standard run committed under `results/runs/<run-id>/`
- generated `site/` from that run
- a user-level service serving `site/` on a non-loopback interface
- final report containing the reachable LAN URL and, when available, Tailscale URL

## Architecture

Use one canonical workload/data layer and thin library-specific adapters. Adapters only translate the already-generated mathematical data into each library's public API. A Python orchestrator executes one implementation/size/replicate per child process, captures timing and resource data as JSON, and never parses human-formatted stdout as the source of truth.

The native Rust runner implements the same workload formulas and emits the same result schema. A summarizer consumes only raw JSON records and produces derived summaries. A static site generator consumes those summaries and produces a fully offline `site/`; the web server is deliberately simple and separate from benchmark execution.

## Non-goals

- No solver-performance ranking.
- No objective-quality ranking.
- No commercial solvers.
- No changing ROML implementation to improve benchmark numbers inside this repo.
- No hand-selected exclusions after seeing results.
- No hiding failures/timeouts/OOMs.
- No benchmark claims based on CI runners.
- No remote telemetry or CDN dependency for the generated site.

## Decision rules

- Prefer reproducibility over a larger benchmark matrix.
- Prefer two structurally different workloads over many toy variants.
- Primary figures use measured medians; raw replicates remain downloadable.
- Any speedup claim must compare paired workload/size points completed by both implementations.
- If one implementation hits the standard-profile stop condition, do not extrapolate its curve.
- If results contradict the expected ROML advantage, publish them unchanged and investigate separately.
