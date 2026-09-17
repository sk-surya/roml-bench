//! Item 8 lowering evidence: build the parameterized construction fixture
//! through the raw L2 parameter-block path and the current Rust L1 array path,
//! and print the packed-dependency lowering counters + canonical fingerprints
//! so roml-bench has its own evidence (MIR numbers are a sanity check only).
#[path = "../common.rs"]
mod common;

use roml::prelude::*;

fn main() {
    let b: usize = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(300);
    let prices: Vec<f64> = match std::env::args().nth(2) {
        Some(csv) => csv.split(',').map(|s| s.trim().parse().unwrap()).collect(),
        None => vec![50.0; common::BESS_T],
    };
    for arm in ["bulk", "l1"] {
        let mut model = Model::named("param_bess");
        if arm == "bulk" {
            common::build_param_bess_bulk(&mut model, b, &prices, None).expect("bulk");
        } else {
            common::build_param_bess_l1(&mut model, b, &prices, None).expect("l1");
        }
        model.commit().expect("commit");
        let l = model.lowering_stats();
        println!(
            "arm={arm} b={b} general_affine={} param_dep_blocks={} param_positions_cells={} \
             ordinal={} journal={}",
            l.general_affine,
            l.param_dep_blocks,
            l.param_positions_cells,
            model.normalized_ordinal_fingerprint().expect("ordinal"),
            model.normalized_journal_fingerprint().expect("journal"),
        );
    }
}
