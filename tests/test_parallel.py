"""Tests for bounded parallel benchmark execution (-j/--jobs).

Scheduling/unit coverage uses deterministic fakes (no real model builds);
a tmp-repo run_profile exercises the real pilot/stop/variant barriers with
a monkeypatched run_child.
"""

import json
import threading
import time

import pytest

from roml_bench import orchestrator
from roml_bench.cli import build_parser
from roml_bench.orchestrator import CpuPool, run_batch

# ---------- CLI contract ----------


def test_cli_jobs_default_is_one():
    args = build_parser().parse_args(["run", "--profile", "quick"])
    assert args.jobs == 1


def test_cli_jobs_short_and_long():
    assert build_parser().parse_args(["run", "--profile", "quick", "-j", "4"]).jobs == 4
    assert build_parser().parse_args(["run", "--profile", "quick", "--jobs", "16"]).jobs == 16


def test_cli_jobs_zero_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--profile", "quick", "-j", "0"])


def test_cli_jobs_negative_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--profile", "quick", "-j", "-1"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--profile", "quick", "--jobs", "-2"])


def test_cli_jobs_non_integer_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--profile", "quick", "-j", "lots"])


# ---------- CpuPool ----------


def test_pool_acquire_release_reuse():
    pool = CpuPool([0, 1])
    assert pool.acquire() == 0
    assert pool.acquire() == 1
    pool.release(1)
    assert pool.acquire() == 1
    pool.release(1)
    pool.release(0)
    assert pool.acquire() == 0


def test_pool_unknown_platform_passes_none_through():
    pool = CpuPool(None)
    assert pool.acquire() is None
    pool.release(None)
    assert pool.acquire() is None
    assert pool.cpus_or_none() is None


def test_pool_reports_cpus():
    assert CpuPool([3, 4, 5]).cpus_or_none() == [3, 4, 5]


# ---------- run_batch: concurrency bound ----------


def _run_batch(tasks, jobs, pool, run_one):
    return run_batch(tasks, jobs=jobs, pool=pool, run_one=run_one)


def _wait_until(predicate, timeout=10.0, message="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(message)


def test_max_active_never_exceeds_jobs_and_reaches_it():
    pool = CpuPool([0, 1, 2])
    active = 0
    max_active = 0
    lock = threading.Lock()

    def run_one(payload, cpu):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            # Proceed once both slots are demonstrably occupied; a serial
            # scheduler would time out here instead.
            _wait_until(lambda: max_active >= 2, message="slots never saturated")
            time.sleep(0.01)
            return {"position": payload}
        finally:
            with lock:
                active -= 1

    tasks = [(i, i) for i in range(3)]
    out = _run_batch(tasks, 2, pool, run_one)
    assert max_active <= 2
    # With 3 tasks and 2 slots the bound must actually saturate.
    assert max_active == 2
    assert [pos for pos, _ in out] == [0, 1, 2]


def test_overlapping_tasks_use_distinct_cpus():
    pool = CpuPool([0, 1])
    started = []
    lock = threading.Lock()

    def run_one(payload, cpu):
        with lock:
            started.append(payload)
        if payload < 2:
            # Force the first two tasks to truly overlap.
            _wait_until(lambda: len(started) >= 2, message="first pair never overlapped")
        start = time.monotonic()
        time.sleep(0.05)
        finish = time.monotonic()
        with lock:
            events.append((start, finish, cpu))
        return {"position": payload}

    events = []
    tasks = [(i, i) for i in range(4)]
    _run_batch(tasks, 2, pool, run_one)
    assert len(events) == 4
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            s1, f1, c1 = events[i]
            s2, f2, c2 = events[j]
            overlaps = s1 < f2 and s2 < f1
            if overlaps:
                assert c1 != c2, f"overlapping tasks share CPU {c1}"
    assert {c for _, _, c in events} == {0, 1}


def test_cpu_released_and_reused_by_later_task():
    pool = CpuPool([7])
    seen = []

    def run_one(payload, cpu):
        seen.append(cpu)
        return {"position": payload}

    _run_batch([(0, "a"), (1, "b")], 1, pool, run_one)
    assert seen == [7, 7]
    assert pool.acquire() == 7


def test_deterministic_order_despite_reverse_finish():
    pool = CpuPool([0, 1, 2, 3])

    def run_one(payload, cpu):
        time.sleep(0.02 * (3 - payload))
        return {"position": payload, "cpu": cpu}

    out = _run_batch([(i, i) for i in range(4)], 4, pool, run_one)
    assert [pos for pos, _ in out] == [0, 1, 2, 3]


def test_failure_isolation_no_sibling_cancellation():
    pool = CpuPool([0, 1, 2])
    completed = []
    lock = threading.Lock()

    def run_one(payload, cpu):
        time.sleep(0.02)
        with lock:
            completed.append(payload)
        if payload == 1:
            return {"position": payload, "status": "error", "error": "boom"}
        return {"position": payload, "status": "ok"}

    out = _run_batch([(i, i) for i in range(3)], 3, pool, run_one)
    assert sorted(completed) == [0, 1, 2]
    assert [pos for pos, _ in out] == [0, 1, 2]
    assert out[1][1]["status"] == "error"


def test_unexpected_exception_collects_then_raises():
    pool = CpuPool([0, 1])
    completed = []
    lock = threading.Lock()

    def run_one(payload, cpu):
        time.sleep(0.01)
        with lock:
            completed.append(payload)
        if payload == 0:
            raise RuntimeError("programming error")
        return {"position": payload}

    with pytest.raises(RuntimeError, match="programming error"):
        _run_batch([(0, 0), (1, 1)], 2, pool, run_one)
    assert sorted(completed) == [0, 1]


# ---------- run_profile barriers with fake children ----------


def _write_validation(tmp_path, monkeypatch):
    from roml_bench.schema import ROML_SHA
    from roml_bench.system import collect_environment

    monkeypatch.chdir(tmp_path)
    # Deterministic git identity: tmp dirs are not repos.
    monkeypatch.setattr(orchestrator, "git_sha", lambda repo=".": "unknown")
    # Deterministic ROML artifacts: the gate fingerprints hashes of the real
    # checkout/wheel/binary, none of which exist in the tmp repo.
    sentinel = {"test": "artifacts"}
    monkeypatch.setattr(
        orchestrator, "roml_artifact_fingerprint", lambda repo=".": sentinel
    )
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "validation.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "benchmark_sha": "unknown",
                "roml_checkout_sha": ROML_SHA,
                "roml_artifacts": sentinel,
                "environment": {
                    "packages": collect_environment()["packages"],
                },
            }
        )
    )


