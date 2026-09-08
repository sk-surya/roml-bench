"""Process-isolated benchmark orchestration (contract sections 7-9, 13).

Every measured replicate runs in a fresh child process. The orchestrator
randomizes implementation order per workload/size/replicate, pins children
to one logical CPU when possible, enforces wall-time and RSS ceilings, and
appends immutable raw JSON records to results/runs/<run-id>/raw.jsonl.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

from roml_bench.schema import ROML_SHA, validate_record
from roml_bench.system import THREAD_ENV, collect_environment, git_sha
from roml_bench.validate import validation_fingerprint
from roml_bench.workloads import CANONICAL_SEED, make_case, sizes_for

PYTHON_IMPLEMENTATIONS = (
    "roml_python_bulk",
    "roml_python_scalar",
    "pulp_python",
    "pyomo_python",
    "pyoptinterface_python",
)
ALL_IMPLEMENTATIONS = PYTHON_IMPLEMENTATIONS + ("roml_core_rust",)

PROFILES = {
    "quick": {
        "replicates": 3,
        "wall_timeout_s": 15,
        "rss_ceiling_bytes": 16 * 1024**3,
        "pilot_cap_s": None,
    },
    "standard": {
        "replicates": 7,
        "wall_timeout_s": 120,
        "rss_ceiling_bytes": 16 * 1024**3,
        "pilot_cap_s": 60,
    },
}

WORKLOADS = ("sparse_rows", "bess_96")

RUST_BINARY = Path("target/release/roml-bench-core")


def make_run_id(benchmark_sha: str | None) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    host = socket.gethostname().split(".")[0]
    short = (benchmark_sha or "unknown")[:8]
    return f"{stamp}-{host}-{short}"


def shuffled_order(
    implementations: tuple[str, ...], workload: str, size: int, replicate: int, seed: int
) -> list[str]:
    """Deterministic per-point randomized implementation order."""
    digest = hashlib.sha256(f"{seed}/{workload}/{size}/{replicate}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    order = list(implementations)
    rng.shuffle(order)
    return order


def check_validation_gate(repo: str = ".") -> dict:
    """Refuse to run unless validation is present, passing, and current."""
    path = Path(repo) / "results" / "validation.json"
    if not path.exists():
        raise RuntimeError(
            "validation gate: results/validation.json is absent; "
            "run roml-bench validate first"
        )
    validation = json.loads(path.read_text())
    if validation.get("status") != "ok":
        raise RuntimeError("validation gate: results/validation.json status is not ok")
    current = {
        "benchmark_sha": git_sha(repo),
        "roml_checkout_sha": _roml_sha(repo),
        "packages": collect_environment()["packages"],
        "status": "ok",
    }
    expected = validation_fingerprint(validation)
    if expected["benchmark_sha"] != current["benchmark_sha"]:
        raise RuntimeError(
            f"validation gate: stale benchmark_sha {expected['benchmark_sha']} "
            f"!= current {current['benchmark_sha']}; re-run roml-bench validate"
        )
    if expected["roml_checkout_sha"] != current["roml_checkout_sha"]:
        raise RuntimeError("validation gate: ROML checkout changed; re-run roml-bench validate")
    if expected["packages"] != current["packages"]:
        raise RuntimeError("validation gate: package set changed; re-run roml-bench validate")
    return validation


def _roml_sha(repo: str) -> str | None:
    from roml_bench.system import roml_checkout_sha

    if Path(repo, ".cache/roml").exists():
        return roml_checkout_sha()
    return ROML_SHA


def pick_cpu() -> int | None:
    """One logical CPU from the current allowed set, or None if unsettable."""
    try:
        allowed = sorted(os.sched_affinity(0))
        return allowed[0] if allowed else None
    except (AttributeError, OSError):
        return None


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(THREAD_ENV)
    return env


def _parse_record(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith('{"schema_version"'):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def censored_record(
    implementation: str,
    workload: str,
    size: int,
    replicate: int,
    run_id: str,
    benchmark_sha: str,
    seed: int,
    cpu: int | None,
    status: str,
    error: str,
) -> dict:
    case = make_case(workload, size, seed=seed)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "benchmark_sha": benchmark_sha,
        "roml_sha": ROML_SHA,
        "implementation": implementation,
        "workload": workload,
        "size": size,
        "variables": case.variables,
        "constraints": case.constraints,
        "constraint_nnz": case.constraint_nnz,
        "objective_nnz": case.objective_nnz,
        "replicate": replicate,
        "seed": seed,
        "container_init_ns": 0,
        "populate_ns": 0,
        "rss_before_bytes": 0,
        "rss_after_bytes": 0,
        "peak_rss_bytes": 0,
        "cpu": cpu,
        "status": status,
        "error": error,
    }


def run_child(
    implementation: str,
    workload: str,
    size: int,
    seed: int,
    replicate: int,
    run_id: str,
    benchmark_sha: str,
    cpu: int | None,
    wall_timeout_s: int,
    rss_ceiling_bytes: int,
) -> dict:
    """Run one replicate in a fresh child; always return a record."""
    env = _child_env()
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if implementation not in ALL_IMPLEMENTATIONS:
        raise ValueError(f"unknown implementation: {implementation}")
    if implementation == "roml_core_rust":
        if not RUST_BINARY.exists():
            return censored_record(
                implementation, workload, size, replicate, run_id,
                benchmark_sha, seed, cpu, "error",
                "target/release/roml-bench-core not built",
            )
        cmd = [
            str(RUST_BINARY),
            "--workload", workload,
            "--size", str(size),
            "--seed", str(seed),
            "--replicate", str(replicate),
            "--run-id", run_id,
            "--benchmark-sha", benchmark_sha,
            "--roml-sha", ROML_SHA,
            "--timestamp-utc", timestamp,
        ]
        if cpu is not None:
            cmd += ["--cpu", str(cpu)]
        if workload == "bess_96":
            case = make_case(workload, size, seed=seed)
            prices = case.payload["prices"]
            cmd += ["--prices-csv", ",".join(repr(float(v)) for v in prices.tolist())]
    else:
        cmd = [
            sys.executable, "-m", "roml_bench.worker",
            "--implementation", implementation,
            "--workload", workload,
            "--size", str(size),
            "--seed", str(seed),
            "--replicate", str(replicate),
            "--run-id", run_id,
            "--benchmark-sha", benchmark_sha,
        ]
        if cpu is not None:
            cmd += ["--cpu", str(cpu)]

    def preexec():
        try:
            if cpu is not None:
                os.sched_setaffinity(0, {cpu})
        except (AttributeError, OSError):
            pass

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, preexec_fn=preexec,
        )
    except OSError as exc:
        return censored_record(
            implementation, workload, size, replicate, run_id,
            benchmark_sha, seed, cpu, "error", f"spawn failed: {exc}",
        )

    peak_seen = 0
    deadline = time.monotonic() + wall_timeout_s
    outcome = "ok"
    kill_reason = ""
    try:
        import psutil

        monitor = psutil.Process(proc.pid)
    except Exception:
        monitor = None
    while True:
        ret = proc.poll()
        if ret is not None:
            break
        if monitor is not None:
            try:
                rss = int(monitor.memory_info().rss)
                peak_seen = max(peak_seen, rss)
                if rss > rss_ceiling_bytes:
                    outcome = "memory_exceeded"
                    kill_reason = f"RSS {rss} exceeded ceiling {rss_ceiling_bytes}"
                    proc.kill()
                    break
            except Exception:
                pass
        if time.monotonic() > deadline:
            outcome = "timeout"
            kill_reason = f"wall timeout after {wall_timeout_s}s"
            proc.kill()
            break
        time.sleep(0.05)
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        outcome = "timeout"
        kill_reason = f"wall timeout after {wall_timeout_s}s (drain)"
    if outcome != "ok":
        return censored_record(
            implementation, workload, size, replicate, run_id,
            benchmark_sha, seed, cpu, outcome, kill_reason,
        )
    record = _parse_record(stdout or "")
    if record is None:
        tail = (stderr or "")[-1000:]
        return censored_record(
            implementation, workload, size, replicate, run_id,
            benchmark_sha, seed, cpu, "error",
            f"exit {proc.returncode} without JSON record; stderr: {tail}",
        )
    problems = validate_record(record)
    if problems:
        record["status"] = "error"
        record["error"] = f"schema violations: {'; '.join(problems)}"
    if peak_seen and record.get("peak_rss_bytes", 0) < peak_seen:
        record["peak_rss_bytes"] = peak_seen
    if (record.get("peak_rss_bytes") or 0) > rss_ceiling_bytes and record["status"] == "ok":
        record["status"] = "memory_exceeded"
        record["error"] = (
            f"peak RSS {record['peak_rss_bytes']} exceeded ceiling {rss_ceiling_bytes}"
        )
    return record


def run_profile(profile: str, run_id: str | None = None, repo: str = ".") -> Path:
    """Execute a full benchmark profile; return the run directory."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    config = PROFILES[profile]
    check_validation_gate(repo)
    benchmark_sha = git_sha(repo) or "unknown"
    run_id = run_id or make_run_id(benchmark_sha)
    run_dir = Path(repo) / "results" / "runs" / run_id
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    environment = collect_environment()
    (run_dir / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")

    seed = CANONICAL_SEED
    plan = [
        (workload, size)
        for workload in WORKLOADS
        for size in sizes_for(workload, profile)
    ]
    run_meta = {
        "run_id": run_id,
        "profile": profile,
        "seed": seed,
        "benchmark_sha": benchmark_sha,
        "roml_sha": ROML_SHA,
        "config": config,
        "plan": [{"workload": w, "size": s} for w, s in plan],
        "implementations": list(ALL_IMPLEMENTATIONS),
        "stopped": [],
        "points": {},
    }
    (run_dir / "run.json").write_text(json.dumps(run_meta, indent=2) + "\n")

    raw_path = run_dir / "raw.jsonl"
    stopped: set[tuple[str, str]] = set()
    with open(raw_path, "w") as raw:
        for workload, size in plan:
            for replicate in range(config["replicates"]):
                # Pilot cap (standard): replicate 0 runs first; an
                # implementation whose own build already exceeds the pilot
                # budget is stopped (no further replicates or larger sizes).
                pilot_first = config["pilot_cap_s"] is not None and replicate == 0
                order = shuffled_order(
                    ALL_IMPLEMENTATIONS, workload, size, replicate, seed
                )
                cpu = pick_cpu()
                for implementation in order:
                    if (implementation, workload) in stopped:
                        continue
                    record = run_child(
                        implementation, workload, size, seed, replicate,
                        run_id, benchmark_sha, cpu,
                        config["wall_timeout_s"], config["rss_ceiling_bytes"],
                    )
                    raw.write(json.dumps(record) + "\n")
                    raw.flush()
                    key = f"{workload}/{size}/{implementation}"
                    run_meta["points"].setdefault(key, []).append(record["status"])
                    if record["status"] != "ok":
                        stopped.add((implementation, workload))
                        run_meta["stopped"].append(
                            {
                                "implementation": implementation,
                                "workload": workload,
                                "size": size,
                                "status": record["status"],
                                "error": record["error"],
                            }
                        )
                    elif pilot_first and (
                        record["populate_ns"] / 1e9 > config["pilot_cap_s"]
                    ):
                        stopped.add((implementation, workload))
                        run_meta["stopped"].append(
                            {
                                "implementation": implementation,
                                "workload": workload,
                                "size": size,
                                "status": "pilot_capped",
                                "error": (
                                    f"pilot populate "
                                    f"{record['populate_ns'] / 1e9:.1f}s exceeded "
                                    f"{config['pilot_cap_s']}s budget"
                                ),
                            }
                        )
                (run_dir / "run.json").write_text(json.dumps(run_meta, indent=2) + "\n")
                # Early exit for replicate loop when every implementation
                # for this workload is stopped.
                if all((impl, workload) in stopped for impl in ALL_IMPLEMENTATIONS):
                    break
    (run_dir / "run.json").write_text(json.dumps(run_meta, indent=2) + "\n")
    return run_dir
