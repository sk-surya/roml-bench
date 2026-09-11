# ROML Model-Build Benchmark v1 — Implementation Plan

> **For agentic workers:** execute this plan autonomously task-by-task. Keep work on a feature branch, use tests before implementation where practical, commit each independently reviewable task, and do not stop for routine choices already resolved by this packet.

**Goal:** Produce reproducible model-construction benchmarks for ROML Python vs PuLP/Pyomo/PyOptInterface and ROML Python vs native ROML core, then generate and serve a polished offline HTML report.

**Architecture:** A canonical workload layer produces deterministic coefficient/index data. Thin adapters translate that data into each modeling library. A process-isolated orchestrator records raw JSONL. A summarizer derives statistics. A Jinja2 + Plotly static-site generator emits offline HTML. A minimal built-in HTTP server and optional user-systemd unit serve the generated site.

**Tech stack:** Python 3.13, uv, maturin, NumPy/SciPy, PuLP, Pyomo, PyOptInterface, HiGHS for validation only, Rust/Cargo, ROML pinned at `6062398b418c4bc0c7718b2ce569da8b9e42766e`, Jinja2, Plotly, psutil, pytest, ruff.

**Spec:** `.planning/PROJECT.md` and `.planning/BENCHMARK-CONTRACT.md`

## Global constraints

- Do not modify `sk-surya/roml` as part of this milestone.
- Timed code must contain model population only, exactly as defined by the benchmark contract.
- No solve call may occur inside a timed region.
- All authoritative numbers come from immutable raw JSON records.
- Never silently omit failures/timeouts/OOMs.
- CI runs correctness/smoke only; authoritative performance data comes from the target host.
- Generated site must work offline.
- No benchmark-result interpretation before equivalence/structural validation passes.

---

## Target repository layout

```text
roml-bench/
├── .github/workflows/ci.yml
├── .planning/
│   ├── PROJECT.md
│   ├── BENCHMARK-CONTRACT.md
│   ├── IMPLEMENTATION-PLAN.md
│   ├── STATE.md
│   ├── DEVIATIONS.md
│   └── FINAL-REPORT.md
├── Cargo.toml
├── pyproject.toml
├── uv.lock
├── README.md
├── scripts/
│   ├── bootstrap.sh
│   └── install-user-service.sh
├── src/roml_bench/
│   ├── __init__.py
│   ├── cli.py
│   ├── schema.py
│   ├── workloads.py
│   ├── system.py
│   ├── orchestrator.py
│   ├── summarize.py
│   ├── validate.py
│   ├── serve.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── roml_python.py
│   │   ├── pulp.py
│   │   ├── pyomo.py
│   │   └── pyoptinterface.py
│   └── site/
│       ├── generate.py
│       ├── charts.py
│       └── templates/
│           ├── base.html.j2
│           ├── index.html.j2
│           ├── python.html.j2
│           ├── roml-core.html.j2
│           ├── methodology.html.j2
│           └── data.html.j2
├── rust-core/
│   ├── Cargo.toml
│   └── src/main.rs
├── tests/
│   ├── test_workloads.py
│   ├── test_schema.py
│   ├── test_adapters_smoke.py
│   ├── test_validation.py
│   ├── test_orchestrator.py
│   ├── test_summarize.py
│   └── test_site.py
├── fixtures/
│   └── quick-results.jsonl
├── results/runs/
└── site/
```

Keep modules focused. If a module grows beyond one clear responsibility, split it rather than accumulating unrelated helpers.

---

## Task 1 — Reproducible bootstrap and package skeleton

**Deliverable:** one command produces a usable Python environment, installs the pinned ROML Python wheel from source, and builds the native Rust runner dependencies.

**Files:** `pyproject.toml`, `Cargo.toml`, `rust-core/Cargo.toml`, `scripts/bootstrap.sh`, `src/roml_bench/__init__.py`, `README.md`, `.planning/STATE.md`, `.planning/DEVIATIONS.md`.

### Required interfaces

Expose a console script:

```toml
[project.scripts]
roml-bench = "roml_bench.cli:main"
```

`bootstrap.sh` must:

1. require/find Python 3.13 and `uv`
2. run `uv sync`
3. clone/fetch `sk-surya/roml` into `.cache/roml`
4. checkout exact SHA `6062398b418c4bc0c7718b2ce569da8b9e42766e`
5. build the ROML Python extension in release mode with maturin
6. install that wheel into `.venv`
7. verify `import roml` and record `roml.__version__`
8. build `rust-core` in release mode
9. print exact Python, package, Rust, Cargo, benchmark git SHA, and ROML SHA

