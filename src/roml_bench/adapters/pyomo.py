"""Pyomo adapter using indexed components and quicksum.

Construction: ConcreteModel + indexed Var/Constraint with rules +
quicksum expressions. Validation solves use appsi_highs (highspy-backed).
"""

from __future__ import annotations

import pyomo.environ as pyo
from pyomo.core.expr.visitor import identify_variables

from roml_bench.adapters.base import BuildArtifact, StructuralReport
from roml_bench.workloads import WorkloadCase


class PyomoAdapter:
    implementation_id = "pyomo_python"
    construction_path = "ConcreteModel + indexed Var/Constraint rules + quicksum"
    supported_workloads = ("sparse_rows", "bess_96")

    def warmup(self) -> None:
        m = pyo.ConcreteModel()
        m.x = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, 5))
        m.r = pyo.Constraint(expr=m.x <= 10.0)
        m.obj = pyo.Objective(expr=m.x, sense=pyo.minimize)

    def new_model(self, case: WorkloadCase) -> pyo.ConcreteModel:
        return pyo.ConcreteModel()

    def populate(self, model: pyo.ConcreteModel, case: WorkloadCase) -> BuildArtifact:
        for _, step in self.populate_phases(model, case):
            step()
        return _artifact(model, case)

    def populate_phases(self, model: pyo.ConcreteModel, case: WorkloadCase):
        if case.workload == "sparse_rows":
            return [
                ("variables", lambda: _sparse_vars(model, case)),
                ("constraints", lambda: _sparse_cons(model, case)),
                ("objective", lambda: _sparse_obj(model, case)),
            ]
        if case.workload == "bess_96":
            return [
                ("variables", lambda: _bess_vars(model, case)),
                ("constraints", lambda: _bess_cons(model, case)),
                ("objective", lambda: _bess_obj(model, case)),
            ]
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        m = artifact.model
        variables = sum(1 for _ in m.component_data_objects(pyo.Var))
        constraints = sum(1 for _ in m.component_data_objects(pyo.Constraint))
        try:
            objectives = list(m.component_data_objects(pyo.Objective))
            objective_nnz = (
                len(set(identify_variables(objectives[0].expr))) if objectives else None
            )
            constraint_nnz = sum(
                len(set(identify_variables(c.body)))
                for c in m.component_data_objects(pyo.Constraint)
            )
        except Exception:
            objective_nnz = None
            constraint_nnz = None
        return StructuralReport(
            implementation=artifact.implementation,
            workload=case.workload,
            size=case.size,
            variables=variables,
            constraints=constraints,
            constraint_nnz=constraint_nnz,
            objective_nnz=objective_nnz,
            count_source="introspection",
        )


def _artifact(model: pyo.ConcreteModel, case: WorkloadCase) -> BuildArtifact:
    return BuildArtifact(
        model, "pyomo_python", case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


def _sparse_vars(model: pyo.ConcreteModel, case: WorkloadCase) -> None:
    n = case.payload["n"]
    model.I = pyo.Set(initialize=range(n))
    model.R = pyo.Set(initialize=range(case.payload["n_rows"]))
    model.x = pyo.Var(model.I, domain=pyo.NonNegativeReals, bounds=(0, 5))


def _sparse_cons(model: pyo.ConcreteModel, case: WorkloadCase) -> None:
    def row_rule(m: pyo.ConcreteModel, r: int) -> pyo.Constraint:
        base = 10 * r
        return pyo.quicksum(m.x[base + k] for k in range(10)) <= 10.0

    model.rows = pyo.Constraint(model.R, rule=row_rule)


def _sparse_obj(model: pyo.ConcreteModel, case: WorkloadCase) -> None:
    model.obj = pyo.Objective(
        expr=pyo.quicksum(model.x[i] for i in model.I), sense=pyo.minimize
    )


def _bess_vars(model: pyo.ConcreteModel, case: WorkloadCase) -> None:
    p = case.payload
    b, t, limit, cap = p["b"], p["t"], p["p"], p["e"]
    model.B = pyo.Set(initialize=range(b))
    model.T = pyo.Set(initialize=range(t))
    model.Tp1 = pyo.Set(initialize=range(t + 1))
    model.charge = pyo.Var(model.B, model.T, domain=pyo.NonNegativeReals, bounds=(0, limit))
    model.discharge = pyo.Var(
        model.B, model.T, domain=pyo.NonNegativeReals, bounds=(0, limit)
    )
    model.energy = pyo.Var(
        model.B, model.Tp1, domain=pyo.NonNegativeReals, bounds=(0, cap)
    )


def _bess_cons(model: pyo.ConcreteModel, case: WorkloadCase) -> None:
    p = case.payload
    dt, eta, limit, e0 = p["dt"], p["eta"], p["p"], p["e0"]

    def init_rule(m: pyo.ConcreteModel, bb: int) -> pyo.Constraint:
        return m.energy[bb, 0] == e0

    def balance_rule(m: pyo.ConcreteModel, bb: int, tt: int) -> pyo.Constraint:
        return (
            m.energy[bb, tt + 1]
            == m.energy[bb, tt] + dt * (eta * m.charge[bb, tt] - m.discharge[bb, tt] / eta)
        )

    def mode_rule(m: pyo.ConcreteModel, bb: int, tt: int) -> pyo.Constraint:
        return m.charge[bb, tt] + m.discharge[bb, tt] <= limit

    model.init = pyo.Constraint(model.B, rule=init_rule)
    model.balance = pyo.Constraint(model.B, model.T, rule=balance_rule)
    model.mode = pyo.Constraint(model.B, model.T, rule=mode_rule)


def _bess_obj(model: pyo.ConcreteModel, case: WorkloadCase) -> None:
    p = case.payload
    dt, prices = p["dt"], p["prices"]
    model.obj = pyo.Objective(
        expr=pyo.quicksum(
            dt * float(prices[tt]) * (model.discharge[bb, tt] - model.charge[bb, tt])
            for bb in model.B
            for tt in model.T
        ),
        sense=pyo.maximize,
    )


def solve_objective(model: pyo.ConcreteModel) -> float:
    """Solve a validation instance with appsi_highs; return objective value."""
    solver = pyo.SolverFactory("appsi_highs")
    result = solver.solve(model)
    model.solutions.load_from(result)
    value = pyo.value(model.obj)
    return float(value)