def _fake_ok(implementation, workload, size, replicate, variant="canonical", cpu=None):
    return {
        "schema_version": 1,
        "implementation": implementation,
        "workload": workload,
        "size": size,
        "replicate": replicate,
        "variant": variant,
        "cpu": cpu,
        "status": "ok",
        "error": None,
        "populate_ns": 1_000_000,
    }


def _call_log():
    return []


def _install_fake(monkeypatch, log, behavior):
    def fake(implementation, workload, size, seed, replicate, run_id,
             benchmark_sha, cpu, wall_timeout_s, rss_ceiling_bytes,
             csr_variant="canonical"):
        log.append((workload, size, replicate, implementation, csr_variant, cpu))
        return behavior(implementation, workload, size, replicate, csr_variant, cpu)

    monkeypatch.setattr(orchestrator, "run_child", fake)


def test_pilot_barrier_no_speculative_replicate_one(tmp_path, monkeypatch):
    _write_validation(tmp_path, monkeypatch)
    log = _call_log()
    lock = threading.Lock()

    def behavior(implementation, workload, size, replicate, variant, cpu):
        if workload == "sparse_rows" and size == 1000 and replicate == 0:
            time.sleep(0.05)
        return _fake_ok(implementation, workload, size, replicate, variant, cpu)

    def fake(*args, **kwargs):
        workload, size, replicate, implementation = args[1], args[2], args[4], args[0]
        rec = behavior(
            implementation, workload, size, replicate,
            kwargs.get("csr_variant", "canonical"), args[7],
        )
        with lock:
            log.append((workload, size, replicate, implementation))
        return rec

    monkeypatch.setattr(orchestrator, "run_child",
                        lambda *a, **k: fake(*a, **k))
    # Replicate-1 calls must all come after every replicate-0 call for
    # the same (workload, size): the rep-0 sleep widens any race window.
    orchestrator.run_profile("quick", run_id="pilot-probe", repo=".", jobs=4)
    by_point = {}
    for workload, size, replicate, _ in log:
        by_point.setdefault((workload, size, replicate), []).append(1)
    # Every (workload, size) ran replicate 0 fully before replicate 1 began:
    # positions in the log prove it.
    for workload, size in {(w, s) for w, s, _, _ in log}:
        rep0_last = max(i for i, (w, s, r, _) in enumerate(log)
                        if (w, s, r) == (workload, size, 0))
        rep1_firsts = [i for i, (w, s, r, _) in enumerate(log)
                       if (w, s, r) == (workload, size, 1)]
        if rep1_firsts:
            assert rep0_last < min(rep1_firsts), (workload, size)


def test_pilot_capped_implementation_gets_no_replicate_one(tmp_path, monkeypatch):
    _write_validation(tmp_path, monkeypatch)
    log = _call_log()

    def behavior(implementation, workload, size, replicate, variant, cpu):
        if (implementation, workload, size, replicate) == ("pulp_python", "sparse_rows", 1000, 0):
            rec = _fake_ok(implementation, workload, size, replicate, variant, cpu)
            rec["populate_ns"] = 61_000_000_000
            return rec
        return _fake_ok(implementation, workload, size, replicate, variant, cpu)

    _install_fake(monkeypatch, log, behavior)
    orchestrator.run_profile("standard", run_id="pilot-cap", repo=".", jobs=4)
    later = [(w, s, r, i) for (w, s, r, i, _, _) in log
             if i == "pulp_python" and w == "sparse_rows" and not (s == 1000 and r == 0)]
    assert later == []
    # Unaffected implementations still ran larger sizes.
    assert any(w == "sparse_rows" and s == 3000 for (w, s, _, _, _, _) in log)


