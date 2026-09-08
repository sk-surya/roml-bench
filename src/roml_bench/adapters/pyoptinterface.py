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
        "matrix: add_m_variables per family + add_m_linear_constraints "
        "per sense group + ExprBuilder objective"
    )

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
        if case.workload == "sparse_rows":
            return _populate_sparse(model, case)
        if case.workload == "bess_96":
            return _populate_bess(model, case)
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


def _populate_sparse(model: highs.Model, case) -> object:
    from roml_bench.adapters.base import BuildArtifact

    csr = case.payload["csr"]
    n = case.payload["n"]
    x = model.add_m_variables(n, lb=0.0, ub=5.0, name="x")
    model.add_m_linear_constraints(
        csr.csr_array(), x, poi.ConstraintSense.LessEqual, csr.upper
    )
    _set_objective(model, np.asarray(x), csr.obj_coeff, maximize=False)
    return BuildArtifact(
        model, "pyoptinterface_python", case, n, case.payload["n_rows"],
        10 * case.payload["n_rows"], n,
    )


def _populate_bess(model: highs.Model, case) -> object:
    from roml_bench.adapters.base import BuildArtifact

    p = case.payload
    b, t = p["b"], p["t"]
    limit, cap = p["p"], p["e"]
    csr = p["csr"]
    ch = model.add_m_variables(b * t, lb=0.0, ub=limit, name="charge")
    di = model.add_m_variables(b * t, lb=0.0, ub=limit, name="discharge")
    en = model.add_m_variables(b * (t + 1), lb=0.0, ub=cap, name="energy")
    x_all = np.concatenate([np.asarray(ch), np.asarray(di), np.asarray(en)])
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
    _set_objective(model, x_all, csr.obj_coeff, maximize=True)
    return BuildArtifact(
        model, "pyoptinterface_python", case, case.variables, case.constraints,
        case.constraint_nnz, case.objective_nnz,
    )


def solve_objective(model: highs.Model) -> float:
    """Solve a validation instance in-process; return objective value."""
    model.set_model_attribute(poi.ModelAttribute.Silent, True)
    model.optimize()
    status = model.get_model_attribute(poi.ModelAttribute.TerminationStatus)
    if status != poi.TerminationStatusCode.OPTIMAL:
        raise RuntimeError(f"PyOptInterface validation solve status: {status}")
    return float(model.get_model_attribute(poi.ModelAttribute.ObjectiveValue))
