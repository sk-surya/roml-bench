//! Allocation-counting diagnostic for P0 objective research.
//!
//! Runs the same construction code as `roml-bench-core` (via `common`, same
//! `roml` pin) under a counting global allocator and reports per-phase
//! allocation pressure plus a sub-phase split of the sparse objective
//! (expression build vs standalone `simplify` on a throwaway copy vs
//! `minimize` insertion).
//!
//! This binary's timings are NOT authoritative latency evidence: the allocator
//! shim adds atomic operations to every allocation. Authoritative timings
//! come from `roml-bench-core` built without this shim. Records emitted here
//! carry `status: "ok-counting"` and must never enter benchmark runs.

#[path = "../common.rs"]
mod common;

use common::{build_bess, rss_bytes, var_def, BESS_T};
use roml::prelude::*;
use serde::Serialize;
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

const ROML_SHA: &str = "9cea1642508693238562d1f1be2edb95bacaf488";

static ALLOC_CALLS: AtomicU64 = AtomicU64::new(0);
static ALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
static DEALLOC_CALLS: AtomicU64 = AtomicU64::new(0);
static DEALLOC_BYTES: AtomicU64 = AtomicU64::new(0);

struct CountingAlloc;

unsafe impl GlobalAlloc for CountingAlloc {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOC_CALLS.fetch_add(1, Ordering::Relaxed);
        ALLOC_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        DEALLOC_CALLS.fetch_add(1, Ordering::Relaxed);
        DEALLOC_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        unsafe { System.dealloc(ptr, layout) };
    }
}

#[global_allocator]
static GLOBAL: CountingAlloc = CountingAlloc;

#[derive(Clone, Copy, Serialize)]
struct AllocDelta {
    alloc_calls: u64,
    alloc_bytes: u64,
    dealloc_calls: u64,
    dealloc_bytes: u64,
}

fn snapshot() -> (u64, u64, u64, u64) {
    (
        ALLOC_CALLS.load(Ordering::Relaxed),
        ALLOC_BYTES.load(Ordering::Relaxed),
        DEALLOC_CALLS.load(Ordering::Relaxed),
        DEALLOC_BYTES.load(Ordering::Relaxed),
    )
}

fn delta(before: (u64, u64, u64, u64), after: (u64, u64, u64, u64)) -> AllocDelta {
    AllocDelta {
        alloc_calls: after.0 - before.0,
        alloc_bytes: after.1 - before.1,
        dealloc_calls: after.2 - before.2,
        dealloc_bytes: after.3 - before.3,
    }
}

#[derive(Serialize)]
struct PhaseAlloc {
    time_ns: u64,
    #[serde(flatten)]
    alloc: AllocDelta,
}

#[derive(Serialize)]
struct ObjectiveSplit {
    expr_build: PhaseAlloc,
    simplify_standalone: PhaseAlloc,
    minimize_insert: PhaseAlloc,
}

#[derive(Serialize)]
struct Record {
    schema_version: u32,
    run_id: String,
    timestamp_utc: String,
    benchmark_sha: String,
    roml_sha: String,
    implementation: String,
    workload: String,
    size: usize,
    objective_mode: String,
    anonymous: bool,
    variables: usize,
    constraints: usize,
    constraint_nnz: usize,
    objective_nnz: usize,
    replicate: u32,
    seed: u64,
    status: String,
    error: Option<String>,
    phases_ns: std::collections::BTreeMap<String, u64>,
    phases_alloc: std::collections::BTreeMap<String, AllocDelta>,
    objective_split: Option<ObjectiveSplit>,
    rss_before_bytes: u64,
    rss_after_bytes: u64,
    peak_rss_bytes: u64,
}

fn usage() -> ! {
    eprintln!(
        "usage: roml-ops-probe --workload <sparse_rows|bess_96> --size <N> \
         --seed <u64> --replicate <u32> --run-id <id> --benchmark-sha <sha> \
         --roml-sha <sha> --timestamp-utc <ts> [--prices-csv <csv>] \
         [--anonymous] [--objective-mode <constant|parameterized>]"
    );
    std::process::exit(2);
}

