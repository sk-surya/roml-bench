"""Adversarial Python probes on the candidate release wheel."""
import numpy as np
import roml as rm

# 1. view-of-view identity + display names
m = rm.Model("views")
x = m.vars("x", 10, lb=0.0, ub=10.0)
v = x[2:7]
assert v.shape == (5,), v.shape
w = v[1:4]
assert w.shape == (3,), w.shape
s = w[0]
assert '"x[3]"' in repr(s), repr(s)
s2 = v[0]
assert '"x[2]"' in repr(s2), repr(s2)
s3 = x[2:7][0]
assert '"x[2]"' in repr(s3), repr(s3)
# values flow by identity: constrain w[0] == x[3]
m.add(w[0] <= 4.0)
m.add(x[3] >= 4.0)
m.minimize(rm.sum(x))
with rm.Highs() as sv:
    sol = sv.solve(m)
assert abs(float(sol.objective) - 4.0) < 1e-9, float(sol.objective)
print("view-of-view: OK")

# 2. multidimensional slices
m2 = rm.Model("md")
a = m2.vars("a", (4, 5), lb=0.0, ub=10.0)
sub = a[1:3, 2:4]
assert sub.shape == (2, 2), sub.shape
el = sub[0, 0]
assert '"a[7]"' in repr(el), repr(el)  # C-order flat 1*5+2
el2 = sub[1, 1]
assert '"a[13]"' in repr(el2), repr(el2)
print("multidim slices: OK")

# 3. namespace collisions
m3 = rm.Model("ns")
xa = m3.vars("x", 5, lb=0.0, ub=1.0)
try:
    m3.var("x[2]", lb=0.0, ub=1.0)
    raise AssertionError("expected collision for x[2]")
except Exception as e:
    assert "collision" in str(e).lower() or "duplicate" in str(e).lower(), e
try:
    m3.vars("x", 3, lb=0.0, ub=1.0)
    raise AssertionError("expected duplicate base")
except Exception as e:
    pass
# ugly spelling is ordinary explicit name, no collision with x[1]
u = m3.var("x[01]", lb=0.0, ub=1.0)
assert '"x[01]"' in repr(u), repr(u)
# out-of-range is fine
o = m3.var("x[100]", lb=0.0, ub=1.0)
assert '"x[100]"' in repr(o), repr(o)
print("namespace collisions: OK")

# 4. zero-length array
z = m3.vars("z", 0, lb=0.0, ub=1.0)
assert z.shape == (0,), z.shape
print("zero-length: OK")

# 5. deep left-spine build + sink (linear time sanity, small N here)
m4 = rm.Model("deep")
d = m4.vars("d", 20000, lb=0.0, ub=10.0)
import time
t0 = time.perf_counter()
total = 0 * d[0]
for i in range(20000):
    total = total + d[i]
t1 = time.perf_counter()
m4.minimize(total)
t2 = time.perf_counter()
print(f"deep chain 20k: build={t1-t0:.2f}s sink={t2-t1:.2f}s")
with rm.Highs() as sv:
    sol = sv.solve(m4)
assert abs(float(sol.objective)) < 1e-9
print("deep chain: OK")

# 6. shared lazy subtrees + cancellation
m5 = rm.Model("shared")
p = m5.param("p", 2.0)
q = m5.param("q", 3.0)
xx = m5.var("xx", lb=0.0, ub=10.0)
yy = m5.var("yy", lb=0.0, ub=10.0)
a = xx + yy
b = a + xx
c = a - xx  # == yy
m5.add(c >= 4.0)
m5.minimize(b)  # 2xx + yy, min at xx=0,yy=4 -> 4
with rm.Highs() as sv:
    sol = sv.solve(m5)
assert abs(float(sol.objective) - 4.0) < 1e-9, float(sol.objective)
# p*(p*x) must stay nonlinear-safe: coefficient p^2 is general, solve still exact
m6 = rm.Model("ppx")
pp = m6.param("pp", 2.0)
xxx = m6.var("xxx", lb=0.0, ub=10.0)
m6.add(xxx >= 3.0)
m6.minimize(pp * (pp * xxx))  # 4*xxx -> 12
with rm.Highs() as sv:
    sol = sv.solve(m6)
assert abs(float(sol.objective) - 12.0) < 1e-9, float(sol.objective)
# 2*(p*x), -(p*x), (p+q)*x
m7 = rm.Model("mix")
r = m7.param("r", 2.0)
s_ = m7.param("s", 3.0)
xv = m7.var("xv", lb=0.0, ub=10.0)
m7.add(xv >= 1.0)
m7.minimize(2 * (r * xv) - (r * xv) + (r + s_) * xv * 0 + (r * xv))
with rm.Highs() as sv:
    sol = sv.solve(m7)
# 2*2 + (-2) + 0 + 2 = 4 per unit -> 4
assert abs(float(sol.objective) - 4.0) < 1e-9, float(sol.objective)
print("shared/cancellation/param-nesting: OK")
print("ALL ADVERSARIAL PROBES PASSED")
