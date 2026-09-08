"""Canonical deterministic workload layer (benchmark contract section 1).

Library-independent workload specifications. The payload is created once,
outside every timed region, and shared across adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import scipy.sparse as sp

CANONICAL_SEED = 20260908

SPARSE_STANDARD_SIZES = (1_000, 3_000, 10_000, 30_000, 100_000, 300_000, 1_000_000)
SPARSE_QUICK_SIZES = (1_000, 10_000)

BESS_T = 96
BESS_DT = 0.25
BESS_ETA = 0.95
BESS_P = 2.0
BESS_E = 4.0
BESS_E0 = 2.0

BESS_STANDARD_SIZES = (1, 3, 10, 30, 100, 300)
BESS_QUICK_SIZES = (1, 10)


@dataclass(frozen=True)
class WorkloadCase:
    workload: str
    size: int
    seed: int
    variables: int
    constraints: int
    constraint_nnz: int
    objective_nnz: int
    payload: Any


def sparse_rows_counts(n: int) -> tuple[int, int, int, int]:
    """Return (variables, constraints, constraint_nnz, objective_nnz)."""
    rows = n // 10
    return (n, rows, 10 * rows, n)


def bess_96_counts(b: int, t: int = BESS_T) -> tuple[int, int, int, int]:
    """Return (variables, constraints, constraint_nnz, objective_nnz)."""
    return (b * (3 * t + 1), b * (2 * t + 1), b * (1 + 6 * t), b * (2 * t))


def bess_prices(seed: int, t: int = BESS_T) -> np.ndarray:
    """Deterministic shared price vector in $/MWh, uniform on [20, 80)."""
    rng = np.random.default_rng(seed)
    return 20.0 + 60.0 * rng.random(t)


def make_case(workload: str, size: int, seed: int = CANONICAL_SEED) -> WorkloadCase:
    if workload == "sparse_rows":
        variables, constraints, constraint_nnz, objective_nnz = sparse_rows_counts(size)
        payload = {"n": size, "n_rows": size // 10, "csr": sparse_rows_csr(size)}
    elif workload == "bess_96":
        variables, constraints, constraint_nnz, objective_nnz = bess_96_counts(size)
        payload = {
            "b": size,
            "t": BESS_T,
            "dt": BESS_DT,
            "eta": BESS_ETA,
            "p": BESS_P,
            "e": BESS_E,
            "e0": BESS_E0,
            "prices": bess_prices(seed),
            "csr": bess_96_csr(size, bess_prices(seed)),
        }
    else:
        raise ValueError(f"unknown workload: {workload}")
    return WorkloadCase(
        workload=workload,
        size=size,
        seed=seed,
        variables=variables,
        constraints=constraints,
        constraint_nnz=constraint_nnz,
        objective_nnz=objective_nnz,
        payload=payload,
    )


def sizes_for(workload: str, profile: str) -> tuple[int, ...]:
    if workload == "sparse_rows":
        grid = SPARSE_STANDARD_SIZES if profile == "standard" else SPARSE_QUICK_SIZES
    elif workload == "bess_96":
        grid = BESS_STANDARD_SIZES if profile == "standard" else BESS_QUICK_SIZES
    else:
        raise ValueError(f"unknown workload: {workload}")
    if profile not in ("quick", "standard"):
        raise ValueError(f"unknown profile: {profile}")
    return grid


# ---------------------------------------------------------------------------
# Shared CSR payloads.
#
# Precomputed once per run outside every timed region and handed to adapters
# that use matrix/bulk-row APIs. Timed regions therefore measure library
# ingestion, not index-array assembly. The formulas mirror the contract
# counts exactly; contributing adapters and the Rust core runner share them.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CsrPayload:
    """CSR constraint matrix plus row bounds and objective coefficients."""

    indptr: np.ndarray
    indices: np.ndarray
    data: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    obj_coeff: np.ndarray
    maximize: bool

    def csr_array(self) -> "sp.csr_array":
        return sp.csr_array((self.data, self.indices, self.indptr))


def sparse_rows_csr(n: int) -> CsrPayload:
    """Row r covers x[10r .. 10r+9] with unit coefficients, rhs 10."""
    rows = n // 10
    indptr = np.arange(rows + 1, dtype=np.int64) * 10
    indices = np.arange(rows * 10, dtype=np.int64)
    data = np.ones(rows * 10, dtype=np.float64)
    lower = np.full(rows, -np.inf)
    upper = np.full(rows, 10.0)
    obj_coeff = np.ones(n, dtype=np.float64)
    return CsrPayload(indptr, indices, data, lower, upper, obj_coeff, False)


def bess_96_csr(b: int, prices: np.ndarray, t: int = BESS_T) -> CsrPayload:
    """Flat column order: charge (B*T), discharge (B*T), energy (B*(T+1)).

    Rows per battery: 1 init (energy[b,0] == E0), T balance equalities,
    T mode rows (charge + discharge <= P).
    """
    dt, eta, p, e0 = BESS_DT, BESS_ETA, BESS_P, BESS_E0
    n_vars = b * (3 * t + 1)
    n_rows = b * (2 * t + 1)
    indptr = np.zeros(n_rows + 1, dtype=np.int64)
    idx: list[int] = []
    val: list[float] = []
    lower = np.empty(n_rows)
    upper = np.empty(n_rows)
    obj = np.zeros(n_vars)
    row = 0
    for bb in range(b):
        ch = bb * t
        di = b * t + bb * t
        en = 2 * b * t + bb * (t + 1)
        # init row
        idx.append(en)
        val.append(1.0)
        lower[row] = upper[row] = e0
        row += 1
        for tt in range(t):
            # energy[t+1] - energy[t] - dt*eta*charge + (dt/eta)*discharge == 0
            idx.extend([en + tt + 1, en + tt, ch + tt, di + tt])
            val.extend([1.0, -1.0, -dt * eta, dt / eta])
            lower[row] = upper[row] = 0.0
            row += 1
        for tt in range(t):
            idx.extend([ch + tt, di + tt])
            val.extend([1.0, 1.0])
            lower[row] = -np.inf
            upper[row] = p
            row += 1
        obj[ch : ch + t] = -dt * prices
        obj[di : di + t] = dt * prices
    # Deterministic row widths: 1 per init row, 4 per balance row, 2 per mode row.
    widths = np.array([1] * b + [4] * (b * t) + [2] * (b * t), dtype=np.int64)
    indptr[1:] = np.cumsum(widths)
    return CsrPayload(
        indptr,
        np.asarray(idx, dtype=np.int64),
        np.asarray(val, dtype=np.float64),
        lower,
        upper,
        obj,
        True,
    )
