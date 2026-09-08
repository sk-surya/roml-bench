"""PuLP adapter using the documented efficient public API.

Construction: LpVariable.dicts + lpSum helpers + in-place problem building.
Validation solves use the bundled CBC binary (PULP_CBC_CMD); PuLP's HiGHS
command interface needs an external `highs` binary that is not part of the
pinned environment.
"""

from __future__ import annotations

import pulp
from pulp import LpMaximize, LpMinimize, LpProblem, lpSum

from roml_bench.adapters.base import BuildArtifact, StructuralReport
from roml_bench.workloads import WorkloadCase


class PulpAdapter:
    implementation_id = "pulp_python"
    construction_path = "LpProblem.add_variable_dicts + lpSum + LpProblem"
    supported_workloads = ("sparse_rows", "bess_96")

    def warmup(self) -> None:
        prob = LpProblem("warmup", LpMinimize)
        x = prob.add_variable("x", lowBound=0, upBound=5)
        prob += x <= 10.0, "r"
        prob += x

    def new_model(self, case: WorkloadCase) -> LpProblem:
        sense = LpMaximize if case.workload == "bess_96" else LpMinimize
        return LpProblem(case.workload, sense)

    def populate(self, model: LpProblem, case: WorkloadCase) -> BuildArtifact:
        for _, step in self.populate_phases(model, case):
            step()
        return _artifact(model, case)

    def populate_phases(self, model: LpProblem, case: WorkloadCase):
        stage: dict = {}
        if case.workload == "sparse_rows":
            return [
                ("variables", lambda: stage.update(xs=_sparse_vars(model, case))),
                ("constraints", lambda: _sparse_cons(model, case, stage["xs"])),
                ("objective", lambda: _sparse_obj(model, case, stage["xs"])),
            ]
        if case.workload == "bess_96":
            return [
                ("variables", lambda: stage.update(handles=_bess_vars(model, case))),
                ("constraints", lambda: _bess_cons(model, case, stage["handles"])),
                ("objective", lambda: _bess_obj(model, case, stage["handles"])),
            ]
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact: BuildArtifact, case: WorkloadCase) -> StructuralReport:
        prob: LpProblem = artifact.model
        constraints = prob.constraints()
        variables = len(prob.variables())
        objective_nnz = len(prob.objective)
        constraint_nnz = sum(len(c) for c in constraints)
        return StructuralReport(
            implementation=artifact.implementation,
            workload=case.workload,
            size=case.size,
            variables=variables,
            constraints=len(constraints),
            constraint_nnz=constraint_nnz,
            objective_nnz=objective_nnz,
            count_source="introspection",
        )


def _artifact(model: LpProblem, case: WorkloadCase) -> BuildArtifact:
    return BuildArtifact(
        model, "pulp_python", case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


def _sparse_vars(model: LpProblem, case: WorkloadCase):
    n = case.payload["n"]
    return model.add_variable_dicts("x", range(n), lowBound=0, upBound=5)


def _sparse_cons(model: LpProblem, case: WorkloadCase, xs) -> None:
    for r in range(case.payload["n_rows"]):
        base = 10 * r
        model += lpSum(xs[base + k] for k in range(10)) <= 10.0, f"row_{r}"


def _sparse_obj(model: LpProblem, case: WorkloadCase, xs) -> None:
    model += lpSum(xs[i] for i in range(case.payload["n"]))


def _bess_vars(model: LpProblem, case: WorkloadCase):
    p = case.payload
    b, t, limit, cap = p["b"], p["t"], p["p"], p["e"]
    charge = model.add_variable_dicts(
        "charge", (range(b), range(t)), lowBound=0, upBound=limit
    )
    discharge = model.add_variable_dicts(
        "discharge", (range(b), range(t)), lowBound=0, upBound=limit
    )
    energy = model.add_variable_dicts(
        "energy", (range(b), range(t + 1)), lowBound=0, upBound=cap
    )
    return (charge, discharge, energy)


def _bess_cons(model: LpProblem, case: WorkloadCase, handles) -> None:
    charge, discharge, energy = handles
    p = case.payload
    b, t, dt, eta = p["b"], p["t"], p["dt"], p["eta"]
    limit, e0 = p["p"], p["e0"]
    for bb in range(b):
        model += energy[bb][0] == e0, f"init_{bb}"
        for tt in range(t):
            model += (
                energy[bb][tt + 1]
                == energy[bb][tt] + dt * (eta * charge[bb][tt] - discharge[bb][tt] / eta),
                f"balance_{bb}_{tt}",
            )
        for tt in range(t):
            model += charge[bb][tt] + discharge[bb][tt] <= limit, f"mode_{bb}_{tt}"


def _bess_obj(model: LpProblem, case: WorkloadCase, handles) -> None:
    charge, discharge, _ = handles
    p = case.payload
    b, t, dt, prices = p["b"], p["t"], p["dt"], p["prices"]
    model += lpSum(
        dt * float(prices[tt]) * (discharge[bb][tt] - charge[bb][tt])
        for bb in range(b)
        for tt in range(t)
    )


def solve_objective(prob: LpProblem) -> float:
    """Solve a validation instance with bundled CBC; return objective value."""
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"PuLP validation solve status: {pulp.LpStatus[status]}")
    value = pulp.value(prob.objective)
    if value is None:
        raise RuntimeError("PuLP validation solve returned no objective value")
    return float(value)
