//! Secondary observability probe for the P0..P1C2 forensic pass.
//!
//! Builds the contract workloads natively (same `common` builders as the
//! timing runner, named entities to mirror the Python spellings) and
//! separately records what `populate_ms` does NOT include: commit,
//! snapshot, delta op count, coefficient count, peak RSS. Timings here are
//! structural diagnostics, not headline evidence; the authoritative
//! populate numbers come from the suite runs.

#[path = "../common.rs"]
mod common;

use common::{build_bess, build_sparse, rss_bytes, BESS_T};
use roml::prelude::*;
use roml::sync::AdapterCursor;
use serde::Serialize;
use std::collections::BTreeMap;
use std::time::Instant;

const ROML_SHA: &str = "d6afabd2988761fe9d5dd08597491a6f3fb73779";

#[derive(Serialize)]
struct ProbeRecord {
    roml_sha: String,
    workload: String,
    size: usize,
    replicate: u32,
    phases_ms: BTreeMap<String, f64>,
    commit_ms: f64,
    snapshot_ms: f64,
    delta_ops: usize,
    coefficients: usize,
    variables: usize,
    constraints: usize,
    peak_rss_bytes: u64,
}

fn probe_sparse(n: usize, replicate: u32) -> ProbeRecord {
    let mut model = Model::new();
    let mut phases = BTreeMap::new();
    build_sparse(&mut model, n, true, false, Some(&mut phases)).unwrap();
    finish("sparse_rows", n, replicate, model, phases)
}

fn probe_bess(b: usize, replicate: u32) -> ProbeRecord {
    // Canonical BESS-96 prices: same deterministic generator as the suite
    // (seed 20260908, uniform 20..80 tiled over blocks).
    let mut rng = SimpleRng(20260908);
    let prices: Vec<f64> = (0..BESS_T).map(|_| 20.0 + 60.0 * rng.next()).collect();
    let mut model = Model::new();
    let mut phases = BTreeMap::new();
    build_bess(&mut model, b, &prices, true, Some(&mut phases)).unwrap();
    finish("bess_96", b, replicate, model, phases)
}

fn finish(
    workload: &str,
    size: usize,
    replicate: u32,
    mut model: Model,
    phases: BTreeMap<String, u64>,
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
        workload: workload.to_string(),
        size,
        replicate,
        phases_ms,
        commit_ms,
        snapshot_ms,
        delta_ops,
        coefficients,
        variables,
        constraints,
        peak_rss_bytes: peak,
    }
}

/// SplitMix64-style deterministic generator (no extra dependencies).
struct SimpleRng(u64);

impl SimpleRng {
    fn next(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^= z >> 31;
        (z >> 11) as f64 / (1u64 << 53) as f64
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
    let _ = get("--cpu");
    // CPU pinning is the caller's job (taskset); this probe never pins
    // itself so it cannot disturb a pinned suite run.
    let record = match workload.as_str() {
        "sparse_rows" => probe_sparse(size, replicate),
        "bess_96" => probe_bess(size, replicate),
        _ => {
            eprintln!("unknown workload: {workload}");
            std::process::exit(2);
        }
    };
    println!("{}", serde_json::to_string(&record).unwrap());
}
