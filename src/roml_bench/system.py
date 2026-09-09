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
    "JULIA_NUM_THREADS": "1",
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


def _sha256_file(path) -> str | None:
    import hashlib
    from pathlib import Path

    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _cargo_roml_revs(repo: str = ".") -> dict[str, str | None]:
    """ROML revs pinned by each workspace member's Cargo.toml plus the lock."""
    import re
    from pathlib import Path

    revs: dict[str, str | None] = {}
    for member in ("rust-core", "rust-store-proto"):
        text = _read(str(Path(repo, member, "Cargo.toml"))) or ""
        m = re.search(r'rev\s*=\s*"([0-9a-f]{40})"', text)
        revs[member] = m.group(1) if m else None
    lock = _read(str(Path(repo, "Cargo.lock"))) or ""
    revs["lock"] = sorted(set(re.findall(r"rev=([0-9a-f]{40})", lock))) or None
    return revs


def roml_artifact_fingerprint(repo: str = ".") -> dict:
    """Hash-level provenance for every ROML representation the suite loads.

    Closes the stale-wheel/stale-binary hole: package version 0.1.0 never
    changes across development commits, so identity must come from the
    checkout SHA plus SHA256 of the exact wheel, the loaded native
    extension, and the release core binary. The validation gate rejects
    any drift before a benchmark run.
    """
    from pathlib import Path

    installed_file: str | None = None
    native_sha: str | None = None
    try:
        import roml

        installed_file = roml.__file__
        root = Path(roml.__file__).parent
        candidates = sorted(
            p for p in root.iterdir()
            if p.suffix == ".so" or p.name.endswith(".so")
        )
        if candidates:
            native_sha = _sha256_file(str(candidates[0]))
    except Exception:
        pass
    installed_wheel_url: str | None = None
    try:
        import importlib.metadata as metadata

        dist = metadata.distribution("roml-python")
        try:
            installed_wheel_url = dist.read_text("direct_url.json")
        except Exception:
            installed_wheel_url = None
    except Exception:
        pass
    wheels_dir = Path(repo, ".cache", "wheels")
    wheel_path: str | None = None
    wheel_sha: str | None = None
    try:
        wheels = sorted(wheels_dir.glob("roml_python-*.whl"))
        if wheels:
            # Absolute: installed direct_url.json records an absolute
            # file:// URL, so a relative fingerprint path would mismatch
            # a correct install (false red).
            wheel_path = str(wheels[-1].resolve())
            wheel_sha = _sha256_file(wheel_path)
    except Exception:
        pass
    return {
        "expected_sha": ROML_SHA,
        "checkout_head": roml_checkout_sha(),
        "cargo_revs": _cargo_roml_revs(repo),
        "installed_file": installed_file,
        "installed_wheel_url": installed_wheel_url,
        "wheel_path": wheel_path,
        "wheel_sha256": wheel_sha,
        "native_ext_sha256": native_sha,
        "core_binary_sha256": _sha256_file(
            str(Path(repo, "target", "release", "roml-bench-core"))
        ),
    }


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