Initial benchmark dependencies: PuLP 3.3.1, Pyomo 6.10.1, PyOptInterface 0.6.1. Lock all dependencies with `uv.lock`.

### Tests/gates

```bash
./scripts/bootstrap.sh
uv run python -c 'import roml, pulp, pyomo, pyoptinterface; print("imports-ok")'
cargo build --release -p roml-bench-core
uv run ruff check .
```

Commit: `build: bootstrap reproducible benchmark environment`

---

## Task 2 — Canonical workload layer

**Deliverable:** deterministic, library-independent workload specifications with exact structural counts.

**Files:** `src/roml_bench/workloads.py`, `src/roml_bench/schema.py`, `tests/test_workloads.py`, `tests/test_schema.py`.

### Interfaces

Define immutable workload descriptions roughly equivalent to:

```python
@dataclass(frozen=True)
class WorkloadCase:
    workload: str
    size: int
    seed: int
    variables: int
    constraints: int
    constraint_nnz: int
    objective_nnz: int
    payload: object


def make_case(workload: str, size: int, seed: int) -> WorkloadCase: ...
```

The `payload` contains precomputed arrays/index data only. It must be created outside timed regions.

Add pure count helpers for `sparse_rows` and `bess_96` and assert the formulas in `.planning/BENCHMARK-CONTRACT.md`.

### Tests

At minimum verify:

- `sparse_rows(1000)` => 1000 vars, 100 rows, 1000 row nnz, 1000 objective nnz
- `bess_96(10)` => 2890 vars, 1930 rows, 5770 row nnz, 1920 objective nnz
- same seed produces byte-identical numeric price payload
- different seed changes BESS prices but not structure

Run:

```bash
uv run pytest tests/test_workloads.py tests/test_schema.py -q
```

Commit: `feat: add canonical benchmark workloads`

---

## Task 3 — Python adapter contract and implementations

**Deliverable:** all four Python libraries can build both quick workloads from the same canonical cases and return a common measurement record.

**Files:** `src/roml_bench/adapters/*`, `tests/test_adapters_smoke.py`.

### Adapter boundary

Define an adapter protocol with no benchmark orchestration inside it:

```python
class Adapter(Protocol):
    implementation_id: str
    def warmup(self) -> None: ...
    def new_model(self, case: WorkloadCase) -> object: ...
    def populate(self, model: object, case: WorkloadCase) -> BuildArtifact: ...
    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport: ...
```

`populate()` is the only method called inside the primary timer. It must not generate workload data, import modules, solve, print, or write files.

### Implementation requirements

- `roml_python_vectorized`: use public array/bulk ROML constructs; for `sparse_rows`, use bulk vars + CSR/bulk-row path where it expresses the canonical model directly.
- `roml_python_scalar`: use `Model.var`/scalar expressions/`Model.add` without bulk shortcuts.
- `pulp_python`: use the pinned stable public PuLP API and efficient supported expression helpers.
- `pyomo_python`: use `ConcreteModel`, indexed `Var`/`Constraint`, and efficient documented summation/expression construction.
- `pyoptinterface_python`: first probe the pinned HiGHS model for documented `add_m_variables` / `add_m_linear_constraints`; use them if genuinely supported. Otherwise use the documented efficient `ExprBuilder` scalar path. Record the selected path as metadata.

Do not use private undocumented APIs merely to improve a number.

### Smoke gates

For quick cases, every adapter must successfully build without solve. `inspect()` must verify all counts that are publicly introspectable.

Run:

```bash
uv run pytest tests/test_adapters_smoke.py -q
```

Commit: `feat: add Python modeling-library adapters`

---

## Task 4 — Native ROML core runner

**Deliverable:** optimized Rust executable that builds the exact same workload formulas and emits one JSON measurement record.

**Files:** `rust-core/src/main.rs`, `rust-core/Cargo.toml`, root `Cargo.toml`.

Pin ROML with an exact git `rev` matching the project source baseline. Build with `--release`.

CLI contract:

```text
roml-bench-core --workload sparse_rows --size 10000 --seed 20260908 --replicate 0
roml-bench-core --workload bess_96 --size 10 --seed 20260908 --replicate 0
```

The binary must:

