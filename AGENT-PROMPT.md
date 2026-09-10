# Autonomous execution prompt — ROML model-build benchmark v1

You are the implementation owner for `sk-surya/roml-bench`.

## Mission

Start from branch `planning/model-build-benchmark-v1` and autonomously implement, validate, benchmark, publish, and serve the complete **model-building benchmark v1**. Do not stop after scaffolding, a quick benchmark, or chart generation. Finish the entire milestone through the running local-network/Tailscale site and final report.

## First actions

1. Clone/fetch `sk-surya/roml-bench` and check out `planning/model-build-benchmark-v1`.
2. Read these files completely before editing anything:
   - `.planning/PROJECT.md`
   - `.planning/BENCHMARK-CONTRACT.md`
   - `.planning/IMPLEMENTATION-PLAN.md`
   - `AGENT-PROMPT.md`
3. Inspect the current host/toolchain and the pinned ROML source at commit `6062398b418c4bc0c7718b2ce569da8b9e42766e`.
4. Create an execution branch such as `bench/model-build-v1` from the planning branch. Do not implement on `main`.
5. Keep `.planning/STATE.md` current with task, evidence, blockers, and next gate.

## Authority and scope

The planning packet is approved. Execute it; do not ask me to re-decide routine implementation details.

You may make small implementation choices needed to satisfy the contract. Prefer the simplest reliable design. If a dependency/API differs from the packet, inspect the installed stable release, adapt with documented public APIs, and record the deviation in `.planning/DEVIATIONS.md`.

Do **not**:

- modify `sk-surya/roml` to make the benchmark look better
- benchmark a moving ROML `main`
- add solve-time, update-time, extraction, warm-start, or solver-quality scope
- use commercial solvers
- hide failed/censored results
- move data generation, imports, solves, file I/O, or report work into a timed model-population region
- use private competitor APIs just to improve a result
- invent/extrapolate missing benchmark points
- performance-gate on GitHub-hosted CI

## Critical benchmark invariants

Treat `.planning/BENCHMARK-CONTRACT.md` as normative.

In particular:

1. All libraries consume the same deterministic canonical workload data.
2. The primary timer measures `populate_ms`: first variable insertion through objective installation into an already-created empty model.
3. Imports, canonical data generation, validation, solving, serialization, and HTML generation are outside the timer.
4. Every publishable implementation/workload must pass structural checks plus a small objective-equivalence solve gate first.
5. Python primary comparison uses each library's documented efficient public modeling path.
6. ROML also gets a scalar path so Python-scalar vs native-Rust-core is a clean overhead comparison.
7. PyOptInterface's direct solver-backed architecture must be disclosed; do not imply identical internal work.
8. Every replicate is preserved as raw immutable JSON. Summaries are derived artifacts.
9. Any timeout/OOM/failure is data. Stop larger sizes for that implementation/workload according to the contract; do not erase the event.
10. Measured results win over expectations. If ROML loses somewhere, publish it honestly.

## Development method

Execute `.planning/IMPLEMENTATION-PLAN.md` task by task.

For each task:

- inspect relevant APIs before coding
- write/adjust focused tests first when practical
- implement the minimum required behavior
- run the task's verification commands
- commit an independently reviewable change
- update `.planning/STATE.md`

Keep modules small and interfaces explicit. Do not create a large framework around two workloads.

Use exact reproducibility:

- Python 3.13
- `uv` + committed `uv.lock`
- initial stable pins: PuLP 3.3.1, Pyomo 6.10.1, PyOptInterface 0.6.1
- ROML exact SHA `6062398b418c4bc0c7718b2ce569da8b9e42766e`
- release-mode maturin build for ROML Python
- release-mode Cargo build for native ROML core

If a stated package pin is genuinely incompatible with the host, choose the newest compatible stable version, lock it, and document the deviation. Do not silently float versions.

## Benchmark execution

After correctness implementation is complete:

1. Run the full validation gate.
2. Run a quick profile and inspect raw output for schema/timing mistakes.
3. Fix methodology bugs before the authoritative run.
4. Ensure the machine is not under obvious unrelated heavy load.
5. Record environment/provenance.
6. Run the complete standard profile.
7. Summarize from raw JSON only.
8. Inspect paired results for impossible counts or timing anomalies.
9. If the run itself is invalid, mark it invalid and perform a new run. Never edit raw measurements.
10. Generate the final offline site from the accepted authoritative run.

Do not spend time squeezing benchmark variance indefinitely. The acceptance bar is the contract's process isolation, seven standard replicates, transparent environment capture, and honest quartile/median reporting.

## Site quality bar

The output should look like a benchmark publication, not a debug dashboard.

Required:

- `site/index.html`
- `site/python.html`
- `site/roml-core.html`
- `site/methodology.html`
- `site/data.html`
- responsive layout
- offline Plotly bundle; no CDN dependency
- log-scale scaling charts where appropriate
- measured markers and p25/p75 uncertainty
- paired speedup charts
- provenance above the fold
- exact package/source versions
- raw data links
- neutral measured-result copy
- clear PyOptInterface semantic-boundary disclosure

Use simple static Jinja2 + Plotly. Do not introduce React/Node/Next/Vite or a backend application.

## Final serving requirement

This task is **not complete** when HTML files merely exist.

At the end:

1. install/start `roml-bench-site.service` as a user-level systemd service when available
2. bind the static server to `0.0.0.0:8787` unless a safer host-specific decision is required
3. verify localhost with `curl`
4. verify listening socket with `ss`
5. discover LAN IPv4
6. discover Tailscale IPv4 with `tailscale ip -4` when available
7. curl the LAN/Tailscale address from the host where routing allows it
8. leave the service active after your run

Do not use sudo merely to serve the report. Do not change firewall/router configuration unless absolutely necessary and clearly safe. If local service is correct but network policy prevents remote access, report that exact blocker with evidence.

## Final verification gate

Before claiming completion, run and record at least:

```bash
uv run ruff check .
uv run pytest -q
cargo fmt --all -- --check
cargo clippy -p roml-bench-core --all-targets -- -D warnings
cargo test -p roml-bench-core
uv run roml-bench validate
systemctl --user is-active roml-bench-site.service
curl -fsS http://127.0.0.1:8787/ >/dev/null
ss -ltn | grep ':8787'
git status --short
```

Also verify the generated site has no external CDN script/style dependencies.

## Final artifacts

Commit:

- implementation and tests
- `uv.lock`
- validation evidence
- authoritative `results/runs/<run-id>/` raw + summaries + environment metadata
- generated `site/`
- `.planning/DEVIATIONS.md`
- `.planning/FINAL-REPORT.md`

If GitHub CLI/auth is available, push the execution branch and open/update a draft PR against `main`. Do not bypass branch protections or merge without owner direction.

## Final response to me

Return one compact completion report containing:

- execution branch and exact HEAD SHA
- authoritative run ID
- ROML SHA
- installed comparison-library versions
- validation result
- largest common completed size per workload
- measured headline results (no extrapolation)
- tests/checks result
- localhost URL
- LAN URL if available
- Tailscale URL if available
- `roml-bench-site.service` status
- PR number/link if created
- remaining limitations only if material

Do not propose the next benchmark milestone. Stop with model-building v1 complete and served.
