//! Native ROML core benchmark runner.
//!
//! Builds the contract workloads directly against `roml` (no Python) and
//! emits exactly one JSON measurement record on stdout. Never solves.
//!
//! BESS prices are passed in from the orchestrator (`--prices-csv`) so the
//! Rust core consumes byte-identical canonical input to the Python adapters.

mod common;

use common::{build_bess, build_bess_bulk, build_sparse, build_sparse_bulk, rss_bytes, BESS_T};
use roml::prelude::*;
use serde::Serialize;
use std::time::Instant;

const ROML_SHA: &str = "9cea1642508693238562d1f1be2edb95bacaf488";
const SCHEMA_VERSION: u32 = 1;

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
    variables: usize,
    constraints: usize,
    constraint_nnz: usize,
    objective_nnz: usize,
    replicate: u32,
    seed: u64,
    variant: String,
    container_init_ns: u64,
    populate_ns: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    phases: Option<std::collections::BTreeMap<String, u64>>,
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
    implementation: String,
    anonymous: bool,
    phase_breakdown: bool,
    objective_mode: String,
}

fn usage() -> ! {
    eprintln!(
        "usage: roml-bench-core --workload <sparse_rows|bess_96> --size <N> \
         --seed <u64> --replicate <u32> --run-id <id> --benchmark-sha <sha> \
         --roml-sha <sha> --timestamp-utc <ts> [--cpu <n>] [--prices-csv <csv>] \
         [--implementation <roml_core_rust|roml_core_rust_anon|roml_core_bulk>] [--anonymous] \
         [--phase-breakdown] [--objective-mode <constant|parameterized>]"
    );
    std::process::exit(2);
}

fn get(args: &[String], flag: &str) -> Option<String> {
    args.windows(2).find(|w| w[0] == flag).map(|w| w[1].clone())
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
    let has = |flag: &str| raw.iter().any(|a| a == flag);
    let implementation =
        get(&raw, "--implementation").unwrap_or_else(|| "roml_core_rust".to_string());
    if implementation != "roml_core_rust"
        && implementation != "roml_core_rust_anon"
        && implementation != "roml_core_bulk"
    {
        usage();
    }
    let objective_mode = get(&raw, "--objective-mode").unwrap_or_else(|| "constant".to_string());
    if objective_mode != "constant" && objective_mode != "parameterized" {
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
        anonymous: has("--anonymous") || implementation == "roml_core_rust_anon",
        phase_breakdown: has("--phase-breakdown"),
        implementation,
        workload,
        objective_mode,
    }
}

fn emit(record: &Record) {
    println!(
        "{}",
        serde_json::to_string(record).unwrap_or_else(|_| "{}".to_string())
    );
}

fn fail(args: &Args, message: String, container_init_ns: u64) -> ! {
    let (rss_after, peak) = rss_bytes();
    emit(&Record {
        schema_version: SCHEMA_VERSION,
        run_id: args.run_id.clone(),
        timestamp_utc: args.timestamp_utc.clone(),
        benchmark_sha: args.benchmark_sha.clone(),
        roml_sha: args.roml_sha.clone(),
        implementation: args.implementation.clone(),
        workload: args.workload.clone(),
        size: args.size,
        objective_mode: args.objective_mode.clone(),
        variables: 0,
        constraints: 0,
        constraint_nnz: 0,
        objective_nnz: 0,
        replicate: args.replicate,
        seed: args.seed,
        variant: "canonical".to_string(),
        container_init_ns,
        populate_ns: 0,
        phases: None,
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
    if args.workload == "bess_96" && args.objective_mode == "parameterized" {
        eprintln!("bess_96 has no parameterized-objective mode in this build");
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
    let mut phase_map: Option<std::collections::BTreeMap<String, u64>> =
        args.phase_breakdown.then(std::collections::BTreeMap::new);
    let named = !args.anonymous;
    let parameterized = args.objective_mode == "parameterized";
    let bulk = args.implementation == "roml_core_bulk";
    if bulk && parameterized {
        fail(
            &args,
            "roml_core_bulk has no parameterized-objective mode in this build".to_string(),
            container_init_ns,
        );
    }
    if bulk && args.anonymous {
        fail(
            &args,
            "roml_core_bulk is always named (mirrors the Python bulk arm)".to_string(),
            container_init_ns,
        );
    }
    let counts = if args.workload == "sparse_rows" {
        if bulk {
            build_sparse_bulk(&mut model, args.size, named, phase_map.as_mut())
                .map(|(v, c, nnz)| (v, c, nnz, args.size))
        } else {
            build_sparse(
                &mut model,
                args.size,
                named,
                parameterized,
                phase_map.as_mut(),
            )
            .map(|(v, c, nnz)| (v, c, nnz, args.size))
        }
    } else {
        let csv = match &args.prices_csv {
            Some(v) => v.clone(),
            None => fail(
                &args,
                "bess_96 requires --prices-csv".to_string(),
                container_init_ns,
            ),
        };
        let prices: Vec<f64> = csv
            .split(',')
            .map(|s| {
                s.trim().parse().unwrap_or_else(|_| {
                    fail(
                        &args,
                        format!("bad prices-csv value: {s}"),
                        container_init_ns,
                    )
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
        if bulk {
            build_bess_bulk(&mut model, args.size, &prices, named, phase_map.as_mut())
        } else {
            build_bess(&mut model, args.size, &prices, named, phase_map.as_mut())
        }
    };
    let (variables, constraints, constraint_nnz, objective_nnz) = match counts {
        Ok(v) => v,
        Err(e) => fail(
            &args,
            format!("construction failed: {e:?}"),
            container_init_ns,
        ),
    };
    let populate_ns = pop_start.elapsed().as_nanos() as u64;
    let (rss_after, peak) = rss_bytes();

    emit(&Record {
        schema_version: SCHEMA_VERSION,
        run_id: args.run_id.clone(),
        timestamp_utc: args.timestamp_utc.clone(),
        benchmark_sha: args.benchmark_sha.clone(),
        roml_sha: args.roml_sha.clone(),
        implementation: args.implementation.clone(),
        workload: args.workload.clone(),
        size: args.size,
        objective_mode: args.objective_mode.clone(),
        variables,
        constraints,
        constraint_nnz,
        objective_nnz,
        replicate: args.replicate,
        seed: args.seed,
        variant: "canonical".to_string(),
        container_init_ns,
        populate_ns,
        phases: phase_map,
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
    use super::common;

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
        assert!((common::BESS_DT * common::BESS_ETA - 0.2375).abs() < 1e-12);
        assert!((common::BESS_DT / common::BESS_ETA - 0.2631578947368421).abs() < 1e-12);
    }

    fn count_sparse(n: usize) -> (usize, usize, usize, usize) {
        let rows = n / 10;
        (n, rows, 10 * rows, n)
    }

    fn count_bess(b: usize) -> (usize, usize, usize, usize) {
        (
            b * (3 * common::BESS_T + 1),
            b * (2 * common::BESS_T + 1),
            b * (1 + 6 * common::BESS_T),
            b * (2 * common::BESS_T),
        )
    }
}
