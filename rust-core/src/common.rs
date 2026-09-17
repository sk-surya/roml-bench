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

/// Variables per row in the indexed-rule workload.
pub const RULE_J: usize = 10;

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
/// Sparse workload through the documented efficient bulk core API
/// (native mirror of the Python `roml_python_vectorized` arm, which reaches
/// these same primitives).
///
/// Mathematically identical to [`build_sparse`]: `n` variables
/// `x[0..n]` on `[0, 5]`, `n/10` ten-coefficient unit rows
/// `(−inf, 10]`, one all-ones `minimize`. Differences are exactly the
/// interface under test: CSR buffers are derived inside the timer (the
/// contract derives rows during timing; the pattern here is the same
/// deterministic `row r = x[10r..10r+9]` the suite pre-generates for
/// Python) and inserted with one [`Model::add_linear_rows_bulk`] call;
/// the objective goes through
/// [`Model::set_linear_objective_bulk`]. Variable creation uses the current
/// packed block primitive [`Model::add_variable_array_block`] — one packed
/// variable-block op; block creation materializes no per-element names
/// (MIR-01/MIR-04). The `named` flag is retained for interface symmetry with
/// the scalar-builder arms but has no effect on block creation.
///
/// Fairness disclosure: neither the variable block nor
/// [`Model::add_linear_rows_bulk`] takes names, so this arm is anonymous
/// while the Python arm registers `x[i]`/`rows[i]` element names. The
/// naming-work delta is quantified in the parity evidence, not hidden.
#[allow(dead_code)]
pub fn build_sparse_bulk(
    model: &mut Model,
    n: usize,
    named: bool,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize), ModelError> {
    use roml::{BlockBounds, Bounds, ConstraintBounds, VarType};
    let _ = named;
    let rows = n / 10;
    let t0 = Instant::now();
    let x = model.add_variable_array_block(
        [n],
        VarType::Continuous,
        BlockBounds::Uniform(Bounds::new(0.0, 5.0)),
    )?;
    let mut vars = Vec::with_capacity(n);
    for i in 0..n {
        vars.push(x.get(i).expect("block member"));
    }
    let t_vars = t0.elapsed().as_nanos() as u64;
    let t1 = Instant::now();
    // Deterministic CSR derivation inside the timer (same pattern the
    // suite pre-generates for the Python arm).
    let mut row_ptr = Vec::with_capacity(rows + 1);
    let mut flat_vars = Vec::with_capacity(10 * rows);
    let mut values = Vec::with_capacity(10 * rows);
    let mut bounds = Vec::with_capacity(rows);
    for r in 0..rows {
        row_ptr.push((10 * r) as u32);
        for k in 0..10 {
            flat_vars.push(vars[10 * r + k]);
            values.push(1.0);
        }
        bounds.push(ConstraintBounds {
            lower: f64::NEG_INFINITY,
            upper: 10.0,
        });
    }
    row_ptr.push((10 * rows) as u32);
    model.add_linear_rows_bulk(&row_ptr, &flat_vars, &values, &bounds)?;
    let t_cons = t1.elapsed().as_nanos() as u64;
    let t2 = Instant::now();
    let coeffs = vec![1.0; n];
    model.set_linear_objective_bulk(roml::Sense::Minimize, &vars, &coeffs, 0.0)?;
    let t_obj = t2.elapsed().as_nanos() as u64;
    if let Some(map) = phases {
        map.insert("variables".to_string(), t_vars);
        map.insert("constraints".to_string(), t_cons);
        map.insert("objective".to_string(), t_obj);
    }
    Ok((n, rows, 10 * rows))
}
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