- generate canonical numeric payload before timing
- perform tiny warmup before target timing
- time only model population
- emit exactly one JSON object on stdout
- never solve in the measured path
- include structural expected counts and ROML source SHA

Add Rust unit tests for count formulas and deterministic payload generation.

Run:

```bash
cargo test -p roml-bench-core
cargo clippy -p roml-bench-core --all-targets -- -D warnings
cargo build --release -p roml-bench-core
```

Commit: `feat: add native ROML core benchmark runner`

---

## Task 5 — Structural and mathematical validation gate

**Deliverable:** a command that proves every publishable adapter/workload is structurally consistent and mathematically equivalent on bounded validation instances.

**Files:** `src/roml_bench/validate.py`, `tests/test_validation.py`.

CLI:

```bash
uv run roml-bench validate
```

For each implementation/workload:

- compare available model counts with `WorkloadCase`
- perform bound/domain spot checks
- construct a small deterministic validation instance
- solve outside all timing code using HiGHS-compatible paths
- compare objective values within `1e-7 abs + 1e-7 rel`
- write `results/validation.json`

The benchmark command must refuse to create an authoritative run if validation is absent, stale relative to source/package pins, or failed.

Run:

```bash
uv run pytest tests/test_validation.py -q
uv run roml-bench validate
```

Commit: `test: add benchmark equivalence validation gate`

---

## Task 6 — Process-isolated measurement orchestrator

**Deliverable:** deterministic quick/standard benchmark runner producing immutable JSONL raw data and environment metadata.

**Files:** `src/roml_bench/system.py`, `src/roml_bench/orchestrator.py`, `src/roml_bench/cli.py`, `tests/test_orchestrator.py`.

Required CLI:

```bash
uv run roml-bench run --profile quick
uv run roml-bench run --profile standard
```

Required behavior:

- one fresh subprocess per implementation/size/replicate
- deterministic randomized implementation order per size/replicate
- single-CPU affinity when possible
- thread environment limits from the contract
- quick: 3 replicates, 15 s point limit
- standard: 7 replicates, 120 s hard process limit, 16 GiB RSS ceiling, stop larger sizes after implementation/workload censoring
- capture stdout/stderr separately; only valid JSON becomes raw result
- record timeout/OOM/error as data, never as omitted rows
- create `results/runs/<run-id>/raw.jsonl`
- create `environment.json` before measurements
- create immutable `run.json` containing configuration and validation fingerprint

`run-id` should be sortable and collision-resistant, for example `20260908T041500Z-ai90-<benchsha8>`.

Use `psutil` monitoring for RSS ceiling and process termination. Never kill unrelated processes.

Run:

```bash
uv run pytest tests/test_orchestrator.py -q
uv run roml-bench run --profile quick
```

Commit: `feat: add isolated benchmark orchestrator`

---

## Task 7 — Statistical summarizer

**Deliverable:** deterministic summaries and paired speedups derived only from raw JSONL.

**Files:** `src/roml_bench/summarize.py`, `tests/test_summarize.py`, `fixtures/quick-results.jsonl`.

CLI:

```bash
uv run roml-bench summarize results/runs/<run-id>
```

For every successful group compute median, p25, p75, min, max, MAD, count. Preserve censored/error groups. Generate:

- `summary.json`
- `summary.csv`

Paired speedups are produced only where both implementations have a successful point at identical workload/size.

Tests must include missing/censored points and ensure no extrapolated speedup is emitted.

Commit: `feat: summarize benchmark measurements`

---

## Task 8 — Offline publication-quality site

**Deliverable:** responsive static site that communicates results and methodology without internet access.

**Files:** `src/roml_bench/site/*`, templates, tests, generated `site/`.

Use Jinja2 for pages and Plotly for interactive charts. Bundle Plotly JS locally; no CDN. Keep the site static—no Node build, SPA framework, database, or web backend.

Required commands:

```bash
uv run roml-bench site results/runs/<run-id>
```

Required pages and plots are normative in `.planning/BENCHMARK-CONTRACT.md`.

Visual requirements:

- responsive desktop/mobile layout
- readable system-font typography
- accessible contrast and stable implementation colors
- log scales where scaling spans orders of magnitude
- visible measured markers
- p25/p75 error bars or bands
- tooltips with median, quartiles, model counts, implementation, package version
- concise neutral finding text derived from actual paired measurements
- explicit direct-solver-boundary note for PyOptInterface on the Python comparison page
- raw-data and methodology links in persistent navigation
- provenance block above the fold

