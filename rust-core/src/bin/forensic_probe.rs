//! Secondary observability + equivalence probe for the forensic passes.
//!
//! Builds the contract workloads natively (same `common` builders as the
//! timing runner, named entities to mirror the Python spellings) and
//! separately records what `populate_ms` does NOT include: commit,
//! snapshot, delta op count, coefficient count, peak RSS. Timings here are
//! structural diagnostics, not headline evidence; the authoritative
//! populate numbers come from the suite runs.
//!
//! `--equiv` additionally builds the same case through the OTHER
//! construction (scalar vs bulk), commits both, replays both journals
//! into [`ReferenceBackend`]s, and asserts full replay equality plus
//! snapshot equality. This is the native-bulk correctness link:
//! bulk ≡ scalar canonically, scalar ≡ Python by counts, Python by the
//! suite solve gate.
//!
//! Workload `bess_96_param` is the parametric diagnostic: BESS structure
//! with a `(B, T)` parameter price grid inserted through
//! [`Model::set_linear_objective_param_bulk`], then a ×1.1 price update,
//! reporting construction cells, update propagation, and changed-op
//! counts. Prices arrive via `--prices-csv` (suite-canonical) so the
//! reported cells cross-check the Python packed-parametric probe.

#[path = "../common.rs"]
mod common;

use common::{build_bess, build_bess_bulk, build_sparse, build_sparse_bulk, rss_bytes, BESS_T};
use roml::prelude::*;
use roml::solver::reference::ReferenceBackend;
use roml::sync::AdapterCursor;
use serde::Serialize;
use std::collections::BTreeMap;
use std::time::Instant;

const ROML_SHA: &str = "9cea1642508693238562d1f1be2edb95bacaf488";

#[derive(Serialize)]
struct ProbeRecord {
    roml_sha: String,
    workload: String,
    size: usize,
    replicate: u32,
    construction: String,
    phases_ms: BTreeMap<String, f64>,
    commit_ms: f64,
    snapshot_ms: f64,
    delta_ops: usize,
    coefficients: usize,
    variables: usize,
    constraints: usize,
    peak_rss_bytes: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    equiv_scalar_bulk: Option<EquivReport>,
}

#[derive(Serialize)]
struct EquivReport {
    snapshots_equal: bool,
    variables_equal: bool,
    constraints_equal: bool,
    constraint_cells_equal: bool,
    objective_cells_equal: bool,
    objectives_equal: bool,
    scalar_delta_ops: usize,
    bulk_delta_ops: usize,
}

fn replay(model: &Model) -> ReferenceBackend {
    let mut backend = ReferenceBackend::new();
    let cursor = AdapterCursor::new();
    for batch in model.deltas_since(cursor.applied_revision).unwrap() {
        for op in &batch.operations {
            backend.apply_op(op).expect("replay op applies");
        }
    }
    backend
}

