"""Host environment and provenance capture (contract section 8)."""

from __future__ import annotations

import datetime
import importlib.metadata as metadata
import os
import platform
import subprocess

from roml_bench.schema import ROML_SHA
from roml_bench.workloads import CANONICAL_SEED

THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "RAYON_NUM_THREADS": "1",
}


def _read(path: str) -> str | None:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _cpu_model() -> str | None:
    text = _read("/proc/cpuinfo")
    if text:
        for line in text.splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or None


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for dist in ("roml-python", "pulp", "pyomo", "pyoptinterface", "highspy",
                 "numpy", "scipy", "jinja2", "plotly", "psutil"):
        try:
            versions[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            versions[dist] = None
    try:
        import roml

        versions["roml_import"] = roml.__version__
    except Exception:
        versions["roml_import"] = None
    return versions


def _command_version(argv: list[str]) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else None
    except (OSError, subprocess.SubprocessError):
        return None


def git_sha(repo: str = ".") -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        sha = out.stdout.strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


def roml_checkout_sha() -> str | None:
    return git_sha(".cache/roml")


def collect_environment() -> dict:
    mem_total = mem_available = None
    try:
        import psutil

        vm = psutil.virtual_memory()
        mem_total, mem_available = vm.total, vm.available
    except Exception:
        pass
    return {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "cpu_governor": _read(
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        ),
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "memory_total_bytes": mem_total,
        "memory_available_bytes": mem_available,
        "rustc": _command_version(["rustc", "--version"]),
        "cargo": _command_version(["cargo", "--version"]),
        "packages": _package_versions(),
        "benchmark_sha": git_sha("."),
        "roml_sha_expected": ROML_SHA,
        "roml_checkout_sha": roml_checkout_sha(),
        "canonical_seed": CANONICAL_SEED,
        "thread_env": dict(THREAD_ENV),
    }