fn get(args: &[String], flag: &str) -> Option<String> {
    args.windows(2).find(|w| w[0] == flag).map(|w| w[1].clone())
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let req = |flag: &str| match get(&raw, flag) {
        Some(v) => v,
        None => usage(),
    };
    let workload = req("--workload");
    if workload != "sparse_rows" && workload != "bess_96" {
        usage();
    }
    let size: usize = req("--size").parse().unwrap_or_else(|_| usage());
    let seed: u64 = req("--seed").parse().unwrap_or_else(|_| usage());
    let replicate: u32 = req("--replicate").parse().unwrap_or_else(|_| usage());
    let run_id = req("--run-id");
    let benchmark_sha = req("--benchmark-sha");
    let roml_sha = req("--roml-sha");
    let timestamp_utc = req("--timestamp-utc");
    let anonymous = raw.iter().any(|a| a == "--anonymous");
    let objective_mode = get(&raw, "--objective-mode").unwrap_or_else(|| "constant".to_string());
    if objective_mode != "constant" && objective_mode != "parameterized" {
        usage();
    }
    if roml_sha != ROML_SHA {
        eprintln!("roml_sha mismatch: probe built for {ROML_SHA}");
        std::process::exit(2);
    }
    if workload == "bess_96" && objective_mode == "parameterized" {
        eprintln!("bess_96 has no parameterized-objective mode in this build");
        std::process::exit(2);
    }
    let prices: Option<Vec<f64>> = get(&raw, "--prices-csv").map(|csv| {
        csv.split(',')
            .map(|s| s.trim().parse().unwrap_or_else(|_| usage()))
            .collect()
    });
    if workload == "bess_96" {
        match &prices {
            Some(p) if p.len() == BESS_T => {}
            _ => {
                eprintln!("bess_96 requires --prices-csv with {BESS_T} values");
                std::process::exit(2);
            }
        }
    }

    // Warmup outside all snapshots (also settles the allocator).
    {
        let mut warm = Model::named("warmup");
        let x = warm
            .add_variable(continuous().bounds(0.0, 5.0).named("x"))
            .expect("warmup var");
        warm.add_constraint(LinExpr::from(x).le(10.0).named("r"))
            .expect("warmup con");
        warm.minimize(LinExpr::from(x)).expect("warmup obj");
    }

    let parameterized = objective_mode == "parameterized";
    let named = !anonymous;
    let (rss_before, _) = rss_bytes();
    let mut phases_ns = std::collections::BTreeMap::new();
    let mut phases_alloc = std::collections::BTreeMap::new();
    let mut objective_split = None;

    let mut model = Model::named(workload.clone());
    let counts = if workload == "sparse_rows" {
        // Instrumented sparse build with an objective sub-phase split.
        let n = size;
        let rows = n / 10;
        let a0 = snapshot();
        let t0 = Instant::now();
        let mut vars = Vec::with_capacity(n);
        for i in 0..n {
            let name = named.then(|| format!("x[{i}]"));
            vars.push(model.add_variable(var_def(name, 0.0, 5.0)).expect("var"));
        }
        let t_vars = t0.elapsed().as_nanos() as u64;
        let a1 = snapshot();
        phases_ns.insert("variables".to_string(), t_vars);
        phases_alloc.insert("variables".to_string(), delta(a0, a1));

        let a2 = snapshot();
        let t1 = Instant::now();
        for r in 0..rows {
            let base = 10 * r;
            let mut expr = LinExpr::new();
            for k in 0..10 {
                expr = expr.term(1.0, vars[base + k]);
            }
            let name = named.then(|| format!("row[{r}]"));
            model
                .add_constraint(common::con_spec(expr, name, 10.0))
                .expect("row");
        }
        let t_cons = t1.elapsed().as_nanos() as u64;
        let a3 = snapshot();
        phases_ns.insert("constraints".to_string(), t_cons);
        phases_alloc.insert("constraints".to_string(), delta(a2, a3));

        // Objective sub-split: build the expression, simplify a throwaway
        // clone standalone (isolates simplify's time/allocations), then run
        // the real insertion (which re-simplifies internally).
        let mut build_expr = || {
            let mut total = LinExpr::new();
            if parameterized {
                let p = model.add_parameter(1.0).expect("param");
                for v in &vars {
                    total = total.term(roml::ValueExpr::param(p), *v);
                }
            } else {
                for v in &vars {
                    total = total.term(1.0, *v);
                }
            }
            total
        };
        let b0 = snapshot();
        let t2 = Instant::now();
        let total = build_expr();
        let t_expr = t2.elapsed().as_nanos() as u64;
        let b1 = snapshot();

        let s0 = snapshot();
        let t3 = Instant::now();
        let _ = total.clone().simplify();
        let t_simplify = t3.elapsed().as_nanos() as u64;
        let s1 = snapshot();

        // Drop the throwaway simplification's peak before insertion so the
        // insert phase starts from the same state as the timing runner.
        let m0 = snapshot();
        let t4 = Instant::now();
        model.minimize(total).expect("objective");
        let t_insert = t4.elapsed().as_nanos() as u64;
        let m1 = snapshot();

        phases_ns.insert("objective".to_string(), t_expr + t_simplify + t_insert);
        // The standalone simplify is extra work the timing runner never
        // does; report the insert-phase allocations (which match the timing
        // runner's objective phase) separately from the split components.
        phases_alloc.insert("objective_insert_only".to_string(), delta(m0, m1));
        objective_split = Some(ObjectiveSplit {
            expr_build: PhaseAlloc {
                time_ns: t_expr,
                alloc: delta(b0, b1),
            },
            simplify_standalone: PhaseAlloc {
                time_ns: t_simplify,
                alloc: delta(s0, s1),
            },
            minimize_insert: PhaseAlloc {
                time_ns: t_insert,
                alloc: delta(m0, m1),
            },
        });
        Ok((n, rows, 10 * rows, n))
    } else {
        let mut map = std::collections::BTreeMap::new();
        let a0 = snapshot();
        let r = build_bess(&mut model, size, &prices.unwrap(), named, Some(&mut map));
        let a1 = snapshot();
        // Single snapshot pair spans the whole build; per-phase alloc split
        // for BESS is future work (sparse is the P0 focus).
        phases_alloc.insert("total".to_string(), delta(a0, a1));
        for (k, v) in map {
            phases_ns.insert(k, v);
        }
        r
    };
    let (variables, constraints, constraint_nnz, objective_nnz) = match counts {
        Ok(v) => v,
        Err(e) => {
            let rec = Record {
                schema_version: 1,
                run_id,
                timestamp_utc,
                benchmark_sha,
                roml_sha,
                implementation: "roml_core_ops_probe".to_string(),
                workload,
                size,
                objective_mode,
                anonymous,
                variables: 0,
                constraints: 0,
                constraint_nnz: 0,
                objective_nnz: 0,
                replicate,
                seed,
                status: "error".to_string(),
                error: Some(format!("construction failed: {e:?}")),
                phases_ns,
                phases_alloc,
                objective_split,
                rss_before_bytes: rss_before,
                rss_after_bytes: 0,
                peak_rss_bytes: 0,
            };
            println!("{}", serde_json::to_string(&rec).unwrap());
            std::process::exit(1);
        }
    };
    let (rss_after, peak) = rss_bytes();
    let rec = Record {
        schema_version: 1,
        run_id,
        timestamp_utc,
        benchmark_sha,
        roml_sha,
        implementation: "roml_core_ops_probe".to_string(),
        workload,
        size,
        objective_mode,
        anonymous,
        variables,
        constraints,
        constraint_nnz,
        objective_nnz,
        replicate,
        seed,
        status: "ok-counting".to_string(),
        error: None,
        phases_ns,
        phases_alloc,
        objective_split,
        rss_before_bytes: rss_before,
        rss_after_bytes: rss_after,
        peak_rss_bytes: peak,
    };
    println!("{}", serde_json::to_string(&rec).unwrap());
}