fn check_equiv(scalar: &Model, bulk: &Model, scalar_ops: usize, bulk_ops: usize) -> EquivReport {
    // Allocation-independent comparison: the scalar builder inserts
    // init/balance/mode rows interleaved per battery while the bulk
    // builder inserts per group, so raw ConIds differ by design. What
    // must match is canonical semantics: same row multiset (bounds +
    // cells by variable), same objective cells by variable, same
    // snapshot function/set multiset. Variable creation order is
    // identical in both builders, so VarIds align and need no
    // normalization.
    fn sorted_strings(mut v: Vec<String>) -> Vec<String> {
        v.sort();
        v
    }
    let rs = replay(scalar);
    let rb = replay(bulk);
    let row_multiset = |cells: &std::collections::HashMap<
        (roml::model::CoefficientTarget, roml::VarId),
        (roml::ValueExpr, f64),
    >| {
        use std::collections::HashMap;
        let mut rows: HashMap<String, Vec<String>> = HashMap::new();
        for (key, (expr, val)) in cells {
            rows.entry(format!("{:?}", key.0))
                .or_default()
                .push(format!("{:?}|{expr:?}|{val}", key.1));
        }
        let mut out: Vec<String> = rows
            .into_values()
            .map(|mut cells| {
                cells.sort();
                cells.join(";")
            })
            .collect();
        out.sort();
        out
    };
    let snap = |model: &Model| model.take_snapshot().unwrap();
    let (ss, sb) = (snap(scalar), snap(bulk));
    let snap_fns = |snap: &roml::snapshot::ModelSnapshot| {
        sorted_strings(
            snap.functions
                .iter()
                .map(|e| format!("{:?}|{:?}", e.function, e.set))
                .collect(),
        )
    };
    let snap_cons = |snap: &roml::snapshot::ModelSnapshot| {
        sorted_strings(
            snap.constraints
                .iter()
                .map(|e| format!("{:?}|{}", e.bounds, e.active))
                .collect(),
        )
    };
    let snap_objs = |snap: &roml::snapshot::ModelSnapshot| {
        sorted_strings(
            snap.objectives
                .iter()
                .map(|e| format!("{:?}|{}|{}", e.sense, e.active, e.constant))
                .collect(),
        )
    };
    let obj_cells = |cells: &std::collections::HashMap<
        (roml::model::CoefficientTarget, roml::VarId),
        (roml::ValueExpr, f64, f64),
    >| {
        sorted_strings(
            cells
                .iter()
                .map(|(k, (e, v, c))| format!("{:?}|{e:?}|{v}|{c}", k.1))
                .collect(),
        )
    };
    EquivReport {
        snapshots_equal: snap_fns(&ss) == snap_fns(&sb)
            && snap_cons(&ss) == snap_cons(&sb)
            && snap_objs(&ss) == snap_objs(&sb),
        variables_equal: rs.variables == rb.variables,
        constraints_equal: sorted_strings(
            rs.constraints.values().map(|v| format!("{v:?}")).collect(),
        ) == sorted_strings(
            rb.constraints.values().map(|v| format!("{v:?}")).collect(),
        ),
        constraint_cells_equal: row_multiset(&rs.constraint_cells)
            == row_multiset(&rb.constraint_cells),
        objective_cells_equal: obj_cells(&rs.objective_cells) == obj_cells(&rb.objective_cells),
        objectives_equal: rs.objectives.len() == rb.objectives.len()
            && rs.objective_constants.values().collect::<Vec<_>>()
                == rb.objective_constants.values().collect::<Vec<_>>(),
        scalar_delta_ops: scalar_ops,
        bulk_delta_ops: bulk_ops,
    }
}

fn build_case(
    workload: &str,
    size: usize,
    prices: &[f64],
    construction: &str,
    phases: Option<&mut BTreeMap<String, u64>>,
) -> Model {
    let mut model = Model::new();
    match (workload, construction) {
        ("sparse_rows", "scalar") => {
            build_sparse(&mut model, size, true, false, phases).unwrap();
        }
        ("sparse_rows", "bulk") => {
            build_sparse_bulk(&mut model, size, true, phases).unwrap();
        }
        ("bess_96", "scalar") => {
            build_bess(&mut model, size, prices, true, phases).unwrap();
        }
        ("bess_96", "bulk") => {
            build_bess_bulk(&mut model, size, prices, true, phases).unwrap();
        }
        _ => {
            eprintln!("unknown workload/construction: {workload}/{construction}");
            std::process::exit(2);
        }
    }
    model
}

fn finish(
    workload: &str,
    size: usize,
    replicate: u32,
    construction: &str,
    mut model: Model,
    phases: BTreeMap<String, u64>,
    equiv: Option<EquivReport>,
) -> ProbeRecord {
    let phases_ms: BTreeMap<String, f64> = phases
        .into_iter()
        .map(|(k, v)| (k, v as f64 / 1e6))
        .collect();
    let variables = model.num_variables();
    let constraints = model.num_constraints();
    let t0 = Instant::now();
    model.commit().unwrap();
    let commit_ms = t0.elapsed().as_secs_f64() * 1e3;
    finish_committed(
        model,
        FinishArgs {
            workload: workload.to_string(),
            size,
            replicate,
            construction: construction.to_string(),
            phases_ms,
            commit_ms,
            variables,
            constraints,
            equiv,
        },
    )
}

struct FinishArgs {
    workload: String,
    size: usize,
    replicate: u32,
    construction: String,
    phases_ms: BTreeMap<String, f64>,
    commit_ms: f64,
    variables: usize,
    constraints: usize,
    equiv: Option<EquivReport>,
}

fn finish_committed(model: Model, args: FinishArgs) -> ProbeRecord {
    let cursor = AdapterCursor::new();
    let delta_ops: usize = model
        .deltas_since(cursor.applied_revision)
        .unwrap()
        .iter()
        .map(|b| b.operations.len())
        .sum();
    let coefficients = model.num_coefficients();
    let t0 = Instant::now();
    model.take_snapshot().unwrap();
    let snapshot_ms = t0.elapsed().as_secs_f64() * 1e3;
    let (_, peak) = rss_bytes();
    ProbeRecord {
        roml_sha: ROML_SHA.to_string(),
        workload: args.workload,
        size: args.size,
        replicate: args.replicate,
        construction: args.construction,
        phases_ms: args.phases_ms,
        commit_ms: args.commit_ms,
        snapshot_ms,
        delta_ops,
        coefficients,
        variables: args.variables,
        constraints: args.constraints,
        peak_rss_bytes: peak,
        equiv_scalar_bulk: args.equiv,
    }
}

