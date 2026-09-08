"""ROML Python adapters: scalar path and shaped/bulk path.

Scalar path: `Model.var` + scalar expressions + `Model.add`.
Bulk path: `Model.vars` + `add_linear_rows` CSR rows (sparse_rows) or
vectorized `Model.add` over array expressions (bess_96), plus `roml.sum` /
`roml.dot` objectives.

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


def _report(artifact: BuildArtifact, source: str = "construction") -> StructuralReport:
    return StructuralReport(
        implementation=artifact.implementation,
        workload=artifact.case.workload,
        size=artifact.case.size,
        variables=artifact.variables,
        constraints=artifact.constraints,
        constraint_nnz=artifact.constraint_nnz,
        objective_nnz=artifact.objective_nnz,
        count_source=source,
    )


class RomlPythonScalarAdapter:
    implementation_id = "roml_python_scalar"
    construction_path = "scalar: Model.var + scalar expressions + Model.add"

    def warmup(self) -> None:
        m = rm.Model("warmup")
        x = m.var("x", lb=0.0, ub=5.0)
        m.add(x <= 10.0, name="r")
        m.minimize(x)

    def new_model(self, case: WorkloadCase) -> rm.Model:
        return rm.Model(case.workload)

    def populate(self, model: rm.Model, case: WorkloadCase) -> BuildArtifact:
        if case.workload == "sparse_rows":
            return _populate_sparse_scalar(model, case, self.implementation_id)
        if case.workload == "bess_96":
            return _populate_bess_scalar(model, case, self.implementation_id)
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        return _report(artifact)


def _populate_sparse_scalar(
    model: rm.Model, case: WorkloadCase, impl: str
) -> BuildArtifact:
    n = case.payload["n"]
    n_rows = case.payload["n_rows"]
    xs = [model.var(f"x[{i}]", lb=0.0, ub=5.0) for i in range(n)]
    for r in range(n_rows):
        base = 10 * r
        expr = xs[base]
        for k in range(1, 10):
            expr = expr + xs[base + k]
        model.add(expr <= 10.0, name=f"row[{r}]")
    total = xs[0]
    for v in xs[1:]:
        total = total + v
    model.minimize(total)
    return BuildArtifact(model, impl, case, n, n_rows, 10 * n_rows, n)


def _populate_bess_scalar(
    model: rm.Model, case: WorkloadCase, impl: str
) -> BuildArtifact:
    p = case.payload
    b, t, dt, eta = p["b"], p["t"], p["dt"], p["eta"]
    limit, cap, e0, prices = p["p"], p["e"], p["e0"], p["prices"]
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
    total = None
    for bb in range(b):
        for tt in range(t):
            term = prices[tt] * (discharge[bb][tt] - charge[bb][tt])
            total = term if total is None else total + term
    model.maximize(dt * total)
    return BuildArtifact(
        model, impl, case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


class RomlPythonBulkAdapter:
    implementation_id = "roml_python_bulk"
    construction_path = (
        "bulk: Model.vars + add_linear_rows CSR (sparse_rows) or vectorized "
        "Model.add over array expressions (bess_96); roml.sum/roml.dot objectives"
    )

    def warmup(self) -> None:
        m = rm.Model("warmup")
        x = m.vars("x", 3, ub=10.0)
        m.add_linear_rows([0, 3], [0, 1, 2], [1.0, 1.0, 1.0],
                          variables=x, lower=6.0, upper=np.inf)
        m.minimize(rm.sum(x))

    def new_model(self, case: WorkloadCase) -> rm.Model:
        return rm.Model(case.workload)

    def populate(self, model: rm.Model, case: WorkloadCase) -> BuildArtifact:
        if case.workload == "sparse_rows":
            return _populate_sparse_bulk(model, case, self.implementation_id)
        if case.workload == "bess_96":
            return _populate_bess_bulk(model, case, self.implementation_id)
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        return _report(artifact)


def _populate_sparse_bulk(model: rm.Model, case: WorkloadCase, impl: str) -> BuildArtifact:
    csr = case.payload["csr"]
    x = model.vars("x", case.payload["n"], lb=0.0, ub=5.0)
    model.add_linear_rows(
        csr.indptr, csr.indices, csr.data, variables=x,
        lower=csr.lower, upper=csr.upper, name="rows",
    )
    model.minimize(rm.sum(x))
    return BuildArtifact(
        model, impl, case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


def _populate_bess_bulk(model: rm.Model, case: WorkloadCase, impl: str) -> BuildArtifact:
    p = case.payload
    b, t, dt, eta = p["b"], p["t"], p["dt"], p["eta"]
    limit, cap, e0, prices = p["p"], p["e"], p["e0"], p["prices"]
    charge = model.vars("charge", (b, t), lb=0.0, ub=limit)
    discharge = model.vars("discharge", (b, t), lb=0.0, ub=limit)
    energy = model.vars("energy", (b, t + 1), lb=0.0, ub=cap)
    model.add(energy[:, 0] == e0, name="init")
    model.add(
        energy[:, 1:] == energy[:, :-1] + dt * (eta * charge - discharge / eta),
        name="balance",
    )
    model.add(charge + discharge <= limit, name="mode")
    total = None
    for bb in range(b):
        term = rm.dot(prices, discharge[bb, :] - charge[bb, :])
        total = term if total is None else total + term
    model.maximize(dt * total)
    return BuildArtifact(
        model, impl, case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )
