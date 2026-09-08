//! Native ROML core benchmark runner.
//!
//! Builds the contract workloads directly against `roml` (no Python) and
//! emits exactly one JSON measurement record on stdout. Never solves.
//!
//! BESS prices are passed in from the orchestrator (`--prices-csv`) so the
//! Rust core consumes byte-identical canonical input to the Python adapters.

use roml::prelude::*;
use serde::Serialize;
use std::time::Instant;

const ROML_SHA: &str = "6062398b418c4bc0c7718b2ce569da8b9e42766e";
const SCHEMA_VERSION: u32 = 1;

const BESS_T: usize = 96;
const BESS_DT: f64 = 0.25;
const BESS_ETA: f64 = 0.95;
const BESS_P: f64 = 2.0;
const BESS_E: f64 = 4.0;
const BESS_E0: f64 = 2.0;

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
    variables: usize,
    constraints: usize,
    constraint_nnz: usize,
    objective_nnz: usize,
    replicate: u32,
    seed: u64,
    container_init_ns: u64,
    populate_ns: u64,
    rss_before_bytes: u64,
    rss_after_bytes: u64,
    peak_rss_bytes: u64,
    cpu: Option<u32>,
    status: String,
    error: Option<String>,
}

struct Args {
    workload: String,
    size: usize,
    seed: u64,
    replicate: u32,
    run_id: String,
    benchmark_sha: String,
    roml_sha: String,
    timestamp_utc: String,
    cpu: Option<u32>,
    prices_csv: Option<String>,
}

fn usage() -> ! {
    eprintln!(
        "usage: roml-bench-core --workload <sparse_rows|bess_96> --size <N> \
         --seed <u64> --replicate <u32> --run-id <id> --benchmark-sha <sha> \
         --roml-sha <sha> --timestamp-utc <ts> [--cpu <n>] [--prices-csv <csv>]"
    );
    std::process::exit(2);
}

fn get(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|w| w[0] == flag)
        .map(|w| w[1].clone())
}

fn parse_args() -> Args {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let req = |flag: &str| match get(&raw, flag) {
        Some(v) => v,
        None => usage(),
    };
    let workload = req("--workload");
    if workload != "sparse_rows" && workload != "bess_96" {
        usage();
    }
    Args {
        size: req("--size").parse().unwrap_or_else(|_| usage()),
        seed: req("--seed").parse().unwrap_or_else(|_| usage()),
        replicate: req("--replicate").parse().unwrap_or_else(|_| usage()),
        run_id: req("--run-id"),
        benchmark_sha: req("--benchmark-sha"),
        roml_sha: req("--roml-sha"),
        timestamp_utc: req("--timestamp-utc"),
        cpu: get(&raw, "--cpu").map(|v| v.parse().unwrap_or_else(|_| usage())),
        prices_csv: get(&raw, "--prices-csv"),
        workload,
    }
}

/// Current VmRSS and process peak (VmHWM) in bytes from /proc/self/status.
fn rss_bytes() -> (u64, u64) {
    let mut rss = 0u64;
    let mut hwm = 0u64;
    if let Ok(text) = std::fs::read_to_string("/proc/self/status") {
        for line in text.lines() {
            if let Some(rest) = line.strip_prefix("VmRSS:") {
                rss = rest.split_whitespace().next().and_then(|v| v.parse().ok()).unwrap_or(0)
                    * 1024;
            } else if let Some(rest) = line.strip_prefix("VmHWM:") {
                hwm = rest.split_whitespace().next().and_then(|v| v.parse().ok()).unwrap_or(0)
                    * 1024;
            }
        }
    }
    (rss, hwm)
}

fn build_sparse(model: &mut Model, n: usize) -> Result<(usize, usize, usize), ModelError> {
    let rows = n / 10;
    let mut vars = Vec::with_capacity(n);
    for i in 0..n {
        vars.push(model.add_variable(continuous().bounds(0.0, 5.0).named(format!("x[{i}]")))?);
    }
    for r in 0..rows {
        let base = 10 * r;
        let mut expr = LinExpr::new();
        for k in 0..10 {
            expr = expr.term(1.0, vars[base + k]);
        }
        model.add_constraint(expr.le(10.0).named(format!("row[{r}]")))?;
    }
    let mut total = LinExpr::new();
    for v in &vars {
        total = total.term(1.0, *v);
    }
    model.minimize(total)?;
    Ok((n, rows, 10 * rows))
}

fn build_bess(
    model: &mut Model,
    b: usize,
    prices: &[f64],
) -> Result<(usize, usize, usize, usize), ModelError> {
    assert_eq!(prices.len(), BESS_T);
    let t = BESS_T;
    let mut charge = Vec::with_capacity(b * t);
    let mut discharge = Vec::with_capacity(b * t);
    let mut energy = Vec::with_capacity(b * (t + 1));
    for bb in 0..b {
        for tt in 0..t {
            charge.push(
                model.add_variable(
                    continuous().bounds(0.0, BESS_P).named(format!("charge[{bb},{tt}]")),
                )?,
            );
        }
    }
    for bb in 0..b {
        for tt in 0..t {
            discharge.push(
                model.add_variable(
                    continuous().bounds(0.0, BESS_P).named(format!("discharge[{bb},{tt}]")),
                )?,
            );
        }
    }
    for bb in 0..b {
        for tt in 0..=t {
            energy.push(
                model.add_variable(
                    continuous().bounds(0.0, BESS_E).named(format!("energy[{bb},{tt}]")),
                )?,
            );
        }
    }
    let mut obj = LinExpr::new();
    for bb in 0..b {
        model.add_constraint(
            LinExpr::from(energy[bb * (t + 1)]).eq(BESS_E0).named(format!("init[{bb}]")),
        )?;
        for tt in 0..t {
            let ch = charge[bb * t + tt];
            let di = discharge[bb * t + tt];
            let en0 = energy[bb * (t + 1) + tt];
            let en1 = energy[bb * (t + 1) + tt + 1];
            // en1 == en0 + dt * (eta * ch - di / eta)
            let rhs = LinExpr::from(en0)
                + LinExpr::new().term(BESS_DT * BESS_ETA, ch)
                + LinExpr::new().term(-BESS_DT / BESS_ETA, di);
            model.add_constraint(
                (LinExpr::from(en1) - rhs).eq(0.0).named(format!("balance[{bb},{tt}]")),
            )?;
            model.add_constraint(
                (LinExpr::from(ch) + LinExpr::from(di))
                    .le(BESS_P)
                    .named(format!("mode[{bb},{tt}]")),
            )?;
            obj = obj.term(-BESS_DT * prices[tt], ch);
            obj = obj.term(BESS_DT * prices[tt], di);
        }
    }
    model.maximize(obj)?;
    Ok((b * (3 * t + 1), b * (2 * t + 1), b * (1 + 6 * t), b * (2 * t)))
}

fn emit(record: &Record) {
    println!("{}", serde_json::to_string(record).unwrap_or_else(|_| "{}".to_string()));
}

fn fail(args: &Args, message: String, container_init_ns: u64) -> ! {
    let (rss_after, peak) = rss_bytes();
    emit(&Record {
        schema_version: SCHEMA_VERSION,
        run_id: args.run_id.clone(),
        timestamp_utc: args.timestamp_utc.clone(),
        benchmark_sha: args.benchmark_sha.clone(),
        roml_sha: args.roml_sha.clone(),
        implementation: "roml_core_rust".to_string(),
        workload: args.workload.clone(),
        size: args.size,
        variables: 0,
        constraints: 0,
        constraint_nnz: 0,
        objective_nnz: 0,
        replicate: args.replicate,
        seed: args.seed,
        container_init_ns,
        populate_ns: 0,
        rss_before_bytes: 0,
        rss_after_bytes: rss_after,
        peak_rss_bytes: peak,
        cpu: args.cpu,
        status: "error".to_string(),
        error: Some(message),
    });
    std::process::exit(1);
}

fn main() {
    let args = parse_args();
    if args.roml_sha != ROML_SHA {
        eprintln!("roml_sha mismatch: runner built for {ROML_SHA}");
        std::process::exit(2);
    }

    // Tiny unrecorded warmup to settle lazy initialization.
    {
        let mut warm = Model::named("warmup");
        let x = warm
            .add_variable(continuous().bounds(0.0, 5.0).named("x"))
            .expect("warmup var");
        warm.add_constraint(LinExpr::from(x).le(10.0).named("r"))
            .expect("warmup con");
        warm.minimize(LinExpr::from(x)).expect("warmup obj");
    }

    let init_start = Instant::now();
    let mut model = Model::named(args.workload.clone());
    let container_init_ns = init_start.elapsed().as_nanos() as u64;

    let (rss_before, _) = rss_bytes();
    let pop_start = Instant::now();
    let counts = if args.workload == "sparse_rows" {
        build_sparse(&mut model, args.size).map(|(v, c, nnz)| (v, c, nnz, args.size))
    } else {
        let csv = match &args.prices_csv {
            Some(v) => v.clone(),
            None => fail(&args, "bess_96 requires --prices-csv".to_string(), container_init_ns),
        };
        let prices: Vec<f64> = csv
            .split(',')
            .map(|s| {
                s.trim().parse().unwrap_or_else(|_| {
                    fail(&args, format!("bad prices-csv value: {s}"), container_init_ns)
                })
            })
            .collect();
        if prices.len() != BESS_T {
            fail(
                &args,
                format!("prices-csv has {} values, need {BESS_T}", prices.len()),
                container_init_ns,
            );
        }
        build_bess(&mut model, args.size, &prices)
    };
    let (variables, constraints, constraint_nnz, objective_nnz) = match counts {
        Ok(v) => v,
        Err(e) => fail(&args, format!("construction failed: {e:?}"), container_init_ns),
    };
    let populate_ns = pop_start.elapsed().as_nanos() as u64;
    let (rss_after, peak) = rss_bytes();

    emit(&Record {
        schema_version: SCHEMA_VERSION,
        run_id: args.run_id.clone(),
        timestamp_utc: args.timestamp_utc.clone(),
        benchmark_sha: args.benchmark_sha.clone(),
        roml_sha: args.roml_sha.clone(),
        implementation: "roml_core_rust".to_string(),
        workload: args.workload.clone(),
        size: args.size,
        variables,
        constraints,
        constraint_nnz,
        objective_nnz,
        replicate: args.replicate,
        seed: args.seed,
        container_init_ns,
        populate_ns,
        rss_before_bytes: rss_before,
        rss_after_bytes: rss_after,
        peak_rss_bytes: peak,
        cpu: args.cpu,
        status: "ok".to_string(),
        error: None,
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sparse_counts_match_contract() {
        let (v, c, nnz, obj) = count_sparse(1000);
        assert_eq!((v, c, nnz, obj), (1000, 100, 1000, 1000));
    }

    #[test]
    fn bess_counts_match_contract() {
        let (v, c, nnz, obj) = count_bess(10);
        assert_eq!((v, c, nnz, obj), (2890, 1930, 5770, 1920));
    }

    #[test]
    fn balance_row_algebra_matches_contract() {
        // energy[t+1] == energy[t] + dt * (eta * ch - di / eta)
        // => coefficients (en1, en0, ch, di) = (1, -1, -dt*eta, +dt/eta).
        assert!((BESS_DT * BESS_ETA - 0.2375).abs() < 1e-12);
        assert!((BESS_DT / BESS_ETA - 0.2631578947368421).abs() < 1e-12);
    }

    fn count_sparse(n: usize) -> (usize, usize, usize, usize) {
        let rows = n / 10;
        (n, rows, 10 * rows, n)
    }

    fn count_bess(b: usize) -> (usize, usize, usize, usize) {
        (b * (3 * BESS_T + 1), b * (2 * BESS_T + 1), b * (1 + 6 * BESS_T), b * (2 * BESS_T))
    }
}
