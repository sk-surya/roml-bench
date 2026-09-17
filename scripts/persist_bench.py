#!/usr/bin/env python3
"""Benchmark v2 — persistent-update family (item 7).

One fixed-structure multi-period production/inventory planning model; new
demand and margin forecasts arrive each cycle. Measures the update-and-resolve
lifecycle separately from construction, and reports each framework's
retention honestly:

* ``roml_direct``     — one ``Model`` + parameters, ``m.update(...)`` then solve
                        on the same ``Highs`` session.
* ``roml_template``   — ``Template.bind(shapes=same, data=new)`` then
                        ``template.solve()``; same-structure binds perform one
                        atomic ``Model.update`` on the same model + session.
* ``pyomo_rebuild``   — rebuild + solve (appsi_highs), explicitly labelled.
* ``pulp_rebuild``    — rebuild + solve (bundled CBC), explicitly labelled.

Cold path: construct, create solver/session, initial synchronization, initial
solve. Warm cycle: data/update, synchronization, solve, end-to-end. The first
structural ``Template.bind`` is reported separately and never folded into the
same-structure update statistic.

Usage: ``python scripts/persist_bench.py --cycles 50 [--out PATH]``
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time

import numpy as np

import roml as rm

P_PRODUCTS = 4
P_PERIODS = 24
SOLVE_CALL_NOTE = (
    "solve_call_ms times the whole framework solve call. It includes whatever "
    "synchronization / model transfer the framework performs inside that call; "
    "backend synchronization and optimizer execution are NOT independently "
    "instrumented by this benchmark. end_to_end_ms = update/bind/rebuild + "
    "solve_call."
)
HOLDING = 0.4
CAPACITY = 20.0
SEED = 20260908


def forecast(seed: int, k: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed + k)
    demand = np.maximum(8.0 + 3.0 * rng.standard_normal((P_PRODUCTS, P_PERIODS)), 0.0)
    margin = 6.0 + 2.0 * rng.standard_normal((P_PRODUCTS, P_PERIODS))
    return demand, margin


def build(shapes: dict) -> rm.Model:
    """Fixed-structure planning model with placeholder data (for Template)."""
    p, t = int(shapes["P"]), int(shapes["T"])
    m = rm.Model("planning")
    production = m.vars("production", (p, t), lb=0.0, ub=CAPACITY)
    sales = m.vars("sales", (p, t), lb=0.0)
    inventory = m.vars("inventory", (p, t + 1), lb=0.0)
    demand = m.params("demand", np.zeros((p, t)))
    margin = m.params("margin", np.zeros((p, t)))
    m.add(sales <= demand, name="sales_limit")
    m.add(inventory[:, 0] == 0.0, name="initial")
    m.add(inventory[:, 1:] == inventory[:, :-1] + production - sales, name="balance")
    m.maximize(rm.sum(margin * sales - HOLDING * inventory[:, :-1]))
    return m


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def summary(xs: list[float]) -> dict:
    ln = sorted(xs)
    p90 = ln[min(len(ln) - 1, round((len(ln) - 1) * 0.9))]
    return {
        "median": statistics.median(xs),
        "p90": p90,
        "min": min(xs),
        "max": max(xs),
        "series": xs,
    }


def roml_direct(cycles: int) -> dict:
    demand0, margin0 = forecast(SEED, 0)
    cold0 = time.perf_counter()
    m = build({"P": P_PRODUCTS, "T": P_PERIODS})
    m.update(demand=demand0, margin=margin0)
    build_ms = _ms(cold0)
    solver = rm.Highs(threads=1, output=False)
    solver0 = time.perf_counter()
    first = solver.solve(m)
    cold_solve_ms = _ms(solver0)
    assert first.is_optimal

    update_ms, solve_call_ms, end_to_end = [], [], []
    for k in range(1, cycles + 1):
        demand, margin = forecast(SEED, k)
        t0 = time.perf_counter()
        m.update(demand=demand, margin=margin)
        t1 = time.perf_counter()
        result = solver.solve(m)
        t2 = time.perf_counter()
        assert result.is_optimal
        update_ms.append((t1 - t0) * 1000.0)
        solve_call_ms.append((t2 - t1) * 1000.0)
        end_to_end.append((t2 - t0) * 1000.0)
    solver.close()
    return {
        "cold_build_ms": build_ms,
        "cold_solve_ms": cold_solve_ms,
        "update_ms": summary(update_ms),
        "solve_call_ms": summary(solve_call_ms),
        "end_to_end_ms": summary(end_to_end),
        "measurement_notes": SOLVE_CALL_NOTE,
        "retention": {
            "model_retained": True,
            "solver_object_retained": True,
            "backend_solver_model_retained": True,
            "native_coefficient_update_api": "Model.update -> revisioned delta",
            "rebuild_required": False,
        },
    }


def roml_template(cycles: int) -> dict:
    demand0, margin0 = forecast(SEED, 0)
    cold0 = time.perf_counter()
    tpl = rm.Template(
        build, solver_factory=lambda: rm.Highs(threads=1, output=False)
    )
    tpl.bind(shapes={"P": P_PRODUCTS, "T": P_PERIODS},
             data={"demand": demand0, "margin": margin0})
    build_ms = _ms(cold0)
    t0 = time.perf_counter()
    first = tpl.solve()
    cold_solve_ms = _ms(t0)
    assert first.is_optimal

    same_structure_bind_ms, solve_call_ms, end_to_end = [], [], []
    for k in range(1, cycles + 1):
        demand, margin = forecast(SEED, k)
        t0 = time.perf_counter()
        tpl.bind(shapes={"P": P_PRODUCTS, "T": P_PERIODS},
                 data={"demand": demand, "margin": margin})
        t1 = time.perf_counter()
        result = tpl.solve()
        t2 = time.perf_counter()
        assert result.is_optimal
        same_structure_bind_ms.append((t1 - t0) * 1000.0)
        solve_call_ms.append((t2 - t1) * 1000.0)
        end_to_end.append((t2 - t0) * 1000.0)
    generation = tpl.generation
    tpl.close()
    return {
        "cold_build_and_first_bind_ms": build_ms,
        "cold_solve_ms": cold_solve_ms,
        "same_structure_bind_ms": summary(same_structure_bind_ms),
        "solve_call_ms": summary(solve_call_ms),
        "end_to_end_ms": summary(end_to_end),
        "measurement_notes": SOLVE_CALL_NOTE,
        "generation_after_warm_cycles": generation,
        "retention": {
            "model_retained": True,
            "solver_object_retained": True,
            "backend_solver_model_retained": True,
            "native_coefficient_update_api": "Template.bind -> one Model.update",
            "rebuild_required": False,
            "first_structural_bind_reported_separately": True,
        },
    }


def pyomo_rebuild(cycles: int) -> dict:
    import pyomo.environ as pyo

    def rebuild(demand, margin):
        m = pyo.ConcreteModel()
        m.P = pyo.Set(initialize=range(P_PRODUCTS))
        m.T = pyo.Set(initialize=range(P_PERIODS))
        m.S = pyo.Set(initialize=range(P_PERIODS + 1))
        m.production = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals, bounds=(0, CAPACITY))
        m.sales = pyo.Var(m.P, m.T, domain=pyo.NonNegativeReals)
        m.inventory = pyo.Var(m.P, m.S, domain=pyo.NonNegativeReals)

        def sales_rule(mm, i, t):
            return mm.sales[i, t] <= float(demand[i, t])

        def init_rule(mm, i):
            return mm.inventory[i, 0] == 0.0

        def balance_rule(mm, i, t):
            return (
                mm.inventory[i, t + 1]
                == mm.inventory[i, t] + mm.production[i, t] - mm.sales[i, t]
            )

        m.sales_limit = pyo.Constraint(m.P, m.T, rule=sales_rule)
        m.init = pyo.Constraint(m.P, rule=init_rule)
        m.balance = pyo.Constraint(m.P, m.T, rule=balance_rule)
        m.obj = pyo.Objective(
            expr=pyo.quicksum(
                float(margin[i, t]) * m.sales[i, t]
                - HOLDING * m.inventory[i, t]
                for i in m.P
                for t in m.T
            ),
            sense=pyo.maximize,
        )
        return m

    solver = pyo.SolverFactory("appsi_highs")
    demand0, margin0 = forecast(SEED, 0)
    t0 = time.perf_counter()
    model = rebuild(demand0, margin0)
    build_ms = _ms(t0)
    t0 = time.perf_counter()
    solver.solve(model)
    cold_solve_ms = _ms(t0)

    rebuild_ms, solve_call_ms, end_to_end = [], [], []
    for k in range(1, cycles + 1):
        demand, margin = forecast(SEED, k)
        t0 = time.perf_counter()
        model = rebuild(demand, margin)
        t1 = time.perf_counter()
        solver.solve(model)
        t2 = time.perf_counter()
        rebuild_ms.append((t1 - t0) * 1000.0)
        solve_call_ms.append((t2 - t1) * 1000.0)
        end_to_end.append((t2 - t0) * 1000.0)
    return {
        "cold_build_ms": build_ms,
        "cold_solve_ms": cold_solve_ms,
        "rebuild_ms": summary(rebuild_ms),
        "solve_call_ms": summary(solve_call_ms),
        "end_to_end_ms": summary(end_to_end),
        "measurement_notes": SOLVE_CALL_NOTE,
        "retention": {
            "model_retained": False,
            "solver_object_retained": True,
            "backend_solver_model_retained": False,
            "native_coefficient_update_api": None,
            "rebuild_required": True,
            "label": "rebuild + solve",
        },
    }


def pulp_rebuild(cycles: int) -> dict:
    import pulp

    def rebuild(demand, margin):
        prob = pulp.LpProblem("planning", pulp.LpMaximize)
        prod = pulp.LpVariable.dicts(
            "prod", (range(P_PRODUCTS), range(P_PERIODS)), 0, CAPACITY
        )
        sales = pulp.LpVariable.dicts(
            "sales", (range(P_PRODUCTS), range(P_PERIODS)), 0
        )
        inv = pulp.LpVariable.dicts(
            "inv", (range(P_PRODUCTS), range(P_PERIODS + 1)), 0
        )
        for i in range(P_PRODUCTS):
            prob += inv[i][0] == 0.0
            for t in range(P_PERIODS):
                prob += sales[i][t] <= float(demand[i, t])
                prob += inv[i][t + 1] == inv[i][t] + prod[i][t] - sales[i][t]
        prob += pulp.lpSum(
            float(margin[i, t]) * sales[i][t] - HOLDING * inv[i][t]
            for i in range(P_PRODUCTS)
            for t in range(P_PERIODS)
        )
        return prob

    solver = pulp.PULP_CBC_CMD(msg=False)
    demand0, margin0 = forecast(SEED, 0)
    t0 = time.perf_counter()
    prob = rebuild(demand0, margin0)
    build_ms = _ms(t0)
    t0 = time.perf_counter()
    prob.solve(solver)
    cold_solve_ms = _ms(t0)

    rebuild_ms, solve_call_ms, end_to_end = [], [], []
    for k in range(1, cycles + 1):
        demand, margin = forecast(SEED, k)
        t0 = time.perf_counter()
        prob = rebuild(demand, margin)
        t1 = time.perf_counter()
        prob.solve(solver)
        t2 = time.perf_counter()
        rebuild_ms.append((t1 - t0) * 1000.0)
        solve_call_ms.append((t2 - t1) * 1000.0)
        end_to_end.append((t2 - t0) * 1000.0)
    return {
        "cold_build_ms": build_ms,
        "cold_solve_ms": cold_solve_ms,
        "rebuild_ms": summary(rebuild_ms),
        "solve_call_ms": summary(solve_call_ms),
        "end_to_end_ms": summary(end_to_end),
        "measurement_notes": SOLVE_CALL_NOTE,
        "retention": {
            "model_retained": False,
            "solver_object_retained": True,
            "backend_solver_model_retained": False,
            "native_coefficient_update_api": None,
            "rebuild_required": True,
            "label": "rebuild + solve",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=25)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    report = {
        "workload": "production_planning_persistent",
        "shape": [P_PRODUCTS, P_PERIODS],
        "cycles": args.cycles,
        "seed": SEED,
        "config": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "roml": rm.__version__,
            "threads": 1,
        },
        "arms": {
            "roml_direct": roml_direct(args.cycles),
            "roml_template": roml_template(args.cycles),
            "pyomo_rebuild": pyomo_rebuild(args.cycles),
            "pulp_rebuild": pulp_rebuild(args.cycles),
        },
    }
    text = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    print(
        json.dumps(
            {
                "roml_direct_end_to_end_p50_ms": report["arms"]["roml_direct"]["end_to_end_ms"]["median"],
                "roml_template_end_to_end_p50_ms": report["arms"]["roml_template"]["end_to_end_ms"]["median"],
                "pyomo_rebuild_end_to_end_p50_ms": report["arms"]["pyomo_rebuild"]["end_to_end_ms"]["median"],
                "pulp_rebuild_end_to_end_p50_ms": report["arms"]["pulp_rebuild"]["end_to_end_ms"]["median"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
