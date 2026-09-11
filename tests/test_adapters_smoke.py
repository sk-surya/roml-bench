"""Smoke tests: every Python adapter builds both quick workloads."""

import pytest

from roml_bench.adapters import ADAPTERS, get_adapter
from roml_bench.adapters.base import check_report_against_case
from roml_bench.workloads import CANONICAL_SEED, make_case


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
@pytest.mark.parametrize("workload,size", [("sparse_rows", 1000), ("bess_96", 1)])
def test_adapter_builds_and_counts_match(adapter_cls, workload, size):
    if workload not in getattr(adapter_cls, "supported_workloads", ("sparse_rows", "bess_96")):
        pytest.skip(f"{adapter_cls.implementation_id} does not support {workload}")
    adapter = adapter_cls()
    adapter.warmup()
    case = make_case(workload, size, seed=CANONICAL_SEED)
    model = adapter.new_model(case)
    artifact = adapter.populate(model, case)
    report = adapter.inspect(artifact, case)
    assert report.implementation == adapter.implementation_id
    assert check_report_against_case(report, case) == []


def test_adapter_registry_resolves_all_ids():
    for cls in ADAPTERS:
        adapter = get_adapter(cls.implementation_id)
        assert adapter.implementation_id == cls.implementation_id
        assert adapter.construction_path
    with pytest.raises(ValueError):
        get_adapter("nope")


def test_sparse_rows_bulk_matches_scalar_objective():
    import roml as rm

    from roml_bench.adapters.pulp import solve_objective as pulp_solve
    from roml_bench.adapters.pyomo import solve_objective as pyomo_solve
    from roml_bench.adapters.pyoptinterface import (
        solve_objective as poi_solve,
    )

    case = make_case("sparse_rows", 100, seed=CANONICAL_SEED)
    from roml_bench.adapters import get_adapter as get

    bulk = get("roml_python_vectorized")
    art = bulk.populate(bulk.new_model(case), case)
    with rm.Highs() as solver:
        roml_obj = solver.solve(art.model).objective

    pulp_adapter = get("pulp_python")
    pulp_obj = pulp_solve(
        pulp_adapter.populate(pulp_adapter.new_model(case), case).model
    )
    pyomo_adapter = get("pyomo_python")
    pyomo_obj = pyomo_solve(
        pyomo_adapter.populate(pyomo_adapter.new_model(case), case).model
    )
    poi_adapter = get("pyoptinterface_python")
    poi_obj = poi_solve(
        poi_adapter.populate(poi_adapter.new_model(case), case).model
    )
    assert roml_obj == pytest.approx(0.0, abs=1e-9)
    assert pulp_obj == pytest.approx(roml_obj, abs=1e-7)
    assert pyomo_obj == pytest.approx(roml_obj, abs=1e-7)
    assert poi_obj == pytest.approx(roml_obj, abs=1e-7)


def test_bess_all_arms_agree():
    """Every bess-capable arm (incl. fused-dot bulk and CSR) agrees."""
    import roml as rm

    from roml_bench.adapters import get_adapter as get
    from roml_bench.adapters.pulp import solve_objective as pulp_solve
    from roml_bench.adapters.pyomo import solve_objective as pyomo_solve
    from roml_bench.adapters.pyoptinterface import (
        solve_objective as poi_solve,
    )

    case = make_case("bess_96", 2, seed=CANONICAL_SEED)
    bulk = get("roml_python_vectorized")
    with rm.Highs() as solver:
        reference = solver.solve(bulk.populate(bulk.new_model(case), case).model).objective
    assert reference > 0
    naive = get("roml_python_naive_chain")
    with rm.Highs() as solver:
        naive_obj = solver.solve(naive.populate(naive.new_model(case), case).model).objective
    csr = get("roml_python_csr")
    with rm.Highs() as solver:
        csr_obj = solver.solve(csr.populate(csr.new_model(case), case).model).objective
    poi = get("pyoptinterface_python")
    poi_obj = poi_solve(poi.populate(poi.new_model(case), case).model)
    poi_scalar = get("pyoptinterface_scalar")
    poi_scalar_obj = poi_solve(poi_scalar.populate(poi_scalar.new_model(case), case).model)
    pulp_adapter = get("pulp_python")
    pulp_obj = pulp_solve(pulp_adapter.populate(pulp_adapter.new_model(case), case).model)
    pyomo_adapter = get("pyomo_python")
    pyomo_obj = pyomo_solve(pyomo_adapter.populate(pyomo_adapter.new_model(case), case).model)
    for name, value in (
        ("naive", naive_obj), ("csr", csr_obj), ("poi", poi_obj),
        ("poi_scalar", poi_scalar_obj), ("pulp", pulp_obj), ("pyomo", pyomo_obj),
    ):
        assert value == pytest.approx(reference, abs=1e-7, rel=1e-7), name
