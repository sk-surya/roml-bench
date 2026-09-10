//! Kernel C prototype: raw packed arrays, no identity arena.
//!
//! Positions are identities (no generations, no stale detection): measures
//! how much the `IdArena` itself costs relative to kernel B, so the
//! retain-vs-redesign decision rests on measurement, not intuition.
//! Semantic gaps vs B are documented, not hidden.

use crate::kernel_a::store::CoefficientTarget;
use roml::id::{CoeffId, Generation, VarId};
use roml::value_expr::ValueExpr;

/// Raw packed constant store: one sorted run per target plus a dead bitset.
/// `u32` positions serve as identities (no generations).
#[derive(Clone, Debug, Default)]
pub struct RawPacked {
    vars: Vec<VarId>,
    values: Vec<f64>,
    exprs: Vec<Option<ValueExpr>>,
    dead: Vec<u64>,
    start: u32,
    len: u32,
}

fn bit_get(bits: &[u64], i: u32) -> bool {
    bits.get(i as usize / 64)
        .is_some_and(|w| w & (1u64 << (i % 64)) != 0)
}

fn bit_set(bits: &mut Vec<u64>, i: u32) {
    let need = i as usize / 64 + 1;
    if bits.len() < need {
        bits.resize(need, 0);
    }
    bits[i as usize / 64] |= 1u64 << (i % 64);
}

impl RawPacked {
    pub fn new() -> Self {
        Self::default()
    }

    /// Bulk-insert one constant block. Same caller contract as kernel B
    /// (unique, fresh, finite, `vars` sorted ascending).
    pub fn build_constant_block(
        &mut self,
        _target: CoefficientTarget,
        vars: &[VarId],
        values: &[f64],
    ) -> Vec<CoeffId> {
        debug_assert_eq!(vars.len(), values.len());
        debug_assert!(vars.windows(2).all(|w| w[0] < w[1]));
        let n = vars.len();
        self.vars.reserve(n);
        self.values.reserve(n);
        self.exprs.reserve(n);
        self.start = self.vars.len() as u32;
        let mut ids = Vec::with_capacity(n);
        for (k, (var, value)) in vars.iter().zip(values.iter()).enumerate() {
            self.vars.push(*var);
            self.values.push(*value);
            self.exprs.push(None);
            // Positional identity WITHOUT generation semantics (prototype gap).
            ids.push(CoeffId::new(self.start + k as u32, Generation::new()));
        }
        self.len = n as u32;
        ids
    }

    fn position(&self, var: VarId) -> Option<u32> {
        let base = &self.vars[self.start as usize..(self.start + self.len) as usize];
        let pos = base.binary_search(&var).ok()?;
        let idx = self.start + pos as u32;
        if bit_get(&self.dead, idx) {
            return None;
        }
        Some(idx)
    }

    pub fn for_cell(&self, _target: CoefficientTarget, var: VarId) -> Option<(CoeffId, f64)> {
        let idx = self.position(var)?;
        // `values` always carries the current evaluated value (set at update
        // time); `exprs` retains symbolic structure only.
        Some((
            CoeffId::new(idx, Generation::new()),
            self.values[idx as usize],
        ))
    }

    pub fn iter_live(&self) -> Vec<(CoeffId, VarId, f64)> {
        let mut out = Vec::new();
        for k in 0..self.len {
            let idx = self.start + k;
            if bit_get(&self.dead, idx) {
                continue;
            }
            out.push((
                CoeffId::new(idx, Generation::new()),
                self.vars[idx as usize],
                self.values[idx as usize],
            ));
        }
        out
    }

    pub fn remove(&mut self, _target: CoefficientTarget, var: VarId) -> bool {
        match self.position(var) {
            Some(idx) => {
                bit_set(&mut self.dead, idx);
                true
            }
            None => false,
        }
    }

    pub fn update(&mut self, _target: CoefficientTarget, var: VarId, expr: ValueExpr, value: f64) {
        if let Some(idx) = self.position(var) {
            // No generation bump: known prototype gap vs kernel B.
            self.exprs[idx as usize] = Some(expr);
            self.values[idx as usize] = value;
        }
    }
}
