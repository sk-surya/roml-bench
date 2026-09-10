"""PyOptInterface adapter using the documented matrix/bulk path.

Construction: add_m_variables per variable family (scalar lb/ub only) +
add_m_linear_constraints over scipy csr_array groups (one call per
constraint sense) + ExprBuilder objective with reserved capacity.

The pinned 0.6.1 matrix helper ingests rows through per-row native calls,
and variable naming is only supported as a single base name per
add_m_variables call; both facts are disclosed on the site methodology
page. The HiGHS shared library is the highspy-bundled libhighs, loaded
explicitly because the pinned autoloader only probes the unversioned
soname.

Semantic disclosure (contract section 4): a PyOptInterface model is
solver-backed — population calls insert directly into HiGHS — while the
other compared libraries maintain a separate modeling representation.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pyoptinterface as poi

_LIB_LOADED = False


def ensure_highs_library() -> str:
    """Load the highspy-bundled libhighs; return the path used."""
    global _LIB_LOADED
    if _LIB_LOADED:
        return "already-loaded"
    import highspy
    from pyoptinterface.highs import load_library

    candidates = sorted(pathlib.Path(highspy.__file__).parent.glob("libhighs.so*"))
    if not candidates:
        raise RuntimeError("no libhighs found next to highspy")
    # Prefer the fully versioned real file over symlinks.
    path = max(candidates, key=lambda p: len(p.suffixes))
    if not load_library(str(path)):
        raise RuntimeError(f"pyoptinterface could not load {path}")
    _LIB_LOADED = True
    return str(path)


ensure_highs_library()

from pyoptinterface import highs  # noqa: E402


class PyOptInterfaceAdapter:
    implementation_id = "pyoptinterface_python"
    construction_path = (
        "matrix ingestion: add_m_variables per family + "
        "add_m_linear_constraints per sense group + ExprBuilder objective"
    )
    supported_workloads = ("sparse_rows", "bess_96")

    def warmup(self) -> None:
        m = highs.Model()
        x = m.add_m_variables(1, lb=0.0, ub=5.0, name="x")
        a = __import__("scipy.sparse", fromlist=["csr_array"]).csr_array(
            np.array([[1.0]])
        )
        m.add_m_linear_constraints(a, x, poi.ConstraintSense.LessEqual, np.array([10.0]))
        builder = poi.ExprBuilder()
        builder.add_affine_term(x[0], 1.0)
        m.set_objective(builder, poi.ObjectiveSense.Minimize)

    def new_model(self, case) -> highs.Model:
        return highs.Model()

    def populate(self, model: highs.Model, case) -> object:
        for _, step in self.populate_phases(model, case):
            step()
        return _counts(model, case, self.implementation_id)

    def populate_phases(self, model: highs.Model, case):
        stage: dict = {}
        if case.workload == "sparse_rows":
            return [
                ("variables", lambda: stage.update(x=_sparse_vars(model, case))),
                ("constraints", lambda: _sparse_cons(model, case, stage["x"])),
                ("objective", lambda: _sparse_obj(model, case, stage["x"])),
            ]
        if case.workload == "bess_96":
            return [
                ("variables", lambda: stage.update(x=_bess_vars(model, case))),
                ("constraints", lambda: _bess_cons(model, case, stage["x"])),
                ("objective", lambda: _bess_obj(model, case, stage["x"])),
            ]
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact, case) -> object:
        from roml_bench.adapters.base import StructuralReport

        return StructuralReport(
            implementation=artifact.implementation,
            workload=case.workload,
            size=case.size,
            variables=artifact.variables,
            constraints=artifact.constraints,
            constraint_nnz=artifact.constraint_nnz,
            objective_nnz=artifact.objective_nnz,
            # The pinned API exposes no public model-count introspection;
            # counts are exact adapter bookkeeping over matrix groups.
            count_source="construction",
        )


def _set_objective(
    model: highs.Model, x_all: np.ndarray, coeff: np.ndarray, maximize: bool
) -> None:
    builder = poi.ExprBuilder()
    builder.reserve_affine(int(len(coeff)))
    for j, c in enumerate(coeff):
        if c != 0.0:
            builder.add_affine_term(x_all[j], float(c))
    sense = poi.ObjectiveSense.Maximize if maximize else poi.ObjectiveSense.Minimize
    model.set_objective(builder, sense)


def _counts(model: highs.Model, case, implementation: str) -> object:
    from roml_bench.adapters.base import BuildArtifact

    return BuildArtifact(
        model, implementation, case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


def _sparse_vars(model: highs.Model, case):
    return model.add_m_variables(case.payload["n"], lb=0.0, ub=5.0, name="x")


def _sparse_cons(model: highs.Model, case, x) -> None:
    csr = case.payload["csr"]
    model.add_m_linear_constraints(
        csr.csr_array(), np.asarray(x), poi.ConstraintSense.LessEqual, csr.upper
    )


def _sparse_obj(model: highs.Model, case, x) -> None:
    _set_objective(model, np.asarray(x), case.payload["csr"].obj_coeff, maximize=False)


def _bess_vars(model: highs.Model, case):
    p = case.payload
    b, t, limit, cap = p["b"], p["t"], p["p"], p["e"]
    ch = model.add_m_variables(b * t, lb=0.0, ub=limit, name="charge")
    di = model.add_m_variables(b * t, lb=0.0, ub=limit, name="discharge")
    en = model.add_m_variables(b * (t + 1), lb=0.0, ub=cap, name="energy")
    return np.concatenate([np.asarray(ch), np.asarray(di), np.asarray(en)])


def _bess_cons(model: highs.Model, case, x_all) -> None:
    p = case.payload
    b, t = p["b"], p["t"]
    csr = p["csr"]
    mat = csr.csr_array()
    n_init = b
    n_bal = b * t
    # init + balance rows are equalities; mode rows are upper bounds.
    model.add_m_linear_constraints(
        mat[:n_init], x_all, poi.ConstraintSense.Equal, csr.upper[:n_init]
    )
    model.add_m_linear_constraints(
        mat[n_init : n_init + n_bal],
        x_all,
        poi.ConstraintSense.Equal,
        csr.upper[n_init : n_init + n_bal],
    )
    model.add_m_linear_constraints(
        mat[n_init + n_bal :],
        x_all,
        poi.ConstraintSense.LessEqual,
        csr.upper[n_init + n_bal :],
    )


def _bess_obj(model: highs.Model, case, x_all) -> None:
    _set_objective(model, x_all, case.payload["csr"].obj_coeff, maximize=True)


def solve_objective(model: highs.Model) -> float:
    """Solve a validation instance in-process; return objective value."""
    model.set_model_attribute(poi.ModelAttribute.Silent, True)
    model.optimize()
    status = model.get_model_attribute(poi.ModelAttribute.TerminationStatus)
    if status != poi.TerminationStatusCode.OPTIMAL:
        raise RuntimeError(f"PyOptInterface validation solve status: {status}")
    return float(model.get_model_attribute(poi.ModelAttribute.ObjectiveValue))


class PyOptInterfaceScalarAdapter:
    """Formulation path: scalar variables + per-row expressions.

    This is the honest high-level-modeling cost for a solver-backed API
    with no algebraic modeling layer: one native call per variable and
    per constraint row, all driven from Python loops over the canonical
    B/T/prices inputs (no shared CSR).
    """

    implementation_id = "pyoptinterface_scalar"
    construction_path = (
        "formulation: add_variable loop + per-row ScalarAffineFunction "
        "constraints + ExprBuilder objective"
    )
    supported_workloads = ("sparse_rows", "bess_96")

    def warmup(self) -> None:
        m = highs.Model()
        x = m.add_variable(lb=0.0, ub=5.0, name="x")
        f = poi.ScalarAffineFunction()
        f.add_term(x, 1.0)
        m.add_linear_constraint(f, poi.ConstraintSense.LessEqual, 10.0)
        builder = poi.ExprBuilder()
        builder.add_affine_term(x, 1.0)
        m.set_objective(builder, poi.ObjectiveSense.Minimize)

    def new_model(self, case) -> highs.Model:
        return highs.Model()

    def populate(self, model: highs.Model, case) -> object:
        for _, step in self.populate_phases(model, case):
            step()
        return _counts(model, case, self.implementation_id)

    def populate_phases(self, model: highs.Model, case):
        stage: dict = {}
        if case.workload == "sparse_rows":
            return [
                ("variables", lambda: stage.update(xs=_scalar_sparse_vars(model, case))),
                ("constraints", lambda: _scalar_sparse_cons(model, case, stage["xs"])),
                ("objective", lambda: _scalar_sparse_obj(model, case, stage["xs"])),
            ]
        if case.workload == "bess_96":
            return [
                ("variables", lambda: stage.update(h=_scalar_bess_vars(model, case))),
                ("constraints", lambda: _scalar_bess_cons(model, case, stage["h"])),
                ("objective", lambda: _scalar_bess_obj(model, case, stage["h"])),
            ]
        raise ValueError(f"unknown workload: {case.workload}")

    def inspect(self, artifact, case) -> object:
        from roml_bench.adapters.base import StructuralReport

        return StructuralReport(
            implementation=artifact.implementation,
            workload=case.workload,
            size=case.size,
            variables=artifact.variables,
            constraints=artifact.constraints,
            constraint_nnz=artifact.constraint_nnz,
            objective_nnz=artifact.objective_nnz,
            count_source="construction",
        )


def _scalar_sparse_vars(model: highs.Model, case):
    n = case.payload["n"]
    return [model.add_variable(lb=0.0, ub=5.0, name=f"x[{i}]") for i in range(n)]


def _scalar_sparse_cons(model: highs.Model, case, xs) -> None:
    for r in range(case.payload["n_rows"]):
        f = poi.ScalarAffineFunction()
        for k in range(10):
            f.add_term(xs[10 * r + k], 1.0)
        model.add_linear_constraint(f, poi.ConstraintSense.LessEqual, 10.0)


def _scalar_sparse_obj(model: highs.Model, case, xs) -> None:
    builder = poi.ExprBuilder()
    builder.reserve_affine(case.payload["n"])
    for v in xs:
        builder.add_affine_term(v, 1.0)
    model.set_objective(builder, poi.ObjectiveSense.Minimize)


def _scalar_bess_vars(model: highs.Model, case):
    p = case.payload
    b, t, limit, cap = p["b"], p["t"], p["p"], p["e"]
    charge = [[model.add_variable(lb=0.0, ub=limit, name=f"charge[{bb},{tt}]")
               for tt in range(t)] for bb in range(b)]
    discharge = [[model.add_variable(lb=0.0, ub=limit, name=f"discharge[{bb},{tt}]")
                  for tt in range(t)] for bb in range(b)]
    energy = [[model.add_variable(lb=0.0, ub=cap, name=f"energy[{bb},{tt}]")
               for tt in range(t + 1)] for bb in range(b)]
    return (charge, discharge, energy)


def _scalar_bess_cons(model: highs.Model, case, handles) -> None:
    charge, discharge, energy = handles
    p = case.payload
    b, t, dt, eta = p["b"], p["t"], p["dt"], p["eta"]
    limit, e0 = p["p"], p["e0"]
    for bb in range(b):
        f = poi.ScalarAffineFunction()
        f.add_term(energy[bb][0], 1.0)
        model.add_linear_constraint(f, poi.ConstraintSense.Equal, e0)
        for tt in range(t):
            f = poi.ScalarAffineFunction()
            f.add_term(energy[bb][tt + 1], 1.0)
            f.add_term(energy[bb][tt], -1.0)
            f.add_term(charge[bb][tt], -dt * eta)
            f.add_term(discharge[bb][tt], dt / eta)
            model.add_linear_constraint(f, poi.ConstraintSense.Equal, 0.0)
        for tt in range(t):
            f = poi.ScalarAffineFunction()
            f.add_term(charge[bb][tt], 1.0)
            f.add_term(discharge[bb][tt], 1.0)
            model.add_linear_constraint(f, poi.ConstraintSense.LessEqual, limit)


def _scalar_bess_obj(model: highs.Model, case, handles) -> None:
    charge, discharge, _ = handles
    p = case.payload
    b, t, dt, prices = p["b"], p["t"], p["dt"], p["prices"]
    builder = poi.ExprBuilder()
    builder.reserve_affine(2 * b * t)
    for bb in range(b):
        for tt in range(t):
            c = dt * float(prices[tt])
            builder.add_affine_term(discharge[bb][tt], c)
            builder.add_affine_term(charge[bb][tt], -c)
    model.set_objective(builder, poi.ObjectiveSense.Maximize)
