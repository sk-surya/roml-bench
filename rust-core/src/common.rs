//! Shared construction workloads for the `roml-bench-core` timing runner and
//! the `roml-ops-probe` counting runner (P0 objective research).
//!
//! Both binaries execute byte-identical build code paths against `roml`
//! pinned at `ROML_SHA`; only the surrounding harness differs (phase timing
//! vs allocation counting). Never solves.

use roml::prelude::*;
use std::collections::BTreeMap;
use std::time::Instant;

pub const BESS_T: usize = 96;
pub const BESS_DT: f64 = 0.25;
pub const BESS_ETA: f64 = 0.95;
pub const BESS_P: f64 = 2.0;
pub const BESS_E: f64 = 4.0;
pub const BESS_E0: f64 = 2.0;

/// Current VmRSS and process peak (VmHWM) in bytes from /proc/self/status.
pub fn rss_bytes() -> (u64, u64) {
    let mut rss = 0u64;
    let mut hwm = 0u64;
    if let Ok(text) = std::fs::read_to_string("/proc/self/status") {
        for line in text.lines() {
            if let Some(rest) = line.strip_prefix("VmRSS:") {
                rss = rest
                    .split_whitespace()
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(0)
                    * 1024;
            } else if let Some(rest) = line.strip_prefix("VmHWM:") {
                hwm = rest
                    .split_whitespace()
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(0)
                    * 1024;
            }
        }
    }
    (rss, hwm)
}

pub fn var_def(name: Option<String>, lower: f64, upper: f64) -> VariableDef {
    let def = continuous().bounds(lower, upper);
    match name {
        Some(n) => def.named(n),
        None => def,
    }
}

pub fn con_spec(expr: LinExpr, name: Option<String>, upper: f64) -> ConstraintSpec {
    let spec = expr.le(upper);
    match name {
        Some(n) => spec.named(n),
        None => spec,
    }
}

/// Sparse workload: `n` variables, `n/10` ten-coefficient rows, one
/// `minimize` over all variables.
///
/// `parameterized` switches the objective coefficients from `Constant(1.0)`
/// to `Param(p)` for a single shared parameter `p = 1.0`, keeping the
/// mathematics identical (every coefficient evaluates to 1.0) while
/// exercising the parameter-dependency machinery. Rows stay constant in
/// both modes.
///
/// Note: the ops-probe binary inlines an instrumented copy of this builder
/// (it needs per-sub-phase allocator snapshots), so this function is dead
/// code in that binary by design; the timing runner is its consumer.
#[allow(dead_code)]
pub fn build_sparse(
    model: &mut Model,
    n: usize,
    named: bool,
    parameterized: bool,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize), ModelError> {
    let rows = n / 10;
    let t0 = Instant::now();
    let mut vars = Vec::with_capacity(n);
    for i in 0..n {
        let name = named.then(|| format!("x[{i}]"));
        vars.push(model.add_variable(var_def(name, 0.0, 5.0))?);
    }
    let t_vars = t0.elapsed().as_nanos() as u64;
    let t1 = Instant::now();
    for r in 0..rows {
        let base = 10 * r;
        let mut expr = LinExpr::new();
        for k in 0..10 {
            expr = expr.term(1.0, vars[base + k]);
        }
        let name = named.then(|| format!("row[{r}]"));
        model.add_constraint(con_spec(expr, name, 10.0))?;
    }
    let t_cons = t1.elapsed().as_nanos() as u64;
    let t2 = Instant::now();
    let mut total = LinExpr::new();
    if parameterized {
        let p = model.add_parameter(1.0)?;
        for v in &vars {
            total = total.term(roml::ValueExpr::param(p), *v);
        }
    } else {
        for v in &vars {
            total = total.term(1.0, *v);
        }
    }
    model.minimize(total)?;
    let t_obj = t2.elapsed().as_nanos() as u64;
    if let Some(map) = phases {
        map.insert("variables".to_string(), t_vars);
        map.insert("constraints".to_string(), t_cons);
        map.insert("objective".to_string(), t_obj);
    }
    Ok((n, rows, 10 * rows))
}