def test_canonical_error_stops_later_points_only(tmp_path, monkeypatch):
    _write_validation(tmp_path, monkeypatch)
    log = _call_log()

    def behavior(implementation, workload, size, replicate, variant, cpu):
        if ((implementation, workload) == ("pulp_python", "sparse_rows")
                and (size, replicate) == (1000, 0)):
            rec = _fake_ok(implementation, workload, size, replicate, variant, cpu)
            rec["status"] = "error"
            rec["error"] = "boom"
            return rec
        return _fake_ok(implementation, workload, size, replicate, variant, cpu)

    _install_fake(monkeypatch, log, behavior)
    orchestrator.run_profile("quick", run_id="stop-probe", repo=".", jobs=4)
    assert not any(i == "pulp_python" and w == "sparse_rows" and (s, r) != (1000, 0)
                   for (w, s, r, i, _, _) in log)
    # Other workloads for the same implementation continue.
    assert any(i == "pulp_python" and w == "bess_96" for (w, _, _, i, _, _) in log)
    # Raw records preserve the error.
    raws = [(json.loads(line)) for line in
            (tmp_path / "results" / "runs" / "stop-probe" / "raw.jsonl").read_text().splitlines()]
    assert any(r["status"] == "error" and r["implementation"] == "pulp_python" for r in raws)


def test_variant_failure_is_variant_scoped(tmp_path, monkeypatch):
    from roml_bench import orchestrator as orch

    _write_validation(tmp_path, monkeypatch)
    log = _call_log()

    def behavior(implementation, workload, size, replicate, variant, cpu):
        if variant == "shuffled":
            rec = _fake_ok(implementation, workload, size, replicate, variant, cpu)
            rec["status"] = "error"
            rec["error"] = "variant boom"
            return rec
        return _fake_ok(implementation, workload, size, replicate, variant, cpu)

    _install_fake(monkeypatch, log, behavior)
    run_meta = {"points": {}, "stopped": []}
    raw_path = tmp_path / "raw.jsonl"
    config = {"replicates": 2, "wall_timeout_s": 5, "rss_ceiling_bytes": 1, "pilot_cap_s": None}
    with open(raw_path, "w") as raw:
        orch._run_variants(raw, tmp_path, run_meta, set(), 20260908,
                           "variant-probe", "sha", config)
    calls = [(w, s, v, r) for (w, s, r, _, v, _) in log]
    # Shuffled failed at replicate 0: no shuffled replicate 1 for anyone.
    assert not any(v == "shuffled" and r == 1 for (_, _, v, r) in calls)
    # Duplicated variants still ran both replicates.
    assert any(v == "duplicated" and r == 1 for (_, _, v, r) in calls)


def test_jobs_one_matches_jobs_four_ordering(tmp_path, monkeypatch):
    _write_validation(tmp_path, monkeypatch)

    def run_once(jobs, run_id):
        log = _call_log()
        _install_fake(monkeypatch, log,
                      lambda i, w, s, r, v, c: _fake_ok(i, w, s, r, v, c))
        orchestrator.run_profile("quick", run_id=run_id, repo=".", jobs=jobs)
        rows = [(json.loads(line)) for line in
                (tmp_path / "results" / "runs" / run_id / "raw.jsonl").read_text().splitlines()]
        order = [(r["workload"], r["size"], r["replicate"], r["implementation"], r["variant"])
                 for r in rows]
        cpus = [(r["workload"], r["size"], r["replicate"], r["cpu"]) for r in rows]
        return order, cpus

    order1, cpus1 = run_once(1, "order-one")
    order4, cpus4 = run_once(4, "order-four")
    assert order1 == order4
    first_cpu = cpus1[0][3]
    assert all(c == first_cpu for (_, _, _, c) in cpus1)


def test_oversubscription_rejected_before_execution(tmp_path, monkeypatch):
    _write_validation(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator, "allowed_cpus", lambda: [0, 1, 2, 3])
    called = []

    def fake(*args, **kwargs):
        called.append(args)
        return _fake_ok(args[0], args[1], args[2], args[4])

    monkeypatch.setattr(orchestrator, "run_child", fake)
    with pytest.raises(RuntimeError, match="(?i)oversubscrib|more .* than|CPUs"):
        orchestrator.run_profile("quick", run_id="never-created", repo=".", jobs=5)
    assert called == []
    assert not (tmp_path / "results" / "runs" / "never-created").exists()


def test_run_profile_rejects_jobs_zero(tmp_path, monkeypatch):
    _write_validation(tmp_path, monkeypatch)
    with pytest.raises((ValueError, RuntimeError)):
        orchestrator.run_profile("quick", run_id="x", repo=".", jobs=0)
