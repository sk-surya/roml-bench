"""Tests for the validation gate helpers."""

import json

from roml_bench.schema import ROML_SHA
from roml_bench.validate import (
    ABS_TOL,
    REL_TOL,
    agrees,
    validate_roml_artifacts,
    validation_fingerprint,
)


def test_agrees_tolerance():
    assert agrees(1.0, 1.0 + 1e-9)
    assert agrees(0.0, 1e-8)
    assert not agrees(1.0, 1.0 + 1e-5)
    assert not agrees(1000.0, 1000.0 + 1.0)
    assert ABS_TOL == REL_TOL == 1e-7


def test_validation_fingerprint_selects_identity():
    validation = {
        "benchmark_sha": "abc",
        "roml_checkout_sha": "def",
        "environment": {"packages": {"pulp": "3.3.1"}},
        "status": "ok",
        "extra": "ignored",
    }
    fingerprint = validation_fingerprint(validation)
    assert fingerprint == {
        "benchmark_sha": "abc",
        "roml_checkout_sha": "def",
        "packages": {"pulp": "3.3.1"},
        "roml_artifacts": None,
        "status": "ok",
    }


def _good_artifacts(tmp_path):
    """A fully consistent artifact set backed by real tmp files."""
    import hashlib
    import zipfile

    venv = tmp_path / "venv"
    installed = venv / "lib" / "site-packages" / "roml" / "__init__.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("x = 1\n")
    so_bytes = b"fake-native-extension"
    wheel = tmp_path / "roml_python-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("roml/_native.so", so_bytes)
    return {
        "expected_sha": ROML_SHA,
        "checkout_head": ROML_SHA,
        "cargo_revs": {
            "rust-core": ROML_SHA,
            "rust-store-proto": ROML_SHA,
            "lock": [ROML_SHA],
        },
        "installed_file": str(installed),
        "installed_wheel_url": json.dumps({"url": wheel.as_uri()}),
        "wheel_path": str(wheel),
        "wheel_sha256": "0" * 64,
        "native_ext_sha256": hashlib.sha256(so_bytes).hexdigest(),
        "core_binary_sha256": "1" * 64,
    }, str(venv)


def test_artifacts_good_set_passes(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    assert validate_roml_artifacts(artifacts, venv_prefix=venv) == []


def test_artifacts_wrong_checkout_fails(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    artifacts["checkout_head"] = "0" * 40
    assert validate_roml_artifacts(artifacts, venv_prefix=venv) != []


def test_artifacts_wrong_cargo_pin_fails(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    artifacts["cargo_revs"]["rust-core"] = "0" * 40
    assert validate_roml_artifacts(artifacts, venv_prefix=venv) != []


def test_artifacts_wrong_lock_sha_fails(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    artifacts["cargo_revs"]["lock"] = [ROML_SHA, "0" * 40]
    assert validate_roml_artifacts(artifacts, venv_prefix=venv) != []


def test_artifacts_missing_binary_fails(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    artifacts["core_binary_sha256"] = None
    assert validate_roml_artifacts(artifacts, venv_prefix=venv) != []


def test_artifacts_native_wheel_mismatch_fails(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    artifacts["native_ext_sha256"] = "2" * 64
    problems = validate_roml_artifacts(artifacts, venv_prefix=venv)
    assert any("native extension" in p for p in problems)


def test_artifacts_direct_url_mismatch_fails(tmp_path):
    artifacts, venv = _good_artifacts(tmp_path)
    artifacts["installed_wheel_url"] = json.dumps(
        {"url": "file:///elsewhere/other.whl"}
    )
    problems = validate_roml_artifacts(artifacts, venv_prefix=venv)
    assert any("direct_url" in p for p in problems)


def test_artifacts_outside_venv_fails(tmp_path):
    artifacts, _venv = _good_artifacts(tmp_path)
    assert validate_roml_artifacts(artifacts, venv_prefix="/elsewhere") != []