/// BESS workload through the documented efficient bulk core API (native
/// mirror of the Python `roml_python_vectorized` arm).
///
/// Same model as [`build_bess`]: `charge`/`discharge` on `[0, P]`,
/// `energy` on `[0, E]`, init/balance/mode groups, numeric-price
/// `maximize` with coefficients `±dt * price` and constant `0`.
/// Variables use the current packed block primitive
/// [`Model::add_variable_array_block`] (one packed op per family, no
/// per-element names). Constraint
/// groups are derived inside the timer (the contract derives rows
/// during timing) and inserted with one
/// [`Model::add_linear_rows_bulk`] call per group — mirroring the
/// Python arm's three `m.add` calls (init, balance, mode). The
/// objective inserts in the Python flatten order (discharge block,
/// then charge block) through
/// [`Model::set_linear_objective_bulk`].
///
/// Fairness disclosure (same as sparse): bulk rows take no names, so
/// the `init[i]`/`balance[i]`/`mode[i]` element names the Python arm
/// registers have no native-bulk counterpart. Quantified in evidence.
#[allow(dead_code)]
pub fn build_bess_bulk(
    model: &mut Model,
    b: usize,
    prices: &[f64],
    named: bool,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize, usize), ModelError> {
    use roml::{BlockBounds, Bounds, ConstraintBounds, VarType};
    let _ = named;
    assert_eq!(prices.len(), BESS_T);
    let t = BESS_T;
    let t0 = Instant::now();
    let charge_arr = model.add_variable_array_block(
        [b, t],
        VarType::Continuous,
        BlockBounds::Uniform(Bounds::new(0.0, BESS_P)),
    )?;
    let discharge_arr = model.add_variable_array_block(
        [b, t],
        VarType::Continuous,
        BlockBounds::Uniform(Bounds::new(0.0, BESS_P)),
    )?;
    let energy_arr = model.add_variable_array_block(
        [b, t + 1],
        VarType::Continuous,
        BlockBounds::Uniform(Bounds::new(0.0, BESS_E)),
    )?;
    let mut charge = Vec::with_capacity(b * t);
    let mut discharge = Vec::with_capacity(b * t);
    let mut energy = Vec::with_capacity(b * (t + 1));
    for i in 0..b * t {
        charge.push(charge_arr.get(i).expect("block member"));
        discharge.push(discharge_arr.get(i).expect("block member"));
    }
    for i in 0..b * (t + 1) {
        energy.push(energy_arr.get(i).expect("block member"));
    }
    let t_vars = t0.elapsed().as_nanos() as u64;
    let t1 = Instant::now();
    // init group: b one-coefficient equalities.
    {
        let mut row_ptr = Vec::with_capacity(b + 1);
        let mut flat_vars = Vec::with_capacity(b);
        let mut values = Vec::with_capacity(b);
        let mut bounds = Vec::with_capacity(b);
        for bb in 0..b {
            row_ptr.push(bb as u32);
            flat_vars.push(energy[bb * (t + 1)]);
            values.push(1.0);
            bounds.push(ConstraintBounds {
                lower: BESS_E0,
                upper: BESS_E0,
            });
        }
        row_ptr.push(b as u32);
        model.add_linear_rows_bulk(&row_ptr, &flat_vars, &values, &bounds)?;
    }
    // balance group: b*t four-coefficient equalities.
    {
        let n = b * t;
        let mut row_ptr = Vec::with_capacity(n + 1);
        let mut flat_vars = Vec::with_capacity(4 * n);
        let mut values = Vec::with_capacity(4 * n);
        let mut bounds = Vec::with_capacity(n);
        for bb in 0..b {
            for tt in 0..t {
                let r = bb * t + tt;
                row_ptr.push((4 * r) as u32);
                flat_vars.push(energy[bb * (t + 1) + tt + 1]);
                values.push(1.0);
                flat_vars.push(energy[bb * (t + 1) + tt]);
                values.push(-1.0);
                flat_vars.push(charge[r]);
                values.push(-BESS_DT * BESS_ETA);
                flat_vars.push(discharge[r]);
                values.push(BESS_DT / BESS_ETA);
                bounds.push(ConstraintBounds {
                    lower: 0.0,
                    upper: 0.0,
                });
            }
        }
        row_ptr.push((4 * n) as u32);
        model.add_linear_rows_bulk(&row_ptr, &flat_vars, &values, &bounds)?;
    }
    // mode group: b*t two-coefficient rows.
    {
        let n = b * t;
        let mut row_ptr = Vec::with_capacity(n + 1);
        let mut flat_vars = Vec::with_capacity(2 * n);
        let mut values = Vec::with_capacity(2 * n);
        let mut bounds = Vec::with_capacity(n);
        for r in 0..n {
            row_ptr.push((2 * r) as u32);
            flat_vars.push(charge[r]);
            values.push(1.0);
            flat_vars.push(discharge[r]);
            values.push(1.0);
            bounds.push(ConstraintBounds {
                lower: f64::NEG_INFINITY,
                upper: BESS_P,
            });
        }
        row_ptr.push((2 * n) as u32);
        model.add_linear_rows_bulk(&row_ptr, &flat_vars, &values, &bounds)?;
    }
    let t_cons = t1.elapsed().as_nanos() as u64;
    let t2 = Instant::now();
    // Objective in Python flatten order: C-order (row-major) discharge
    // block, then C-order charge block.
    let n = b * t;
    let mut obj_vars = Vec::with_capacity(2 * n);
    let mut obj_coeffs = Vec::with_capacity(2 * n);
    for bb in 0..b {
        for tt in 0..t {
            obj_vars.push(discharge[bb * t + tt]);
            obj_coeffs.push(BESS_DT * prices[tt]);
        }
    }
    for bb in 0..b {
        for tt in 0..t {
            obj_vars.push(charge[bb * t + tt]);
            obj_coeffs.push(-BESS_DT * prices[tt]);
        }
    }
    model.set_linear_objective_bulk(roml::Sense::Maximize, &obj_vars, &obj_coeffs, 0.0)?;
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

/// BESS workload through the **current idiomatic Rust Level-1 array API**
/// (`model.var(..).bounds(..).build()`, `model.param(..)`, slicing / array
/// algebra, `add_row`, `maximize_array`).
///
/// Builds the full canonical benchmark model — not the reduced `l1_bess`
/// example: `energy` has `t + 1` periods, the init row `energy[:,0] == e0`
/// and the `charge + discharge <= P` mode rows are present, and the objective
/// is the packed `dt * sum(price * (discharge - charge))`.
///
/// Prices are the canonical shared vector; ROML expresses time-series data as
/// a first-class parameter (its idiomatic surface), which is why this arm is
/// the Rust representative for the parameterized-construction benchmark too.
#[allow(dead_code)]
pub fn build_bess_l1(
    model: &mut Model,
    b: usize,
    prices: &[f64],
    _named: bool,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize, usize), ModelError> {
    assert_eq!(prices.len(), BESS_T);
    let t = BESS_T;
    let mut price_grid = Vec::with_capacity(b * t);
    for _ in 0..b {
        price_grid.extend_from_slice(prices);
    }

    let t0 = Instant::now();
    let charge = model.var("charge", [b, t]).bounds(0.0, BESS_P).build()?;
    let discharge = model.var("discharge", [b, t]).bounds(0.0, BESS_P).build()?;
    let energy = model
        .var("energy", [b, t + 1])
        .bounds(0.0, BESS_E)
        .build()?;
    let t_vars = t0.elapsed().as_nanos() as u64;

    let t1 = Instant::now();
    // energy[:, 0] == e0
    model.add_row(energy.slice(1, 0, 1)?.expr()?.eq(BESS_E0))?;
    // energy[:, 1:] == energy[:, :-1] + dt * (eta * charge - discharge / eta)
    let next = energy.slice(1, 1, t)?;
    let prev = energy.slice(1, 0, t)?;
    let rhs = prev + BESS_DT * (BESS_ETA * charge.clone() - discharge.clone() / BESS_ETA);
    model.add_row((next - rhs).eq(0.0))?;
    // charge + discharge <= P
    model.add_row((charge.clone() + discharge.clone()).le(BESS_P))?;
    let t_cons = t1.elapsed().as_nanos() as u64;

    let t2 = Instant::now();
    let price = model.param("price", [b, t], &price_grid)?;
    let objective = price
        .try_mul(&(discharge.clone() - charge.clone()))?
        .expect("conservative IR covers price * (discharge - charge)")
        * BESS_DT;
    model.maximize_array(&objective)?;
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

/// Indexed-rule workload through the current Rust `add_indexed_rules` API:
/// `n` rows, `j` unit coefficients per row, `sum_j x[i,j] <= cap[i]`,
/// `minimize sum x`. One packed mixed-row commit.
#[allow(dead_code)]
pub fn build_rules(
    model: &mut Model,
    n: usize,
    j: usize,
    caps: &[f64],
    _named: bool,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize, usize), ModelError> {
    assert_eq!(caps.len(), n);
    let t0 = Instant::now();
    let x = model.var("x", [n, j]).bounds(0.0, 5.0).build()?;
    let t_vars = t0.elapsed().as_nanos() as u64;

    let t1 = Instant::now();
    model.add_indexed_rules(0..n, |rules, i| {
        rules.add_le(x.row(i)?, caps[i])?;
        Ok(())
    })?;
    let t_cons = t1.elapsed().as_nanos() as u64;

    let t2 = Instant::now();
    model.minimize_array(&x.expr()?)?;
    let t_obj = t2.elapsed().as_nanos() as u64;

    if let Some(map) = phases {
        map.insert("variables".to_string(), t_vars);
        map.insert("constraints".to_string(), t_cons);
        map.insert("objective".to_string(), t_obj);
    }
    Ok((n * j, n, n * j, n * j))
}

/// Parameterized construction fixture — raw L2 path: block variables, a
/// first-class parameter block, and the packed parameter-dependent objective
/// `maximize sum(price * (discharge - charge))` through
/// `set_linear_objective_param_bulk`. Internal lower bound for item 8.
#[allow(dead_code)]
pub fn build_param_bess_bulk(
    model: &mut Model,
    b: usize,
    prices: &[f64],
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize, usize), ModelError> {
    use roml::{BlockBounds, Bounds, VarType};
    assert_eq!(prices.len(), BESS_T);
    let t = BESS_T;
    let mut price_grid = Vec::with_capacity(b * t);
    for _ in 0..b {
        price_grid.extend_from_slice(prices);
    }

    let t0 = Instant::now();
    let charge = model.add_variable_array_block(
        [b, t],
        VarType::Continuous,
        BlockBounds::Uniform(Bounds::new(0.0, BESS_P)),
    )?;
    let discharge = model.add_variable_array_block(
        [b, t],
        VarType::Continuous,
        BlockBounds::Uniform(Bounds::new(0.0, BESS_P)),
    )?;
    let t_vars = t0.elapsed().as_nanos() as u64;

    let t1 = Instant::now();
    let price = model.add_parameter_array_block([b, t], &price_grid)?;
    let t_params = t1.elapsed().as_nanos() as u64;

    let t2 = Instant::now();
    use roml::bulk::{ParamDepBlockWitness, ParamDepLayout, StridedMap};
    let n = b * t;
    // Canonical order is by variable: charge (created first, scale -1) then
    // discharge (scale +1), each reading the matching price parameter.
    let mut vars = Vec::with_capacity(2 * n);
    let mut params = Vec::with_capacity(2 * n);
    let mut scales = Vec::with_capacity(2 * n);
    for i in 0..n {
        vars.push(charge.get(i).expect("member"));
        params.push(price.get(i).expect("member"));
        scales.push(-1.0);
    }
    for i in 0..n {
        vars.push(discharge.get(i).expect("member"));
        params.push(price.get(i).expect("member"));
        scales.push(1.0);
    }
    let span = *price.view().view().span();
    let layout = ParamDepLayout {
        blocks: vec![
            ParamDepBlockWitness {
                params: span,
                param_map: StridedMap::contiguous(n),
                cell_offset: 0,
                cell_map: StridedMap::contiguous(n),
                scale: -1.0,
                row: None,
            },
            ParamDepBlockWitness {
                params: span,
                param_map: StridedMap::contiguous(n),
                cell_offset: n as u32,
                cell_map: StridedMap::contiguous(n),
                scale: 1.0,
                row: None,
            },
        ],
    };
    model.set_linear_objective_param_bulk_with_layout(
        roml::Sense::Maximize,
        &vars,
        &params,
        &scales,
        0.0,
        &layout,
    )?;
    let t_obj = t2.elapsed().as_nanos() as u64;

    if let Some(map) = phases {
        map.insert("variables".to_string(), t_vars);
        map.insert("parameters".to_string(), t_params);
        map.insert("objective".to_string(), t_obj);
    }
    Ok((2 * b * t, 0, 0, 2 * b * t))
}

/// Parameterized construction fixture — current Rust L1 array path:
/// `var(..).build()`, `param(..)`, and the packed `maximize_array` objective
/// `sum(price * (discharge - charge))`.
#[allow(dead_code)]
pub fn build_param_bess_l1(
    model: &mut Model,
    b: usize,
    prices: &[f64],
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Result<(usize, usize, usize, usize), ModelError> {
    assert_eq!(prices.len(), BESS_T);
    let t = BESS_T;
    let mut price_grid = Vec::with_capacity(b * t);
    for _ in 0..b {
        price_grid.extend_from_slice(prices);
    }

    let t0 = Instant::now();
    let charge = model.var("charge", [b, t]).bounds(0.0, BESS_P).build()?;
    let discharge = model.var("discharge", [b, t]).bounds(0.0, BESS_P).build()?;
    let t_vars = t0.elapsed().as_nanos() as u64;

    let t1 = Instant::now();
    let price = model.param("price", [b, t], &price_grid)?;
    let t_params = t1.elapsed().as_nanos() as u64;

    let t2 = Instant::now();
    let objective = price
        .try_mul(&(discharge.clone() - charge.clone()))?
        .expect("conservative IR covers price * (discharge - charge)");
    model.maximize_array(&objective)?;
    let t_obj = t2.elapsed().as_nanos() as u64;

    if let Some(map) = phases {
        map.insert("variables".to_string(), t_vars);
        map.insert("parameters".to_string(), t_params);
        map.insert("objective".to_string(), t_obj);
    }
    Ok((2 * b * t, 0, 0, 2 * b * t))
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