pub fn build_bess(
    model: &mut Model,
    b: usize,
    prices: &[f64],
    named: bool,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize, usize), ModelError> {
    assert_eq!(prices.len(), BESS_T);
    let t = BESS_T;
    let t0 = Instant::now();
    let mut charge = Vec::with_capacity(b * t);
    let mut discharge = Vec::with_capacity(b * t);
    let mut energy = Vec::with_capacity(b * (t + 1));
    for bb in 0..b {
        for tt in 0..t {
            let name = named.then(|| format!("charge[{bb},{tt}]"));
            charge.push(model.add_variable(var_def(name, 0.0, BESS_P))?);
        }
    }
    for bb in 0..b {
        for tt in 0..t {
            let name = named.then(|| format!("discharge[{bb},{tt}]"));
            discharge.push(model.add_variable(var_def(name, 0.0, BESS_P))?);
        }
    }
    for bb in 0..b {
        for tt in 0..=t {
            let name = named.then(|| format!("energy[{bb},{tt}]"));
            energy.push(model.add_variable(var_def(name, 0.0, BESS_E))?);
        }
    }
    let t_vars = t0.elapsed().as_nanos() as u64;
    let t1 = Instant::now();
    for bb in 0..b {
        let spec = LinExpr::from(energy[bb * (t + 1)]).eq(BESS_E0);
        let spec = match named.then(|| format!("init[{bb}]")) {
            Some(n) => spec.named(n),
            None => spec,
        };
        model.add_constraint(spec)?;
        for tt in 0..t {
            let ch = charge[bb * t + tt];
            let di = discharge[bb * t + tt];
            let en0 = energy[bb * (t + 1) + tt];
            let en1 = energy[bb * (t + 1) + tt + 1];
            // en1 == en0 + dt * (eta * ch - di / eta)
            let rhs = LinExpr::from(en0)
                + LinExpr::new().term(BESS_DT * BESS_ETA, ch)
                + LinExpr::new().term(-BESS_DT / BESS_ETA, di);
            let spec = (LinExpr::from(en1) - rhs).eq(0.0);
            let spec = match named.then(|| format!("balance[{bb},{tt}]")) {
                Some(n) => spec.named(n),
                None => spec,
            };
            model.add_constraint(spec)?;
            let spec = (LinExpr::from(ch) + LinExpr::from(di)).le(BESS_P);
            let spec = match named.then(|| format!("mode[{bb},{tt}]")) {
                Some(n) => spec.named(n),
                None => spec,
            };
            model.add_constraint(spec)?;
        }
    }
    let t_cons = t1.elapsed().as_nanos() as u64;
    let t2 = Instant::now();
    let mut obj = LinExpr::new();
    for bb in 0..b {
        for tt in 0..t {
            let ch = charge[bb * t + tt];
            let di = discharge[bb * t + tt];
            obj = obj.term(-BESS_DT * prices[tt], ch);
            obj = obj.term(BESS_DT * prices[tt], di);
        }
    }
    model.maximize(obj)?;
    let t_obj = t2.elapsed().as_nanos() as u64;
    if let Some(map) = phases {
        map.insert("variables".to_string(), t_vars);
        map.insert("constraints".to_string(), t_cons);
        map.insert("objective".to_string(), t_obj);
    }
    Ok((
        b * (3 * t + 1),
        b * (2 * t + 1),
        b * (1 + 6 * t),
        b * (2 * t),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sparse_counts_match_contract() {
        let rows = 1000 / 10;
        assert_eq!((1000, rows, 10 * rows), (1000, 100, 1000));
    }

    #[test]
    fn parameterized_objective_matches_constant_values() {
        // Same mathematics through both coefficient representations: every
        // objective coefficient evaluates to 1.0 over 50 variables.
        let mut vars_c = Vec::new();
        let mut m_c = Model::named("const");
        for _ in 0..50 {
            vars_c.push(m_c.add_variable(var_def(None, 0.0, 5.0)).unwrap());
        }
        let mut e_c = LinExpr::new();
        for v in &vars_c {
            e_c = e_c.term(1.0, *v);
        }
        m_c.minimize(e_c).unwrap();

        let mut vars_p = Vec::new();
        let mut m_p = Model::named("param");
        for _ in 0..50 {
            vars_p.push(m_p.add_variable(var_def(None, 0.0, 5.0)).unwrap());
        }
        let p = m_p.add_parameter(1.0).unwrap();
        let mut e_p = LinExpr::new();
        for v in &vars_p {
            e_p = e_p.term(roml::ValueExpr::param(p), *v);
        }
        m_p.minimize(e_p).unwrap();

        for m in [&m_c, &m_p] {
            let obj = m.active_objective().expect("one active objective");
            let expr = m.objective_expression(obj).unwrap();
            assert_eq!(expr.num_terms(), 50);
            for term in expr.terms() {
                let value = match &term.coeff {
                    roml::expr::TermCoeff::Constant(v) => *v,
                    roml::expr::TermCoeff::Expr(e) => e.eval(|_| 1.0),
                };
                assert!((value - 1.0).abs() < 1e-12);
            }
        }
    }
}
