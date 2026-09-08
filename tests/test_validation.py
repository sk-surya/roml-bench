"""Tests for the validation gate helpers."""

from roml_bench.validate import ABS_TOL, REL_TOL, agrees, validation_fingerprint


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
        "status": "ok",
    }
