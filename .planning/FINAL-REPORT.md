# Final report — ROML model-build benchmark v1

## Identity

- Execution branch: `bench/model-build-v1`
- Benchmark SHA measured at: `64615d6cce15e0b00ba7542c2e1f2a78d920771a`
- Results publication commit: `e4fcad3` (authoritative run + generated site)
- Authoritative run ID: `20260908T042228Z-ai90-64615d6c`
- ROML SHA: `6062398b418c4bc0c7718b2ce569da8b9e42766e` (merge of PR #53)
- Canonical seed: `20260908`

## Packages (actually installed, from environment.json)

Python 3.13.14 · roml-python 0.1.0 (`import roml` 0.1.0) · PuLP 3.3.1 ·
Pyomo 6.10.1 · PyOptInterface 0.6.1 · HiGHS (highspy) 1.15.1 ·
NumPy 2.5.3 · SciPy 1.18.1 · Jinja2 3.1.6 · Plotly 7.0.0 · psutil 7.2.2 ·
rustc/cargo 1.97.1. Full lockfile: `uv.lock` (+ `Cargo.lock` for the Rust runner).

## Host

AMD Ryzen 9 9950X 16-Core, 32 logical CPUs, 59.5 GiB RAM,
Linux 7.0.0-30-generic, governor `powersave`, load average at run start
0.83/1.11/1.06 (idle 32-core host). Children pinned to one logical CPU with
`OMP/OPENBLAS/MKL/NUMEXPR/RAYON_NUM_THREADS=1`.

## Validation

`roml-bench validate`: **ok** for all 6 implementations. Structural counts
match the contract on `sparse_rows/100` and `bess_96/1`; bound/domain spot
checks pass; deterministic HiGHS-compatible solves agree across all five
Python paths (sparse 0.0; bess B=1 651.993846 within 1e-7 abs + 1e-7 rel).
Rust core counts verified by executing the release binary on both
validation sizes. Evidence: `results/validation.json`.

## Completed / censored ranges (standard profile, 7 replicates)

- `sparse_rows` 1k–1M: PuLP, Pyomo, PyOptInterface, ROML bulk, ROML core
  completed all 7 sizes. ROML scalar completed through 100k, then hit the
  120 s wall timeout at 300k (1 event) and stopped there per policy —
  recorded as data, never extrapolated.
- `bess_96` B=1–300: all 6 implementations completed all sizes.
- 533 raw records (532 ok + 1 timeout); 77 summary groups; 74 paired
  speedups. Raw-record count audit and per-record canonical-count checks:
  0 inconsistencies; every implementation's medians monotonic in size.

## Measured headline findings (paired medians, no extrapolation)

- `sparse_rows` N=1M: Pyomo fastest (1.05 s); ROML bulk 1.70 s (1.61x);
  PyOptInterface 1.65 s (0.97x vs ROML bulk); PuLP 1.98 s (1.17x);
  native core 1.30 s.
- `bess_96` B=300: PyOptInterface fastest (216 ms); Pyomo 358 ms (0.59x vs
  ROML bulk); PuLP 475 ms (0.78x); ROML bulk 606 ms; native core 116 ms.
- ROML binding overhead: scalar-vs-core 350.6x at sparse 100k (scalar
  Python loops do not scale); bulk-vs-core 1.26x at sparse 100k —
  the public fast path is within ~26% of native construction there.
- Small sizes differ: ROML bulk is fastest Python path at bess B=1–10 and
  second at sparse 1k–30k. No single-number overall winner is claimed;
  the site shows full curves with p25/p75 bands.

Where ROML loses (sparse at scale to Pyomo; bess_300 to PyOptInterface),
the measured numbers are published unchanged per the interpretation
discipline.

## Checks run and outcomes

- `uv run ruff check .` — clean
- `uv run pytest -q` — 41 passed
- `cargo fmt --all -- --check` — clean
- `cargo clippy -p roml-bench-core --all-targets -- -D warnings` — clean
- `cargo test -p roml-bench-core` — 3 passed
- `uv run roml-bench validate` — ok (all 6 implementations)
- Site integrity: 5 pages exist; bundled `static/plotly.min.js` (4.3 MB);
  zero `http(s)://` script/style references; all charts built from measured
  points only; all `data/` links resolve.

## Serving

- Service: `roml-bench-site.service` — **active** (user unit, restart
  on failure, serves `site/` on `0.0.0.0:8787` via `.venv/bin/roml-bench`).
- Localhost: http://127.0.0.1:8787/ (curl-verified, incl. subpages)
- LAN: http://192.168.0.111:8787/ (curl-verified from host)
- Tailscale: http://100.67.169.109:8787/ (curl-verified from host)

## Deviations and limitations

- No deviations from `.planning/BENCHMARK-CONTRACT.md`. One implementation
  detail worth knowing: the Rust runner takes BESS prices via
  `--prices-csv` from the orchestrator so it consumes byte-identical
  canonical input (documented in methodology, additive CLI flag only).
- PuLP uses the non-deprecated `add_variable_dicts`/`constraints()` APIs
  of pinned 3.3.1; PuLP validation solves use bundled CBC (no `highs`
  binary in the environment); Pyomo uses appsi_highs; PyOptInterface loads
  the highspy-bundled libhighs explicitly (pinned autoloader only probes
  the unversioned soname). All disclosed on the methodology page.
- Methodology bug caught by the quick profile and fixed before the
  authoritative run: BESS CSR rows were built battery-interleaved while
  bounds assumed grouped order (commit `0746d06`); the tainted quick run
  was discarded, never published.
- Governor is `powersave` (no sudo used to change it, per contract);
  machine was otherwise idle and replicates are tight, but absolute times
  remain host-specific — compare medians/ratios, not single samples.
- Scope is model construction only: no solve-time, incremental-update,
  warm-start, extraction, or solver-quality claims.

---

# Addendum — forensic pass v2 (2026-09-08, supersedes v1 headlines)

Owner review found the v1 BESS leaderboard methodologically invalid as a
single panel (preassembled CSR for POI vs algebra formulation for ROML)
and the 350x figure misdiagnosed (O(n^2) naive expression chaining, not
binding overhead). PR #1 stays draft; v1 raw data is retained for the
record but its headlines are withdrawn. Packet: `.planning/FORENSIC-PASS.md`.

- Forensic run ID: `20260908T053319Z-ai90-14738229` (benchmark SHA at
  measurement: `14738229`; 793 raw records: 791 ok + 1 timeout + 1 error).
- Validation: ok for all 9 arms (fused-dot equivalence proven by
  cross-solver agreement; CSR/anon arms verified).
- Corrected findings (paired medians):
  - BESS formulation B=300: POI scalar 130 ms fastest; ROML bulk (fused)
    197 ms; POI matrix 211 ms; Pyomo 359 ms; PuLP 475 ms; naive chain 4.8 s.
  - BESS ingestion B=300: ROML CSR 168 ms < ROML bulk 197 ms < POI 211 ms.
  - Sparse formulation 100k (largest fully paired): Pyomo 88 ms fastest;
    POI scalar 0.78x, ROML bulk baseline; naive chain 274x (chaining cost).
  - Sparse ingestion 1M: POI 1.60 s vs ROML bulk 1.71 s; Pyomo 1.05 s
    (formulation) still leads overall; core 1.23 s.
  - Named vs anonymous core: 1.03x at sparse 100k (no significant
    name-registration effect at this scale).
  - Phases (sparse 1M): ROML bulk objective 804 ms of 1710 ms; vars 328 ms
    vs core vars 77 ms; POI vars 1186 ms dominate its total.
  - Variants: shuffled ≈ canonical (no sorted-input effect); duplicated
    costs ROML bulk nothing measurable; POI matrix cannot ingest
    duplicates (HiGHS Status -1) — an API limitation, published as data.
- Censored: naive chain sparse 300k timeout (expected O(n^2)); POI
  duplicated-100k error stopped only that diagnostic (variant-scoped stop
  keys; canonical 1M POI intact).
- Trust: bulk-vs-core gap (~1.3x sparse), core-vs-Pyomo gap (real),
  ingestion ranking (ROML CSR < POI on BESS). Do not trust: any
  binding-overhead claim from the naive chain; v1 BESS numbers.
