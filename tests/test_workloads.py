"""Tests for the canonical workload layer."""

import numpy as np

from roml_bench.workloads import (
    BESS_DT,
    BESS_E,
    BESS_E0,
    BESS_ETA,
    BESS_P,
    BESS_T,
    bess_96_counts,
    bess_prices,
    make_case,
    sparse_rows_counts,
)


def test_sparse_rows_counts_match_contract():
    assert sparse_rows_counts(1000) == (1000, 100, 1000, 1000)
    assert sparse_rows_counts(1005) == (1005, 100, 1000, 1005)


def test_bess_96_counts_match_contract():
    assert BESS_T == 96
    assert bess_96_counts(10) == (2890, 1930, 5770, 1920)
    assert bess_96_counts(1) == (289, 193, 577, 192)


def test_make_case_sparse_rows():
    case = make_case("sparse_rows", 1000, seed=20260908)
    assert (case.variables, case.constraints, case.constraint_nnz, case.objective_nnz) == (
        1000,
        100,
        1000,
        1000,
    )
    assert case.payload["n"] == 1000
    assert case.payload["n_rows"] == 100
    csr = case.payload["csr"]
    assert csr.indptr.shape == (101,)
    assert csr.indices.shape == (1000,)
    assert csr.data.shape == (1000,)
    assert bool((csr.upper == 10.0).all())
    assert bool((csr.obj_coeff == 1.0).all())


def test_bess_price_payload_deterministic():
    first = make_case("bess_96", 10, seed=20260908).payload["prices"]
    second = make_case("bess_96", 10, seed=20260908).payload["prices"]
    assert isinstance(first, np.ndarray)
    assert first.shape == (96,)
    assert np.array_equal(first, second)
    assert bool(np.all(first >= 20.0)) and bool(np.all(first < 80.0))


def test_bess_different_seed_changes_prices_not_structure():
    a = make_case("bess_96", 10, seed=20260908)
    b = make_case("bess_96", 10, seed=7)
    assert not np.array_equal(a.payload["prices"], b.payload["prices"])
    assert (a.variables, a.constraints, a.constraint_nnz, a.objective_nnz) == (
        b.variables,
        b.constraints,
        b.constraint_nnz,
        b.objective_nnz,
    )
    assert (BESS_DT, BESS_ETA, BESS_P, BESS_E, BESS_E0) == (0.25, 0.95, 2.0, 4.0, 2.0)
    assert bess_prices(20260908).tobytes() == bess_prices(20260908).tobytes()


def test_csr_payloads_match_contract_counts():
    from roml_bench.workloads import bess_96_csr, sparse_rows_csr

    csr = sparse_rows_csr(1000)
    assert csr.indptr[-1] == 1000 == len(csr.indices) == len(csr.data)
    assert len(csr.lower) == len(csr.upper) == 100
    assert csr.csr_array().shape == (100, 1000)
    assert csr.csr_array().nnz == 1000

    prices = bess_prices(20260908)
    bcsr = bess_96_csr(10, prices)
    assert (bcsr.indptr[-1], len(bcsr.lower), len(bcsr.obj_coeff)) == (5770, 1930, 2890)
    assert bcsr.csr_array().shape == (1930, 2890)
    assert bcsr.csr_array().nnz == 5770
    # Row groups are contiguous: inits, then balance, then mode.
    widths = np.diff(bcsr.indptr)
    assert widths.tolist() == [1] * 10 + [4] * 960 + [2] * 960
    # init row of battery 0 pins energy[0,0] to E0
    assert bcsr.lower[0] == bcsr.upper[0] == BESS_E0
    assert bcsr.indices[0] == 2 * 10 * 96
    # First balance row (battery 0, t=0): {en1, en0, ch, di} with exact coefficients.
    seg = slice(bcsr.indptr[10], bcsr.indptr[11])
    cols = set(bcsr.indices[seg].tolist())
    assert cols == {2 * 10 * 96 + 1, 2 * 10 * 96, 0, 10 * 96}
    coef = dict(zip(bcsr.indices[seg].tolist(), bcsr.data[seg].tolist()))
    assert coef[2 * 10 * 96 + 1] == 1.0
    assert coef[2 * 10 * 96] == -1.0
    assert coef[0] == -(0.25 * 0.95)
    assert coef[10 * 96] == 0.25 / 0.95
    assert bcsr.lower[10] == bcsr.upper[10] == 0.0
    # First mode row (battery 0, t=0).
    assert bcsr.lower[10 + 960] == float("-inf")
    assert bcsr.upper[10 + 960] == BESS_P
    seg = slice(bcsr.indptr[10 + 960], bcsr.indptr[10 + 961])
    assert set(bcsr.indices[seg].tolist()) == {0, 10 * 96}
    # objective coefficients follow dt * price
    assert bcsr.obj_coeff[0] == -(0.25 * prices[0])
    assert bcsr.obj_coeff[10 * 96] == 0.25 * prices[0]
    assert bcsr.maximize is True and csr.maximize is False
