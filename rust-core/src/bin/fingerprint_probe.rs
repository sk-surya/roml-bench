//! Canonical-equivalence probe: build the benchmark BESS through the current
//! Rust L1 array API and print its normalized fingerprints, so the arm can be
//! checked against an equivalent Python construction before timing.
#![allow(dead_code)]
#[path = "../common.rs"]
mod common;

use roml::prelude::*;

fn main() {
    let b: usize = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(1);
    let prices: Vec<f64> = match std::env::args().nth(2) {
        Some(csv) => csv.split(',').map(|s| s.trim().parse().unwrap()).collect(),
        None => vec![50.0; common::BESS_T],
    };
    let mut model = Model::named("bess_96");
    common::build_bess_l1(&mut model, b, &prices, true, None).expect("bess l1");
    model.commit().expect("commit");
    println!(
        "BESS_L1 b={b} ordinal={} journal={}",
        model.normalized_ordinal_fingerprint().expect("ordinal"),
        model.normalized_journal_fingerprint().expect("journal"),
    );
}
