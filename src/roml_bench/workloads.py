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
        prices = bess_prices(seed)
        payload = {
            "b": size,
            "t": BESS_T,
            "dt": BESS_DT,
            "eta": BESS_ETA,
            "p": BESS_P,
            "e": BESS_E,
            "e0": BESS_E0,
            "prices": prices,
            # Contiguous (B, T) price grid for the fused one-call objective.
            "price_grid": np.tile(prices, (size, 1)),
            "csr": bess_96_csr(size, prices),
            # Flat variable bounds in CSR column order
            # (charge B*T @ P, discharge B*T @ P, energy B*(T+1) @ E).
            "var_lb": np.zeros(size * (3 * BESS_T + 1)),
            "var_ub": np.concatenate([
                np.full(size * BESS_T, BESS_P),
                np.full(size * BESS_T, BESS_P),
                np.full(size * (BESS_T + 1), BESS_E),
            ]),
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
    if profile not in ("quick", "standard", "forensic"):
        raise ValueError(f"unknown profile: {profile}")
    standard = profile in ("standard", "forensic")
    if workload == "sparse_rows":
        grid = SPARSE_STANDARD_SIZES if standard else SPARSE_QUICK_SIZES
    elif workload == "bess_96":
        grid = BESS_STANDARD_SIZES if standard else BESS_QUICK_SIZES
    else:
        raise ValueError(f"unknown workload: {workload}")
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

    Rows are grouped: B init rows (energy[b,0] == E0), then B*T balance
    equalities, then B*T mode rows (charge + discharge <= P). Row groups
    must stay contiguous because matrix consumers slice by sense.
    """
    dt, eta, p, e0 = BESS_DT, BESS_ETA, BESS_P, BESS_E0
    n_vars = b * (3 * t + 1)
    obj = np.zeros(n_vars)
    for bb in range(b):
        obj[bb * t : bb * t + t] = -dt * prices
        obj[b * t + bb * t : b * t + bb * t + t] = dt * prices

    def col_charge(bb: int, tt: int) -> int:
        return bb * t + tt

    def col_discharge(bb: int, tt: int) -> int:
        return b * t + bb * t + tt

    def col_energy(bb: int, tt: int) -> int:
        return 2 * b * t + bb * (t + 1) + tt

    indptr = np.zeros(b * (2 * t + 1) + 1, dtype=np.int64)
    indices = np.zeros(b * (1 + 6 * t), dtype=np.int64)
    data = np.zeros(b * (1 + 6 * t), dtype=np.float64)
    lower = np.empty(b * (2 * t + 1))
    upper = np.empty(b * (2 * t + 1))
    pos = 0
    row = 0
    for bb in range(b):  # init rows
        indices[pos] = col_energy(bb, 0)
        data[pos] = 1.0
        pos += 1
        lower[row] = upper[row] = e0
        row += 1
        indptr[row] = pos
    for bb in range(b):  # balance rows
        for tt in range(t):
            # energy[t+1] - energy[t] - dt*eta*charge + (dt/eta)*discharge == 0
            indices[pos : pos + 4] = (
                col_energy(bb, tt + 1),
                col_energy(bb, tt),
                col_charge(bb, tt),
                col_discharge(bb, tt),
            )
            data[pos : pos + 4] = (1.0, -1.0, -dt * eta, dt / eta)
            pos += 4
            lower[row] = upper[row] = 0.0
            row += 1
            indptr[row] = pos
    for bb in range(b):  # mode rows
        for tt in range(t):
            indices[pos : pos + 2] = (col_charge(bb, tt), col_discharge(bb, tt))
            data[pos : pos + 2] = (1.0, 1.0)
            pos += 2
            lower[row] = -np.inf
            upper[row] = p
            row += 1
            indptr[row] = pos
    return CsrPayload(indptr, indices, data, lower, upper, obj, True)


def apply_csr_variant(
    case: WorkloadCase, variant: str, seed: int = CANONICAL_SEED
) -> tuple[WorkloadCase, int]:
    """Return a copy of `case` with a transformed CSR payload plus actual nnz.

    `shuffled` permutes in-row column order (unique, unsorted) to defeat any
    sorted-input fast path. `duplicated` doubles every entry to exercise the
    duplicate-accumulation path; the returned actual nnz is twice canonical.
    Applied outside every timed region from a seeded RNG.
    """
    if variant not in ("shuffled", "duplicated"):
        raise ValueError(f"unknown CSR variant: {variant}")
    csr: CsrPayload = case.payload["csr"]
    rng = np.random.default_rng(seed + hash(variant) % (2**31))
    indptr = csr.indptr.copy()
    if variant == "shuffled":
        indices = csr.indices.copy()
        data = csr.data.copy()
        for r in range(len(indptr) - 1):
            seg = slice(indptr[r], indptr[r + 1])
            perm = rng.permutation(seg.stop - seg.start)
            indices[seg] = indices[seg][perm]
            data[seg] = data[seg][perm]
        actual_nnz = int(indptr[-1])
    else:
        widths = np.diff(indptr)
        new_indptr = np.zeros_like(indptr)
        new_indptr[1:] = np.cumsum(2 * widths)
        indices = np.empty(new_indptr[-1], dtype=np.int64)
        data = np.empty(new_indptr[-1], dtype=np.float64)
        for r in range(len(indptr) - 1):
            seg = slice(indptr[r], indptr[r + 1])
            out = slice(new_indptr[r], new_indptr[r + 1])
            indices[out] = np.concatenate([csr.indices[seg], csr.indices[seg]])
            data[out] = np.concatenate([csr.data[seg], csr.data[seg]])
        indptr = new_indptr
        actual_nnz = int(indptr[-1])
    new_csr = CsrPayload(
        indptr, indices, data, csr.lower.copy(), csr.upper.copy(),
        csr.obj_coeff.copy(), csr.maximize,
    )
    payload = dict(case.payload)
    payload["csr"] = new_csr
    return (
        WorkloadCase(
            workload=case.workload, size=case.size, seed=case.seed,
            variables=case.variables, constraints=case.constraints,
            constraint_nnz=case.constraint_nnz, objective_nnz=case.objective_nnz,
            payload=payload,
        ),
        actual_nnz,
    )
