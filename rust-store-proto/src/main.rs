//! P1.5A store microkernels: A (current P0 topology, verbatim copy),
//! B (packed base + overlay + identity arena), C (raw packed, no arena).
//!
//! Release-only measurement harness. Each kernel runs in its own process
//! (`--kernel a|b|c`) so VmHWM attributes cleanly. Deterministic xorshift
//! workload: 1M constant objective cells, 100k random lookups, full
//! iteration with checksum, 10k removes + 10k updates (half parameterized).
//! Sampled read-back assertions keep every kernel honest; full equivalence
//! fuzzing belongs to P1.5B, not this gate.

mod kernel_a;
mod kernel_b;
mod kernel_c;

use std::time::Instant;

use kernel_a::store::CoefficientTarget;
use roml::id::{Generation, ObjId, ParamId, VarId};
use roml::value_expr::ValueExpr;

fn rss_hwm() -> u64 {
    let mut hwm = 0u64;
    if let Ok(text) = std::fs::read_to_string("/proc/self/status") {
        for line in text.lines() {
            if let Some(rest) = line.strip_prefix("VmHWM:") {
                hwm = rest
                    .split_whitespace()
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(0)
                    * 1024;
            }
        }
    }
    hwm
}

struct XorShift(u64);

impl XorShift {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

fn usage() -> ! {
    eprintln!("usage: store-proto --kernel <a|b|c> --n <cells>");
    std::process::exit(2);
}

fn get(args: &[String], flag: &str) -> Option<String> {
    args.windows(2).find(|w| w[0] == flag).map(|w| w[1].clone())
}

// --- Per-kernel drivers share one workload shape; each returns phase times,
// --- checksums, and counts. Trait-free (monomorphic, zero abstraction cost).

struct Outcome {
    build_ms: f64,
    lookup_ms: f64,
    iterate_ms: f64,
    mutate_ms: f64,
    checksum: f64,
    lookups_found: usize,
    live_after: usize,
    peak_rss_mb: f64,
}

fn drive_a(n: usize, lookups: &[u64], removes: &[u64], updates: &[u64], p: ParamId) -> Outcome {
    use kernel_a::store::CoefficientIndex;
    let obj = ObjId::new(0, Generation::new());
    let target = CoefficientTarget::Objective(obj);
    let vars: Vec<VarId> = (0..n as u32)
        .map(|i| VarId::new(i, Generation::new()))
        .collect();
    let vals: Vec<f64> = (0..n).map(|i| (i % 97) as f64 + 0.5).collect();
    let cells: Vec<(VarId, f64)> = vars.iter().copied().zip(vals.iter().copied()).collect();

    let hwm0 = rss_hwm();
    let t0 = Instant::now();
    let mut store = CoefficientIndex::new();
    store.add_constant_unique_block(target, &cells);
    let build_ms = t0.elapsed().as_secs_f64() * 1e3;

    let t1 = Instant::now();
    let mut found = 0usize;
    let mut sum = 0.0;
    for &i in lookups {
        if let Some(id) = store.for_cell(target, vars[i as usize]) {
            found += 1;
            sum += store.get(id).map(|d| d.cached_value).unwrap_or(0.0);
        }
    }
    let lookup_ms = t1.elapsed().as_secs_f64() * 1e3;

    let t2 = Instant::now();
    let mut total = 0.0;
    let mut count = 0usize;
    for id in store.for_objective(obj) {
        if let Some(d) = store.get(id) {
            total += d.cached_value;
            count += 1;
        }
    }
    let iterate_ms = t2.elapsed().as_secs_f64() * 1e3;

    let t3 = Instant::now();
    for &i in removes {
        if let Some(id) = store.for_cell(target, vars[i as usize]) {
            store.remove(id);
        }
    }
    for (k, &i) in updates.iter().enumerate() {
        if let Some(id) = store.for_cell(target, vars[i as usize]) {
            if k % 2 == 0 {
                let v = (i % 97) as f64 * 2.0 + 1.0;
                store.set_expr(id, ValueExpr::constant(v), v);
            } else {
                let e = ValueExpr::param(p) + 1.0;
                store.set_expr(id, e, 3.0);
            }
        }
    }
    let mutate_ms = t3.elapsed().as_secs_f64() * 1e3;
    let live_after = store.len();
    let peak = rss_hwm().max(hwm0) as f64 / 2f64.powi(20);
    // Honesty probes (sampled).
    assert_eq!(found, lookups.len());
    assert_eq!(count, n);
    let _ = total;
    Outcome {
        build_ms,
        lookup_ms,
        iterate_ms,
        mutate_ms,
        checksum: sum + total,
        lookups_found: found,
        live_after,
        peak_rss_mb: peak,
    }
}

fn drive_b(n: usize, lookups: &[u64], removes: &[u64], updates: &[u64], p: ParamId) -> Outcome {
    use kernel_b::{CellLocation, PackedStore};
    let obj = ObjId::new(0, Generation::new());
    let target = CoefficientTarget::Objective(obj);
    let vars: Vec<VarId> = (0..n as u32)
        .map(|i| VarId::new(i, Generation::new()))
        .collect();
    let vals: Vec<f64> = (0..n).map(|i| (i % 97) as f64 + 0.5).collect();

    let hwm0 = rss_hwm();
    let t0 = Instant::now();
    let mut store = PackedStore::new();
    let ids = store.build_constant_block(target, &vars, &vals);
    assert_eq!(ids.len(), n);
    let build_ms = t0.elapsed().as_secs_f64() * 1e3;

    let t1 = Instant::now();
    let mut found = 0usize;
    let mut sum = 0.0;
    for &i in lookups {
        if let Some((_, v)) = store.for_cell(target, vars[i as usize]) {
            found += 1;
            sum += v;
        }
    }
    let lookup_ms = t1.elapsed().as_secs_f64() * 1e3;

    let t2 = Instant::now();
    let walked = store.iter_target(target);
    let total: f64 = walked.iter().map(|(_, _, v)| v).sum();
    let count = walked.len();
    let iterate_ms = t2.elapsed().as_secs_f64() * 1e3;

    // Identity-location oracle before mutation: base cell lives packed.
    let (pre_id, _) = store.for_cell(target, vars[updates[0] as usize]).unwrap();
    assert!(matches!(
        store.locate(pre_id),
        Some(CellLocation::Packed(_))
    ));
    let t3 = Instant::now();
    for &i in removes {
        assert!(store.remove(target, vars[i as usize]));
    }
    for (k, &i) in updates.iter().enumerate() {
        if k % 2 == 0 {
            let v = (i % 97) as f64 * 2.0 + 1.0;
            store.update(target, vars[i as usize], ValueExpr::constant(v), v);
        } else {
            let e = ValueExpr::param(p) + 1.0;
            store.update(target, vars[i as usize], e, 3.0);
        }
    }
    let mutate_ms = t3.elapsed().as_secs_f64() * 1e3;
    let live_after = store.iter_target(target).len();
    // Exercise the lazy global variable index at scale (not a gated op):
    // first call builds it, overlay deltas resolve through it. Expect
    // exactly one hit per sampled var except removed ones (zero hits);
    // shadowed vars resolve once via the overlay delta.
    let removed_set: std::collections::HashSet<u64> = removes.iter().copied().collect();
    let mut var_hits = 0usize;
    let mut var_sum = 0.0;
    let mut expected_hits = 0usize;
    for &i in lookups.iter().step_by(100) {
        if !removed_set.contains(&i) {
            expected_hits += 1;
        }
        for (_, _, v) in store.for_var(vars[i as usize]) {
            var_hits += 1;
            var_sum += v;
        }
    }
    let peak = rss_hwm().max(hwm0) as f64 / 2f64.powi(20);
    assert_eq!(found, lookups.len());
    assert_eq!(count, n);
    assert_eq!(var_hits, expected_hits);
    assert!(store.var_index_built());
    let _ = var_sum;
    // Spot-check mutation semantics: identity preserved on update,
    // removal visible, parameterized shadow readable.
    let (post_id, v0) = store.for_cell(target, vars[updates[0] as usize]).unwrap();
    assert!((v0 - ((updates[0] % 97) as f64 * 2.0 + 1.0)).abs() < 1e-9);
    // Same logical identity, relocated to the overlay; base never mutated.
    assert_eq!(post_id, pre_id);
    assert!(matches!(
        store.locate(post_id),
        Some(CellLocation::Overlay(_))
    ));
    assert_eq!(store.for_cell(target, vars[removes[0] as usize]), None);
    assert_eq!(live_after, n - removes.len());
    Outcome {
        build_ms,
        lookup_ms,
        iterate_ms,
        mutate_ms,
        checksum: sum + total,
        lookups_found: found,
        live_after,
        peak_rss_mb: peak,
    }
}

fn drive_c(n: usize, lookups: &[u64], removes: &[u64], updates: &[u64], p: ParamId) -> Outcome {
    use kernel_c::RawPacked;
    let obj = ObjId::new(0, Generation::new());
    let target = CoefficientTarget::Objective(obj);
    let vars: Vec<VarId> = (0..n as u32)
        .map(|i| VarId::new(i, Generation::new()))
        .collect();
    let vals: Vec<f64> = (0..n).map(|i| (i % 97) as f64 + 0.5).collect();

    let hwm0 = rss_hwm();
    let t0 = Instant::now();
    let mut store = RawPacked::new();
    let ids = store.build_constant_block(target, &vars, &vals);
    assert_eq!(ids.len(), n);
    let build_ms = t0.elapsed().as_secs_f64() * 1e3;

    let t1 = Instant::now();
    let mut found = 0usize;
    let mut sum = 0.0;
    for &i in lookups {
        if let Some((_, v)) = store.for_cell(target, vars[i as usize]) {
            found += 1;
            sum += v;
        }
    }
    let lookup_ms = t1.elapsed().as_secs_f64() * 1e3;

    let t2 = Instant::now();
    let walked = store.iter_live();
    let total: f64 = walked.iter().map(|(_, _, v)| v).sum();
    let count = walked.len();
    let iterate_ms = t2.elapsed().as_secs_f64() * 1e3;

    let t3 = Instant::now();
    for &i in removes {
        assert!(store.remove(target, vars[i as usize]));
    }
    for (k, &i) in updates.iter().enumerate() {
        if k % 2 == 0 {
            let v = (i % 97) as f64 * 2.0 + 1.0;
            store.update(target, vars[i as usize], ValueExpr::constant(v), v);
        } else {
            let e = ValueExpr::param(p) + 1.0;
            store.update(target, vars[i as usize], e, 3.0);
        }
    }
    let mutate_ms = t3.elapsed().as_secs_f64() * 1e3;
    let live_after = store.iter_live().len();
    let peak = rss_hwm().max(hwm0) as f64 / 2f64.powi(20);
    assert_eq!(found, lookups.len());
    assert_eq!(count, n);
    assert_eq!(live_after, n - removes.len());
    let _ = p;
    Outcome {
        build_ms,
        lookup_ms,
        iterate_ms,
        mutate_ms,
        checksum: sum + total,
        lookups_found: found,
        live_after,
        peak_rss_mb: peak,
    }
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let req = |flag: &str| match get(&raw, flag) {
        Some(v) => v,
        None => usage(),
    };
    let kernel = req("--kernel");
    if kernel != "a" && kernel != "b" && kernel != "c" {
        usage();
    }
    let n: usize = req("--n").parse().unwrap_or_else(|_| usage());

    // Shared deterministic workload (lookups first so the pick closure's
    // mutable borrow starts after direct rng use ends).
    let mut rng = XorShift(0x9E3779B97F4A7C15);
    let mut lookups = Vec::with_capacity(100_000);
    for _ in 0..100_000 {
        lookups.push(rng.below(n as u64));
    }
    let mut taken = vec![false; n];
    let mut pick = |count: usize| -> Vec<u64> {
        let mut out = Vec::with_capacity(count);
        while out.len() < count {
            let i = rng.below(n as u64);
            if !taken[i as usize] {
                taken[i as usize] = true;
                out.push(i);
            }
        }
        out
    };
    let removes = pick(10_000);
    let updates = pick(10_000);
    let p = ParamId::new(0, Generation::new());

    let outcome = match kernel.as_str() {
        "a" => drive_a(n, &lookups, &removes, &updates, p),
        "b" => drive_b(n, &lookups, &removes, &updates, p),
        _ => drive_c(n, &lookups, &removes, &updates, p),
    };
    println!(
        "{{\"kernel\":\"{kernel}\",\"n\":{n},\"build_ms\":{:.1},\"lookup100k_ms\":{:.1},\
         \"iterate_ms\":{:.1},\"mutate20k_ms\":{:.1},\"checksum\":{:.1},\
         \"lookups_found\":{},\"live_after\":{},\"peak_rss_mb\":{:.0}}}",
        outcome.build_ms,
        outcome.lookup_ms,
        outcome.iterate_ms,
        outcome.mutate_ms,
        outcome.checksum,
        outcome.lookups_found,
        outcome.live_after,
        outcome.peak_rss_mb,
    );
}
