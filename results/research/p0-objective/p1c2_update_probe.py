"""P1C-2 parameter-update probe (BESS300): packed-parametric vs scalar.

build -> initial solve -> price update -> incremental sync -> second solve
in ONE persistent HiGHS session per model. Asserts identical objectives
and state; times each stage separately. Standalone diagnostics, not
populate_ms methodology.
"""
import json
import time

import numpy as np


def build_packed(b=300, seed=20260908):
    import roml as rm
    t, dt, eta, p, e, e0 = 96, 0.25, 0.95, 2.0, 4.0, 2.0
    rng = np.random.default_rng(seed)
    prices = 20.0 + 60.0 * rng.random((b, t))
    m = rm.Model("bess-packed")
    t0 = time.perf_counter()
    price = m.params("price", prices)
    charge = m.vars("charge", (b, t), lb=0.0, ub=p)
    discharge = m.vars("discharge", (b, t), lb=0.0, ub=p)
    energy = m.vars("energy", (b, t + 1), lb=0.0, ub=e)
    m.add(energy[:, 0] == e0, name="init")
    m.add(energy[:, 1:] == energy[:, :-1] + dt * (eta * charge - discharge / eta),
          name="balance")
    m.add(charge + discharge <= p, name="mode")
    m.maximize(rm.dot(price, discharge - charge))
    build_ms = (time.perf_counter() - t0) * 1e3
    return m, prices, build_ms


def build_scalar(b=300, seed=20260908):
    import roml as rm
    t, dt, eta, p, e, e0 = 96, 0.25, 0.95, 2.0, 4.0, 2.0
    rng = np.random.default_rng(seed)
    prices = 20.0 + 60.0 * rng.random((b, t))
    m = rm.Model("bess-scalar")
    t0 = time.perf_counter()
    price = m.params("price", prices)
    charge = m.vars("charge", (b, t), lb=0.0, ub=p)
    discharge = m.vars("discharge", (b, t), lb=0.0, ub=p)
    energy = m.vars("energy", (b, t + 1), lb=0.0, ub=e)
    m.add(energy[:, 0] == e0, name="init")
    m.add(energy[:, 1:] == energy[:, :-1] + dt * (eta * charge - discharge / eta),
          name="balance")
    m.add(charge + discharge <= p, name="mode")
    total = None
    for i in range(b):
        for k in range(t):
            term = price[i, k] * (discharge[i, k] - charge[i, k])
            total = term if total is None else total + term
    m.maximize(total)
    build_ms = (time.perf_counter() - t0) * 1e3
    return m, prices, build_ms


def exercise(build, label):
    import roml as rm
    m, prices, build_ms = build()
    out = {"model": label, "build_ms": round(build_ms, 1)}
    with rm.Highs() as s:
        t0 = time.perf_counter()
        r1 = s.solve(m)
        out["solve1_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
        out["obj1"] = r1.objective
        out["optimal1"] = bool(r1.is_optimal)
        t0 = time.perf_counter()
        m.update(price=prices * 1.1)
        out["update_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
        t0 = time.perf_counter()
        r2 = s.solve(m)
        out["solve2_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
        out["obj2"] = r2.objective
        out["optimal2"] = bool(r2.is_optimal)
    return out


if __name__ == "__main__":
    import sys
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    rows = []
    for _ in range(reps):
        rows.append(exercise(build_packed, "packed-parametric"))
        rows.append(exercise(build_scalar, "scalar-general"))
    # Pairwise equivalence assertions.
    for i in range(0, len(rows), 2):
        a, b = rows[i], rows[i + 1]
        assert a["optimal1"] and a["optimal2"] and b["optimal1"] and b["optimal2"]
        assert abs(a["obj1"] - b["obj1"]) / max(1.0, abs(a["obj1"])) < 1e-6, (a, b)
        assert abs(a["obj2"] - b["obj2"]) / max(1.0, abs(a["obj2"])) < 1e-6, (a, b)
        assert abs(a["obj2"] - a["obj1"] * 1.1) / a["obj1"] < 1e-6, a
    print(json.dumps(rows, indent=1))
    print("EQUIVALENCE: PASS")
