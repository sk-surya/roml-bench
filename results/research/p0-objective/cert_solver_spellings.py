"""Phase 5 solver semantic certification (HiGHS): spelling agreement."""
import numpy as np
import roml as rm

def solve_obj(model):
    with rm.Highs() as solver:
        sol = solver.solve(model)
    return float(sol.objective)

# min 3x+2y s.t. x+y>=4, 0<=x,y<=3 -> opt x=1,y=3 -> 9
def build_scalar():
    m = rm.Model("lp")
    x = m.var("x", lb=0.0, ub=3.0)
    y = m.var("y", lb=0.0, ub=3.0)
    m.add(x + y >= 4.0)
    m.minimize(3 * x + 2 * y)
    return m

def build_chain():
    m = rm.Model("lp")
    x = m.var("x", lb=0.0, ub=3.0)
    y = m.var("y", lb=0.0, ub=3.0)
    total = 0 * x
    total = total + x
    total = total + y
    m.add(total >= 4.0)
    obj = 0 * x
    obj = obj + 3 * x
    obj = obj + 2 * y
    m.minimize(obj)
    return m

def build_packed():
    m = rm.Model("lp")
    v = m.vars("v", 2, lb=0.0, ub=3.0)
    m.add(rm.sum(v) >= 4.0)
    m.minimize(rm.dot(np.array([3.0, 2.0]), v))
    return m

def build_csr():
    m = rm.Model("lp")
    v = m.vars("v", 2, lb=0.0, ub=3.0)
    # rows: [1 1] >= 4 ; [1 0] <= 3 ; [0 1] <= 3
    m.add_linear_rows(
        np.array([0, 2, 3, 4], dtype=np.int64),
        np.array([0, 1, 0, 1], dtype=np.int64),
        np.array([1.0, 1.0, 1.0, 1.0]),
        variables=v,
        lower=np.array([4.0, -float("inf"), -float("inf")]),
        upper=np.array([float("inf"), 3.0, 3.0]),
    )
    m.minimize(rm.dot(np.array([3.0, 2.0]), v))
    return m

def build_param():
    m = rm.Model("lp")
    v = m.vars("v", 2, lb=0.0, ub=3.0)
    p = m.params("p", np.array([3.0, 2.0]))
    m.add(rm.sum(v) >= 4.0)
    m.minimize(rm.dot(p, v))
    return m

def build_general():
    m = rm.Model("lp")
    x = m.var("x", lb=0.0, ub=3.0)
    y = m.var("y", lb=0.0, ub=3.0)
    p = m.param("p", 1.0)
    q = m.param("q", 2.0)
    # (p+q)*x forces the general fallback: coefficient is a param sum
    m.add((x + y) >= 4.0)
    m.minimize((p + q) * x + 2 * y + (x - x))
    return m

results = {}
results["scalar"] = solve_obj(build_scalar())
results["chain"] = solve_obj(build_chain())
results["packed"] = solve_obj(build_packed())
results["csr"] = solve_obj(build_csr())
results["param"] = solve_obj(build_param())
results["general"] = solve_obj(build_general())
print(results, flush=True)
assert all(abs(v - 9.0) < 1e-6 for v in results.values()), results
print("small-LP spelling agreement: OK (opt=9)", flush=True)

# parameterized update -> resolve in one persistent session
m = rm.Model("pu")
v = m.vars("v", 2, lb=0.0, ub=3.0)
p = m.params("p", np.array([3.0, 2.0]))
m.add(rm.sum(v) >= 4.0)
m.minimize(rm.dot(p, v))
with rm.Highs() as solver:
    o1 = float(solver.solve(m).objective)
    m.update(p=np.array([3.3, 2.2]))  # x1.1
    o2 = float(solver.solve(m).objective)
print("param update:", o1, "->", o2, flush=True)
assert abs(o1 - 9.0) < 1e-6, o1
assert abs(o2 - 9.9) < 1e-6, o2
m2 = rm.Model("pu2")
v2 = m2.vars("v", 2, lb=0.0, ub=3.0)
p2 = m2.params("p", np.array([3.3, 2.2]))
m2.add(rm.sum(v2) >= 4.0)
m2.minimize(rm.dot(p2, v2))
o3 = solve_obj(m2)
assert abs(o2 - o3) < 1e-9, (o2, o3)
print("parameterized update->resolve agreement: OK", flush=True)

# sparse larger: CSR vs scalar agreement (1k rows, seeded; random 5k LPs
# are pathologically slow for simplex and prove nothing about ROML)
rng = np.random.default_rng(0)
n, nnz_per = 1000, 8
mA = rm.Model("sp_csr")
xs = mA.vars("x", n, lb=0.0, ub=10.0)
indptr = np.zeros(n + 1, dtype=np.int64)
cols, data = [], []
for i in range(n):
    c = rng.choice(n, size=nnz_per, replace=False)
    cols.extend(c)
    data.extend(rng.uniform(0.5, 2.0, size=nnz_per))
    indptr[i + 1] = len(cols)
mA.add_linear_rows(np.asarray(indptr), np.asarray(cols, dtype=np.int64),
                   np.asarray(data), variables=xs,
                   lower=np.full(n, 5.0), upper=np.full(n, float("inf")))
mA.minimize(rm.dot(np.ones(n), xs))
def solve_obj_lim(model, tl=60.0):
    with rm.Highs(time_limit=tl) as solver:
        sol = solver.solve(model)
    assert str(sol.status) == "SolveStatus.Optimal", sol.status
    return float(sol.objective)

o_csr = solve_obj_lim(mA)
print("sparse csr solved", flush=True)

mB = rm.Model("sp_scalar")
ys = mB.vars("x", n, lb=0.0, ub=10.0)
for i in range(n):
    s, e = int(indptr[i]), int(indptr[i + 1])
    row = sum(float(data[k]) * ys[int(cols[k])] for k in range(s, e))
    mB.add(row >= 5.0)
mB.minimize(rm.dot(np.ones(n), ys))
o_packed = solve_obj_lim(mB)
print("sparse 1k:", o_csr, o_packed, flush=True)
assert abs(o_csr - o_packed) < 1e-6 * max(1.0, abs(o_csr)), (o_csr, o_packed)
print("sparse CSR/scalar agreement: OK", flush=True)
