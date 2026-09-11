"""ROML Python adapters: naive chain, vectorized, and CSR ingestion.

- `roml_python_naive_chain`: `Model.var` + repeated `total = total + v`
  chaining. Each `+` clones the accumulated expression and linearly scans
  its terms, so long chains are O(n^2); this arm measures that naive path,
  not binding overhead.
- `roml_python_vectorized`: `Model.vars` + `add_linear_rows` CSR (sparse_rows) or
  vectorized `Model.add` over array expressions with one fused `rm.dot`
  objective call (bess_96).
- `roml_python_csr`: BESS matrix ingestion from the shared canonical CSR
  via `add_linear_rows` (bess_96 only).

ROML Python exposes no public model-count introspection, so structural
counts are exact adapter construction bookkeeping (count_source
"construction"); mathematical equivalence is proven by the validation
solve gate.
"""

from __future__ import annotations

import numpy as np
import roml as rm

from roml_bench.adapters.base import BuildArtifact, StructuralReport
from roml_bench.workloads import WorkloadCase


def _artifact(model: rm.Model, case: WorkloadCase, impl: str) -> BuildArtifact:
    return BuildArtifact(
        model, impl, case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


def _report(artifact: BuildArtifact) -> StructuralReport:
    return StructuralReport(
        implementation=artifact.implementation,
        workload=artifact.case.workload,
        size=artifact.case.size,
        variables=artifact.variables,
        constraints=artifact.constraints,
        constraint_nnz=artifact.constraint_nnz,
        objective_nnz=artifact.objective_nnz,
        count_source="construction",
    )


class RomlPythonScalarAdapter:
    implementation_id = "roml_python_naive_chain"
    construction_path = (
        "naive scalar chain: Model.var + repeated `total = total + v` "
        "expression chaining (O(n^2) accumulation; measures the naive path, "
        "not binding overhead)"
    )
    supported_workloads = ("sparse_rows", "bess_96")

    def warmup(self) -> None:
        m = rm.Model("warmup")
        x = m.var("x", lb=0.0, ub=5.0)
        m.add(x <= 10.0, name="r")
        m.minimize(x)

    def new_model(self, case: WorkloadCase) -> rm.Model:
        return rm.Model(case.workload)

    def populate(self, model: rm.Model, case: WorkloadCase) -> BuildArtifact:
        for _, step in self.populate_phases(model, case):
            step()
        return _artifact(model, case, self.implementation_id)

    def populate_phases(self, model: rm.Model, case: WorkloadCase):
        stage: dict = {}
        if case.workload == "sparse_rows":
            return [
                ("variables", lambda: stage.update(xs=_naive_sparse_vars(model, case))),
                ("constraints", lambda: _naive_sparse_cons(model, case, stage["xs"])),
                ("objective", lambda: _naive_sparse_obj(model, case, stage["xs"])),
            ]
        if case.workload == "bess_96":
            return [
                ("variables", lambda: stage.update(handles=_naive_bess_vars(model, case))),
                ("constraints", lambda: _naive_bess_cons(model, case, stage["handles"])),
                ("objective", lambda: _naive_bess_obj(model, case, stage["handles"])),
            ]
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        return _report(artifact)


def _naive_sparse_vars(model: rm.Model, case: WorkloadCase):
    n = case.payload["n"]
    return [model.var(f"x[{i}]", lb=0.0, ub=5.0) for i in range(n)]


def _naive_sparse_cons(model: rm.Model, case: WorkloadCase, xs) -> None:
    for r in range(case.payload["n_rows"]):
        base = 10 * r
        expr = xs[base]
        for k in range(1, 10):
            expr = expr + xs[base + k]
        model.add(expr <= 10.0, name=f"row[{r}]")


def _naive_sparse_obj(model: rm.Model, case: WorkloadCase, xs) -> None:
    total = xs[0]
    for v in xs[1:]:
        total = total + v
    model.minimize(total)


def _naive_bess_vars(model: rm.Model, case: WorkloadCase):
    p = case.payload
    b, t, limit, cap = p["b"], p["t"], p["p"], p["e"]
    charge = [
        [model.var(f"charge[{bb},{tt}]", lb=0.0, ub=limit) for tt in range(t)]
        for bb in range(b)
    ]
    discharge = [
        [model.var(f"discharge[{bb},{tt}]", lb=0.0, ub=limit) for tt in range(t)]
        for bb in range(b)
    ]
    energy = [
        [model.var(f"energy[{bb},{tt}]", lb=0.0, ub=cap) for tt in range(t + 1)]
        for bb in range(b)
    ]
    return (charge, discharge, energy)


def _naive_bess_cons(model: rm.Model, case: WorkloadCase, handles) -> None:
    charge, discharge, energy = handles
    p = case.payload
    b, t, dt, eta = p["b"], p["t"], p["dt"], p["eta"]
    limit, e0 = p["p"], p["e0"]
    for bb in range(b):
        model.add(energy[bb][0] == e0, name=f"init[{bb}]")
        for tt in range(t):
            model.add(
                energy[bb][tt + 1]
                == energy[bb][tt] + dt * (eta * charge[bb][tt] - discharge[bb][tt] / eta),
                name=f"balance[{bb},{tt}]",
            )
        for tt in range(t):
            model.add(
                charge[bb][tt] + discharge[bb][tt] <= limit,
                name=f"mode[{bb},{tt}]",
            )


def _naive_bess_obj(model: rm.Model, case: WorkloadCase, handles) -> None:
    charge, discharge, _ = handles
    p = case.payload
    b, t, dt, prices = p["b"], p["t"], p["dt"], p["prices"]
    total = None
    for bb in range(b):
        for tt in range(t):
            term = prices[tt] * (discharge[bb][tt] - charge[bb][tt])
            total = term if total is None else total + term
    model.maximize(dt * total)


class RomlPythonBulkAdapter:
    implementation_id = "roml_python_vectorized"
    construction_path = (
        "vectorized: Model.vars + add_linear_rows CSR (sparse_rows) or vectorized "
        "Model.add over array expressions with one fused rm.dot objective "
        "call (bess_96)"
    )
    supported_workloads = ("sparse_rows", "bess_96")

    def warmup(self) -> None:
        m = rm.Model("warmup")
        x = m.vars("x", 3, ub=10.0)
        m.add_linear_rows([0, 3], [0, 1, 2], [1.0, 1.0, 1.0],
                          variables=x, lower=6.0, upper=np.inf)
        m.minimize(rm.sum(x))

    def new_model(self, case: WorkloadCase) -> rm.Model:
        return rm.Model(case.workload)

    def populate(self, model: rm.Model, case: WorkloadCase) -> BuildArtifact:
        for _, step in self.populate_phases(model, case):
            step()
        return _artifact(model, case, self.implementation_id)

    def populate_phases(self, model: rm.Model, case: WorkloadCase):
        stage: dict = {}
        if case.workload == "sparse_rows":
            return [
                ("variables", lambda: stage.update(x=_bulk_sparse_vars(model, case))),
                ("constraints", lambda: _bulk_sparse_cons(model, case, stage["x"])),
                ("objective", lambda: _bulk_sparse_obj(model, case, stage["x"])),
            ]
        if case.workload == "bess_96":
            return [
                ("variables", lambda: stage.update(handles=_bulk_bess_vars(model, case))),
                ("constraints", lambda: _bulk_bess_cons(model, case, stage["handles"])),
                ("objective", lambda: _bulk_bess_obj(model, case, stage["handles"])),
            ]
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        return _report(artifact)


def _bulk_sparse_vars(model: rm.Model, case: WorkloadCase):
    return model.vars("x", case.payload["n"], lb=0.0, ub=5.0)


def _bulk_sparse_cons(model: rm.Model, case: WorkloadCase, x) -> None:
    csr = case.payload["csr"]
    model.add_linear_rows(
        csr.indptr, csr.indices, csr.data, variables=x,
        lower=csr.lower, upper=csr.upper, name="rows",
    )


def _bulk_sparse_obj(model: rm.Model, case: WorkloadCase, x) -> None:
    model.minimize(rm.sum(x))


def _bulk_bess_vars(model: rm.Model, case: WorkloadCase):
    p = case.payload
    b, t, limit, cap = p["b"], p["t"], p["p"], p["e"]
    charge = model.vars("charge", (b, t), lb=0.0, ub=limit)
    discharge = model.vars("discharge", (b, t), lb=0.0, ub=limit)
    energy = model.vars("energy", (b, t + 1), lb=0.0, ub=cap)
    return (charge, discharge, energy)


def _bulk_bess_cons(model: rm.Model, case: WorkloadCase, handles) -> None:
    charge, discharge, energy = handles
    p = case.payload
    dt, eta, limit, e0 = p["dt"], p["eta"], p["p"], p["e0"]
    model.add(energy[:, 0] == e0, name="init")
    model.add(
        energy[:, 1:] == energy[:, :-1] + dt * (eta * charge - discharge / eta),
        name="balance",
    )
    model.add(charge + discharge <= limit, name="mode")


def _bulk_bess_obj(model: rm.Model, case: WorkloadCase, handles) -> None:
    charge, discharge, _ = handles
    p = case.payload
    # One fused reduction in Rust: no Python-side expression accumulation.
    model.maximize(p["dt"] * rm.dot(p["price_grid"], discharge - charge))


class RomlPythonCsrAdapter:
    implementation_id = "roml_python_csr"
    construction_path = (
        "matrix ingestion: one flat Model.vars + add_linear_rows from the "
        "shared canonical CSR (bess_96 only); objective from the shared "
        "coefficient vector via rm.dot"
    )
    supported_workloads = ("bess_96",)

    def warmup(self) -> None:
        m = rm.Model("warmup")
        x = m.vars("x", 3, ub=10.0)
        m.add_linear_rows([0, 3], [0, 1, 2], [1.0, 1.0, 1.0],
                          variables=x, lower=6.0, upper=np.inf)
        m.minimize(rm.sum(x))

    def new_model(self, case: WorkloadCase) -> rm.Model:
        if case.workload != "bess_96":
            raise ValueError(f"roml_python_csr supports bess_96 only: {case.workload}")
        return rm.Model(case.workload)

    def populate(self, model: rm.Model, case: WorkloadCase) -> BuildArtifact:
        for _, step in self.populate_phases(model, case):
            step()
        return _artifact(model, case, self.implementation_id)

    def populate_phases(self, model: rm.Model, case: WorkloadCase):
        if case.workload != "bess_96":
            raise ValueError(f"roml_python_csr supports bess_96 only: {case.workload}")
        stage: dict = {}
        return [
            ("variables", lambda: stage.update(x=_csr_bess_vars(model, case))),
            ("constraints", lambda: _csr_bess_cons(model, case, stage["x"])),
            ("objective", lambda: _csr_bess_obj(model, case, stage["x"])),
        ]

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        return _report(artifact)


def _csr_bess_vars(model: rm.Model, case: WorkloadCase):
    # Flat namespace (ingestion diagnostic); per-element bounds are exact.
    return model.vars("v", case.variables, lb=case.payload["var_lb"], ub=case.payload["var_ub"])


def _csr_bess_cons(model: rm.Model, case: WorkloadCase, x) -> None:
    csr = case.payload["csr"]
    model.add_linear_rows(
        csr.indptr, csr.indices, csr.data, variables=x,
        lower=csr.lower, upper=csr.upper, name="rows",
    )


def _csr_bess_obj(model: rm.Model, case: WorkloadCase, x) -> None:
    csr = case.payload["csr"]
    model.maximize(rm.dot(csr.obj_coeff, x))
