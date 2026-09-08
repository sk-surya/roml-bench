"""Certification re-run of the parameterized BESS diagnostic on final code.

Three spellings, same math (BESS B=100 for speed; BESS300 equivalence is
covered by the forensic validation gate + the original B300 probe):
  packed-parametric : rm.dot(ParamArray, expr) -> set_linear_objective_param_bulk
  classified-param  : per-element lazy p*x chain -> classifier -> param_bulk
  general-symbolic  : per-element (p+q)*x chain -> general Affine fallback
Each: build -> solve -> x1.1 price update -> incremental sync -> solve,
all in ONE persistent HiGHS session. Requires identical objectives.
"""
import json
import sys
import time

import numpy as np

B = int(sys.argv[1]) if len(sys.argv) > 1 else 100
SEED = 20260908


def common(m, b, seed):
    import roml as rm
    t, dt, eta, p, e, e0 = 96, 0.25, 0.95, 2.0, 4.0, 2.0
    rng = np.random.default_rng(seed)
    prices = 20.0 + 60.0 * rng.random((b, t))
    price = m.params("price", prices)
    charge = m.vars("charge", (b, t), lb=0.0, ub=p)
    discharge = m.vars("discharge", (b, t), lb=0.0, ub=p)
    energy = m.vars("energy", (b, t + 1), lb=0.0, ub=e)
    m.add(energy[:, 0] == e0, name="init")
    m.add(energy[:, 1:] == energy[:, :-1] + dt * (eta * charge - discharge / eta),
          name="balance")
    m.add(charge + discharge <= p, name="mode")
    return price, charge, discharge, prices


def build_packed(b=B, seed=SEED):
    import roml as rm
    m = rm.Model("bess-packed")
    t0 = time.perf_counter()
    price, charge, discharge, prices = common(m, b, seed)
    m.maximize(rm.dot(price, discharge - charge))
    return m, prices, (time.perf_counter() - t0) * 1e3


def build_classified(b=B, seed=SEED):
    import roml as rm
    m = rm.Model("bess-classified")
    t0 = time.perf_counter()
    price, charge, discharge, prices = common(m, b, seed)
    total = None
    for i in range(b):
        for k in range(96):
            term = price[i, k] * (discharge[i, k] - charge[i, k])
            total = term if total is None else total + term
    m.maximize(total)
    return m, prices, (time.perf_counter() - t0) * 1e3


def build_general(b=B, seed=SEED):
    import roml as rm
    m = rm.Model("bess-general")
    t0 = time.perf_counter()
    price, charge, discharge, prices = common(m, b, seed)
    # (p + 0*q) is a genuine param-sum expression -> general fallback.
    # Use a second param array of zeros so math is identical.
    zero = m.params("zero", np.zeros((b, 96)))
    total = None
    for i in range(b):
        for k in range(96):
            term = (price[i, k] + zero[i, k]) * (discharge[i, k] - charge[i, k])
            total = term if total is None else total + term
    m.maximize(total)
    return m, prices, (time.perf_counter() - t0) * 1e3


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
    rows = [exercise(build_packed, "packed-parametric"),
            exercise(build_classified, "classified-param"),
            exercise(build_general, "general-symbolic")]
    a, b, c = rows
    for x in rows:
        assert x["optimal1"] and x["optimal2"], x
    for x, y in ((a, b), (a, c)):
        assert abs(x["obj1"] - y["obj1"]) / max(1.0, abs(x["obj1"])) < 1e-9, (x, y)
        assert abs(x["obj2"] - y["obj2"]) / max(1.0, abs(x["obj2"])) < 1e-9, (x, y)
    assert abs(a["obj2"] - a["obj1"] * 1.1) / a["obj1"] < 1e-9, a
    print(json.dumps(rows, indent=1))
    print("EQUIVALENCE: PASS")
