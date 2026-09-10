# Benchmark Contract

This document is normative for model-building benchmark v1. If implementation convenience conflicts with this contract, change the implementation, not the contract. Any unavoidable deviation must be recorded before interpreting results.

## 1. Workloads

### 1.1 `sparse_rows`

Purpose: isolate primitive linear-model construction overhead with fixed sparsity.

For size parameter `N`:

- continuous variables: `x[0:N]`
- bounds: `0 <= x_i <= 5`
- rows: `R = floor(N / 10)`
- each row `r`: `sum(x[10r + k] for k=0..9) <= 10`
- objective: `min sum_i x_i`

Expected structure:

- variables: `N`
- constraints: `floor(N / 10)`
- constraint nonzeros: `10 * floor(N / 10)`
- objective nonzeros: `N`

Standard size grid:

`1_000, 3_000, 10_000, 30_000, 100_000, 300_000, 1_000_000`

Quick profile:

`1_000, 10_000`

### 1.2 `bess_96`

Purpose: exercise realistic indexed linear algebra with narrow temporal coupling and a large objective.

Constants:

- periods `T = 96`
- `dt = 0.25`
- round-trip leg efficiency parameter `eta = 0.95`
- power limit `P = 2.0`
- energy limit `E = 4.0`
- initial energy `E0 = 2.0`
- deterministic price vector of length 96 generated once per run from the canonical workload generator and shared across implementations

For `B` batteries:

Variables per battery:

- `charge[t]`, `t=0..95`, `0 <= charge <= P`
- `discharge[t]`, `t=0..95`, `0 <= discharge <= P`
- `energy[t]`, `t=0..96`, `0 <= energy <= E`

Constraints per battery:

- `energy[0] == E0`
- `energy[t+1] == energy[t] + dt * (eta * charge[t] - discharge[t] / eta)`
- `charge[t] + discharge[t] <= P`

Objective:

`max dt * sum_t price[t] * (discharge[t] - charge[t])`

Expected structure for `T=96`:

- variables: `B * (3T + 1) = 289B`
- constraints: `B * (2T + 1) = 193B`
- constraint nonzeros: `B * (1 + 6T) = 577B`
- objective nonzeros: `2BT = 192B`

Standard battery grid:

`1, 3, 10, 30, 100, 300`

Quick profile:

`1, 10`

Do not introduce ROML mutable parameters in this v1 workload. This milestone is model construction, not parameter-update capability.

## 2. Implementations and modes

Required implementation IDs:

- `roml_python_bulk`
- `roml_python_scalar`
- `pulp_python`
- `pyomo_python`
- `pyoptinterface_python`
- `roml_core_rust`

### Python primary/idiomatic track

Use each library's documented efficient public API while preserving the workload mathematics and semantic naming. Do not intentionally force competitors through known slow paths.

- ROML: shaped/bulk public API where available (`vars`, array expressions, CSR/bulk rows as appropriate).
- PuLP: efficient supported linear-expression helpers rather than repeated immutable expression rebuilding when a faster documented helper exists.
- Pyomo: indexed variables/constraints and efficient linear summation/expression construction.
- PyOptInterface: documented matrix/bulk APIs when supported by the HiGHS model in the pinned release; otherwise use `ExprBuilder`/efficient scalar construction. Record the exact path in site methodology.

### Common scalar diagnostic track

`sparse_rows` must also run a common scalar construction diagnostic for ROML Python and, where practical, the Python competitors. The scalar track is secondary and must not replace the idiomatic primary chart.

### ROML Python vs core

Both `roml_python_scalar` and `roml_core_rust` must create the same variables, constraints, coefficients, bounds, objective, and naming policy. This is the cleanest language/binding-overhead comparison.

`roml_python_bulk` vs `roml_core_rust` is the practical public-fast-path comparison and must be presented separately from scalar-vs-scalar.

## 3. Naming policy

Use semantically equivalent names across implementations.

- `sparse_rows`: base variable family `x`; individual unique names where a library requires them.
- `bess_96`: families `charge`, `discharge`, `energy`.

Do not disable names only for libraries where names are optional if another compared library necessarily materializes them. If a library lazily renders indexed names by design, document that architectural difference rather than adding artificial string work.

## 4. Timed boundary

Primary metric: `populate_ms`.

The timer starts immediately before the first variable is inserted into an already-created empty model/container and stops immediately after the objective is installed.

Excluded from `populate_ms`:

- Python/Rust process startup
- imports and dynamic library loading
- creation of canonical coefficient/data arrays
- random-number generation
- package-version detection
- report logging
- model validation
- solver optimization
- model export or serialization
- HTML generation

Measure `container_init_ms` separately where meaningful. Derive `user_build_total_ms = container_init_ms + populate_ms`, but the main scaling chart uses `populate_ms` so fixed constructor/backend-startup costs do not obscure scaling.

Important semantic disclosure: PyOptInterface's model is solver-backed and its population calls may insert directly into HiGHS, while other libraries can maintain a separate modeling representation. Do not describe `populate_ms` as identical internal work. Describe it as elapsed user-facing construction API work under each library's architecture.

## 5. Canonical input rule

Workload data must be generated once outside the timed region from deterministic seeds and passed to every adapter. No adapter may generate coefficients, prices, sparsity, or index sets inside the timed region except trivial index iteration needed to call the library API.

Canonical seed for v1 authoritative run: `20260908`.

## 6. Validation gate

No performance point is publishable until its implementation has passed validation for that workload family.

Validation is outside the timed path and requires:

1. expected variable count
2. expected constraint count
3. expected objective term count where introspection permits it
4. expected constraint nonzero count where introspection permits it
5. bound/domain spot checks
6. deterministic small-instance solve check with HiGHS and objective agreement within `1e-7 absolute + 1e-7 relative`