Tests:

- generate site from fixture results
- assert all required pages exist
- assert no `http://`/`https://` CDN script/style dependency in generated HTML
- assert every chart references only measured points from fixture summary
- assert raw-data links resolve

Optional: use Playwright only if already easy to install; it is not required. At minimum render/open pages with a local browser when available and inspect for layout regressions.

Commit: `feat: generate offline benchmark report site`

---

## Task 9 — Serve command and persistent user service

**Deliverable:** generated site is reachable from the host network after the agent exits.

**Files:** `src/roml_bench/serve.py`, `scripts/install-user-service.sh`, README docs, tests where possible.

CLI:

```bash
uv run roml-bench serve --host 0.0.0.0 --port 8787 --directory site
```

The command must print reachable addresses it can discover:

- `http://127.0.0.1:8787/`
- LAN IPv4 URL
- Tailscale IPv4 URL when `tailscale ip -4` succeeds

`install-user-service.sh` installs a user service named `roml-bench-site.service` that launches the serve command from this repository, restarts on failure, and does not require root.

Verify with:

```bash
systemctl --user daemon-reload
systemctl --user enable --now roml-bench-site.service
systemctl --user is-active roml-bench-site.service
curl -fsS http://127.0.0.1:8787/ >/dev/null
ss -ltn | grep ':8787'
```

If a LAN or Tailscale IP is available, also `curl` the site through that address from the host. Do not alter firewall/router policy unless explicitly required and safe; report a network-policy blocker if local bind works but remote routing is externally blocked.

Commit: `feat: serve benchmark report on local network`

---

## Task 10 — CI correctness gate

**Deliverable:** PRs verify benchmark code without pretending shared CI timing is performance evidence.

**File:** `.github/workflows/ci.yml`.

CI must run:

```bash
uv sync --frozen
uv run ruff check .
uv run pytest -q
cargo fmt --all -- --check
cargo clippy -p roml-bench-core --all-targets -- -D warnings
cargo test -p roml-bench-core
```

Run a fixture/site-generation smoke. A tiny benchmark smoke may run only if bootstrap cost is reasonable, but CI must not assert absolute performance or speedup thresholds.

Commit: `ci: verify benchmark correctness and site generation`

---

## Task 11 — Authoritative standard run and publication

**Deliverable:** real benchmark data, generated site, final report, and running service.

Before running:

1. ensure git tree is clean
2. record benchmark HEAD
3. ensure ROML pin is exact
4. run full validation
5. inspect host load and record environment; do not proceed during obvious heavy unrelated load if it would invalidate the benchmark

Execute:

```bash
uv run roml-bench validate
uv run roml-bench run --profile standard
uv run roml-bench summarize results/runs/<run-id>
uv run roml-bench site results/runs/<run-id>
```

Then inspect summaries for impossible values, missing paired sizes, validation mismatch, or timing-boundary mistakes. Re-run the entire authoritative run if methodology was wrong; never edit raw records.

Commit the authoritative `results/runs/<run-id>/` directory and generated `site/`.

Install/start the user service and verify URLs.

Write `.planning/FINAL-REPORT.md` with:

- exact benchmark SHA used for measurements
- exact ROML SHA
- package versions
- host/CPU/RAM/OS metadata
- run ID
- validation status
- completed/censored size range by implementation
- measured headline findings without extrapolation
- all test/CI commands and outcomes
- service status
- localhost/LAN/Tailscale URLs
- any deviations/limitations

Commit: `bench: publish model-build benchmark v1`

---

## Task 12 — Final self-review and stop condition

Perform a final review against both normative planning files.

Required final commands:

```bash
uv run ruff check .
uv run pytest -q
cargo fmt --all -- --check
cargo clippy -p roml-bench-core --all-targets -- -D warnings
cargo test -p roml-bench-core
uv run roml-bench validate
systemctl --user is-active roml-bench-site.service
curl -fsS http://127.0.0.1:8787/ >/dev/null
git status --short
```

The milestone stops only when:

- tests and static checks pass
- validation passes
- authoritative standard results exist
- generated site exists and is offline/self-contained
- service is active and reachable locally
- at least one LAN or Tailscale URL is printed when such an interface exists
- final report is complete
- worktree is clean

Do not begin solve-time or incremental-update benchmarking. Record those only as later work.