#[derive(Serialize)]
struct ParamReport {
    roml_sha: String,
    workload: String,
    size: usize,
    replicate: u32,
    build_ms: f64,
    objective_cells: usize,
    sample_initial: Vec<f64>,
    update_ms: f64,
    changed_cells: usize,
    sample_updated: Vec<f64>,
    update_factor_ok: bool,
    peak_rss_bytes: u64,
}

/// Parametric diagnostic: BESS structure, `(B, T)` parameter price grid,
/// `set_linear_objective_param_bulk` with scales ±dt, then a ×1.1 update.
fn probe_param_bess(b: usize, replicate: u32, prices: &[f64]) -> ParamReport {
    use roml::Sense;
    let t = BESS_T;
    let t0 = Instant::now();
    let mut model = Model::new();
    // Same variable structure as build_bess_bulk (flat names, same bounds).
    let mut charge = Vec::with_capacity(b * t);
    let mut discharge = Vec::with_capacity(b * t);
    let mut energy = Vec::with_capacity(b * (t + 1));
    for i in 0..b * t {
        charge.push(
            model
                .add_variable(continuous().bounds(0.0, 2.0).named(format!("charge[{i}]")))
                .unwrap(),
        );
    }
    for i in 0..b * t {
        discharge.push(
            model
                .add_variable(
                    continuous()
                        .bounds(0.0, 2.0)
                        .named(format!("discharge[{i}]")),
                )
                .unwrap(),
        );
    }
    for i in 0..b * (t + 1) {
        energy.push(
            model
                .add_variable(continuous().bounds(0.0, 4.0).named(format!("energy[{i}]")))
                .unwrap(),
        );
    }
    // One anonymous parameter per cell (mirrors the Python (B, T)
    // ParamArray: b*t distinct identities holding tiled values).
    let price_grid: Vec<roml::ParamId> = prices
        .iter()
        .cycle()
        .take(b * t)
        .map(|v| model.add_parameter(*v).unwrap())
        .collect();
    // Balance/mode/init rows via the scalar path (structure only; the
    // diagnostic under test is the parametric objective).
    for bb in 0..b {
        let spec = roml::LinExpr::from(energy[bb * (t + 1)]).eq(2.0);
        model.add_constraint(spec).unwrap();
        for tt in 0..t {
            let rhs = roml::LinExpr::from(energy[bb * (t + 1) + tt])
                + roml::LinExpr::new().term(0.25 * 0.95, charge[bb * t + tt])
                + roml::LinExpr::new().term(-0.25 / 0.95, discharge[bb * t + tt]);
            model
                .add_constraint((roml::LinExpr::from(energy[bb * (t + 1) + tt + 1]) - rhs).eq(0.0))
                .unwrap();
            model
                .add_constraint(
                    (roml::LinExpr::from(charge[bb * t + tt])
                        + roml::LinExpr::from(discharge[bb * t + tt]))
                    .le(2.0),
                )
                .unwrap();
        }
    }
    // Parametric objective in C-order: discharge (+dt*price), charge (−dt*price).
    let n = b * t;
    let mut obj_vars = Vec::with_capacity(2 * n);
    let mut obj_params = Vec::with_capacity(2 * n);
    let mut obj_scales = Vec::with_capacity(2 * n);
    for i in 0..n {
        obj_vars.push(discharge[i]);
        obj_params.push(price_grid[i]);
        obj_scales.push(0.25);
    }
    for i in 0..n {
        obj_vars.push(charge[i]);
        obj_params.push(price_grid[i]);
        obj_scales.push(-0.25);
    }
    let obj = model
        .set_linear_objective_param_bulk(Sense::Maximize, &obj_vars, &obj_params, &obj_scales, 0.0)
        .unwrap();
    model.commit().unwrap();
    let build_ms = t0.elapsed().as_secs_f64() * 1e3;
    let cells = replay(&model);
    let key_of = |v: roml::VarId| (roml::model::CoefficientTarget::Objective(obj), v);
    let sample_initial: Vec<f64> = [0, 1, n / 2, n - 1]
        .iter()
        .map(|i| cells.objective_cells[&key_of(discharge[*i])].1)
        .collect();
    // ×1.1 price update through the transaction + commit, then replay.
    // Every cell has its own parameter (like the Python ParamArray), so
    // all b*t are updated — the same propagation shape the Python probe
    // exercises.
    let t0 = Instant::now();
    for (i, p) in price_grid.iter().enumerate() {
        model.set_parameter(*p, prices[i % BESS_T] * 1.1).unwrap();
    }
    model.commit().unwrap();
    let update_ms = t0.elapsed().as_secs_f64() * 1e3;
    let cells2 = replay(&model);
    let sample_updated: Vec<f64> = [0, 1, n / 2, n - 1]
        .iter()
        .map(|i| cells2.objective_cells[&key_of(discharge[*i])].1)
        .collect();
    let update_factor_ok = sample_initial
        .iter()
        .zip(sample_updated.iter())
        .all(|(a, b)| (b - a * 1.1).abs() <= 1e-9 * a.abs().max(1.0));
    let changed_cells = cells2
        .objective_cells
        .iter()
        .filter(|(k, v)| {
            cells
                .objective_cells
                .get(k)
                .map(|old| (old.1 - v.1).abs() >= f64::EPSILON)
                .unwrap_or(true)
        })
        .count();
    let (_, peak) = rss_bytes();
    ParamReport {
        roml_sha: ROML_SHA.to_string(),
        workload: "bess_96_param".to_string(),
        size: b,
        replicate,
        build_ms,
        objective_cells: cells.objective_cells.len(),
        sample_initial,
        update_ms,
        changed_cells,
        sample_updated,
        update_factor_ok,
        peak_rss_bytes: peak,
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let get = |flag: &str| -> Option<String> {
        args.windows(2).find(|w| w[0] == flag).map(|w| w[1].clone())
    };
    let workload = get("--workload").unwrap_or_else(|| "sparse_rows".to_string());
    let size: usize = get("--size").and_then(|s| s.parse().ok()).unwrap_or(10_000);
    let replicate: u32 = get("--replicate").and_then(|s| s.parse().ok()).unwrap_or(0);
    let construction = get("--construction").unwrap_or_else(|| "scalar".to_string());
    let equiv = args.iter().any(|a| a == "--equiv");
    let _ = get("--cpu");
    // CPU pinning is the caller's job (taskset); this probe never pins
    // itself so it cannot disturb a pinned suite run.
    let prices: Vec<f64> = get("--prices-csv")
        .map(|csv| csv.split(',').map(|s| s.trim().parse().unwrap()).collect())
        .unwrap_or_else(|| {
            (0..BESS_T)
                .map(|i| {
                    20.0 + 60.0 * (((i as u64).wrapping_mul(2654435761) % 100003) as f64 / 100003.0)
                })
                .collect()
        });
    if workload == "bess_96_param" {
        assert_eq!(prices.len(), BESS_T, "bess_96_param needs 96 prices");
        println!(
            "{}",
            serde_json::to_string(&probe_param_bess(size, replicate, &prices)).unwrap()
        );
        return;
    }
    let mut phases = BTreeMap::new();
    let model = build_case(&workload, size, &prices, &construction, Some(&mut phases));
    if equiv {
        let other = if construction == "bulk" {
            "scalar"
        } else {
            "bulk"
        };
        let mut other_model = build_case(&workload, size, &prices, other, None);
        // Commit both sides (timing the primary's first commit), then
        // compare journals, replays, and snapshots.
        let variables = model.num_variables();
        let constraints = model.num_constraints();
        let phases_ms: BTreeMap<String, f64> = phases
            .into_iter()
            .map(|(k, v)| (k, v as f64 / 1e6))
            .collect();
        let mut model = model;
        let t0 = Instant::now();
        model.commit().unwrap();
        let commit_ms = t0.elapsed().as_secs_f64() * 1e3;
        other_model.commit().unwrap();
        let rep = {
            let model_ops = op_count(&model);
            let other_ops = op_count(&other_model);
            // check_equiv(scalar, bulk, scalar_ops, bulk_ops).
            if construction == "bulk" {
                check_equiv(&other_model, &model, other_ops, model_ops)
            } else {
                check_equiv(&model, &other_model, model_ops, other_ops)
            }
        };
        let rec = finish_committed(
            model,
            FinishArgs {
                workload: workload.clone(),
                size,
                replicate,
                construction: construction.clone(),
                phases_ms,
                commit_ms,
                variables,
                constraints,
                equiv: Some(rep),
            },
        );
        print_record(&rec);
        return;
    }
    let rec = finish(
        &workload,
        size,
        replicate,
        &construction,
        model,
        phases,
        None,
    );
    print_record(&rec);
}

fn op_count(model: &Model) -> usize {
    let cursor = AdapterCursor::new();
    model
        .deltas_since(cursor.applied_revision)
        .unwrap()
        .iter()
        .map(|b| b.operations.len())
        .sum()
}

fn print_record(rec: &ProbeRecord) {
    println!("{}", serde_json::to_string(rec).unwrap());
}