Where a library lacks reliable public introspection for a count, record that field as `unavailable`; never fabricate it. The shared workload generator plus independent objective solve check remains mandatory.

Validation failures block publication for that implementation/workload until fixed. They are not silently skipped.

## 7. Process isolation and ordering

Every measured replicate runs in a fresh child process. Process startup is outside the internal timer.

For each implementation/size child:

1. import dependencies
2. apply thread-limiting environment
3. generate/read canonical input outside timing
4. perform a tiny unrecorded warmup construction to settle lazy initialization
5. create the empty target model and record `container_init_ms`
6. start timer
7. populate full target model
8. stop timer
9. report one machine-readable JSON record
10. exit

The orchestrator randomizes implementation order within each workload/size/replicate using the run seed to reduce time-drift bias.

## 8. Runtime controls

Set, where relevant:

- `OMP_NUM_THREADS=1`
- `OPENBLAS_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `NUMEXPR_NUM_THREADS=1`
- `RAYON_NUM_THREADS=1`

On Linux, pin child processes to one logical CPU when possible using the current allowed affinity mask. Record the chosen CPU. If affinity cannot be set, continue and record `cpu_affinity=null`.

Do not use sudo to change CPU governor or kernel settings. Record CPU model, governor when readable, load average, kernel, memory, Python version, Rust version, package versions, benchmark SHA, ROML SHA, and timestamp.

## 9. Replicates and stop policy

Quick profile:

- 3 measured replicates per point
- no point may exceed 15 seconds

Standard profile:

- 7 measured replicates per point while median pilot/build remains <= 60 seconds
- hard per-process wall timeout: 120 seconds
- hard child RSS ceiling: 16 GiB

If an implementation times out or exceeds RSS ceiling at a size:

- record the censored result explicitly
- stop larger sizes for that implementation/workload
- continue other implementations
- never extrapolate missing measurements

The headline comparison at the largest scale must use the largest size completed by all compared implementations in that panel.

## 10. Statistics

Persist every raw replicate. Derived summaries must include at least:

- median
- p25
- p75
- min
- max
- median absolute deviation
- replicate count

Speedup is defined as `competitor_median / roml_median` for paired points only. For ROML binding comparisons, use the explicitly named numerator/denominator in the chart subtitle.

Do not calculate or display a speedup for a censored or missing point.

## 11. Memory

Memory is secondary, not a headline metric. Capture when available:

- RSS immediately before target population
- RSS immediately after target population
- process peak RSS/HWM

Do not claim allocator-independent memory efficiency from RSS alone.

## 12. Raw result schema

Each measured result JSON object must contain at least:

```json
{
  "schema_version": 1,
  "run_id": "...",
  "timestamp_utc": "...",
  "benchmark_sha": "...",
  "roml_sha": "6062398b418c4bc0c7718b2ce569da8b9e42766e",
  "implementation": "roml_python_bulk",
  "workload": "sparse_rows",
  "size": 10000,
  "variables": 10000,
  "constraints": 1000,
  "constraint_nnz": 10000,
  "objective_nnz": 10000,
  "replicate": 0,
  "seed": 20260908,
  "container_init_ns": 0,
  "populate_ns": 0,
  "rss_before_bytes": 0,
  "rss_after_bytes": 0,
  "peak_rss_bytes": 0,
  "cpu": null,
  "status": "ok",
  "error": null
}
```

Environment/package metadata may be normalized into a sibling `environment.json`, but the run and source identities must remain unambiguous.

## 13. Result immutability

Authoritative raw results live under:

`results/runs/<run-id>/raw.jsonl`

Do not edit raw records after a run. If a run is invalid, mark it invalid in a sibling metadata file and create a new run.

Derived files may be regenerated:

- `summary.json`
- `summary.csv`
- `site/`

## 14. Website contract

The generated site must be fully usable without internet access and contain no CDN dependencies.

Required pages:

- `index.html` — executive result summary and headline charts
- `python.html` — ROML Python vs PuLP/Pyomo/PyOptInterface
- `roml-core.html` — ROML Python scalar/bulk vs native Rust core
- `methodology.html` — exact benchmark contract, semantic boundaries, pins, host provenance
- `data.html` — run table and links to raw JSONL/CSV/metadata

Required primary visualizations:

1. log-scaled build/population time versus problem size for Python libraries
2. same comparison against model nonzeros or a clearly defined model-size measure
3. speedup versus ROML Python on paired sizes
4. ROML Python scalar vs bulk vs Rust core
5. secondary memory chart or table, clearly labeled as RSS-based

Charts must show measured points, not smoothed/interpolated invented values. Error presentation should use p25/p75 or raw replicate distribution where practical.

The first screen must display:

- run timestamp
- host
- benchmark SHA
- ROML SHA
- package-version summary
- a concise neutral finding generated from the measured data

## 15. Serving contract

Provide a built-in static-site server command binding to `0.0.0.0` by default on port `8787`, plus an option to bind to a specific address.

At completion, install and start a user-level systemd service when user systemd is available. It must:

- serve the generated `site/`
- restart on failure
- start on login/boot when linger/session policy permits
- never require root

The final agent report must print:

- localhost URL
- LAN IPv4 URL if discoverable
- Tailscale IPv4 URL if `tailscale ip -4` succeeds
- service status
- exact run ID and source SHAs

If user systemd is unavailable, leave a documented foreground serve command and use a durable non-root fallback only if it can be verified safely.

## 16. Interpretation discipline

The report may say ROML is faster/slower only for the measured workload, size range, versions, and construction boundary.

Never infer solve performance from model-build performance.
Never hide PyOptInterface's direct-solver architecture.
Never call the benchmark independent or third-party.
Never publish a single-number overall winner without workload context.
