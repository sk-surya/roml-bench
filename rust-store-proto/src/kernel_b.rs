//! Kernel B prototype: packed constant base + sparse mutation overlay.
//!
//! P1.5A design: the packed base and overlay TOGETHER are the canonical
//! coefficient authority (the overlay is not a cache). Identity stays in a
//! lightweight [`CellLocation`] arena so `CoeffId` + generation semantics
//! (stale detection, update identity, removal) are preserved exactly.
//! The packed topology is never mutated after construction: later writes
//! shadow base cells into the overlay under the same logical `CoeffId`.
//! The global variable index is LAZY (built on first `for_var` use).

use std::collections::HashMap;

use crate::kernel_a::store::CoefficientTarget;
use roml::id::{CoeffId, Generation, ParamId, VarId};
use roml::value_expr::ValueExpr;

use crate::kernel_a::arena::IdArena;

/// Where a live logical cell's data resides.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CellLocation {
    Packed(u32),
    Overlay(u32),
}

/// One contiguous run of packed cells for a single target.
#[derive(Clone, Debug)]
struct TargetSlice {
    target: CoefficientTarget,
    start: u32,
    len: u32,
}

/// A sparse-overlay cell: full general representation (constant or
/// parameterized), tombstone support, and its stable logical identity.
#[derive(Clone, Debug)]
struct OverlayCell {
    key: (CoefficientTarget, VarId),
    coeff_id: CoeffId,
    value_expr: ValueExpr,
    value: f64,
    tombstone: bool,
}

/// Lazily built global variable index over the packed base.
#[derive(Clone, Debug, Default)]
struct PackedVarIndex {
    /// `var_offsets[i]..var_offsets[i+1]` spans `entries` for one var.
    /// `vars_sorted[k]` owns offset `k`.
    vars_sorted: Vec<VarId>,
    var_offsets: Vec<u32>,
    entries: Vec<u32>,
}

impl PackedVarIndex {
    fn build(base_vars: &[VarId]) -> Self {
        // Base rows are canonicalized by VarId per target slice, but the
        // global order across slices is arbitrary: collect + sort once.
        let mut order: Vec<u32> = (0..base_vars.len() as u32).collect();
        order.sort_by_key(|&i| base_vars[i as usize]);
        let mut vars_sorted = Vec::new();
        let mut var_offsets = Vec::with_capacity(order.len() + 1);
        let mut entries = Vec::with_capacity(order.len());
        let mut i = 0;
        while i < order.len() {
            let v = base_vars[order[i] as usize];
            vars_sorted.push(v);
            var_offsets.push(entries.len() as u32);
            while i < order.len() && base_vars[order[i] as usize] == v {
                entries.push(order[i]);
                i += 1;
            }
        }
        var_offsets.push(entries.len() as u32);
        Self {
            vars_sorted,
            var_offsets,
            entries,
        }
    }

    fn positions(&self, var: VarId) -> &[u32] {
        match self.vars_sorted.binary_search(&var) {
            Ok(k) => {
                let s = self.var_offsets[k] as usize;
                let e = self.var_offsets[k + 1] as usize;
                &self.entries[s..e]
            }
            Err(_) => &[],
        }
    }
}

/// Prototype packed-base + overlay coefficient store.
#[derive(Clone, Debug, Default)]
pub struct PackedStore {
    identity: IdArena<CellLocation>,
    // Packed base (append-only after construction).
    base_vars: Vec<VarId>,
    base_values: Vec<f64>,
    base_ids: Vec<CoeffId>,
    target_slices: Vec<TargetSlice>,
    target_directory: HashMap<CoefficientTarget, usize>,
    shadowed: Vec<u64>,
    dead: Vec<u64>,
    // Sparse overlay (all post-build mutation lives here).
    overlay: Vec<OverlayCell>,
    overlay_by_cell: HashMap<(CoefficientTarget, VarId), u32>,
    overlay_by_var: HashMap<VarId, Vec<u32>>,
    overlay_by_target: HashMap<CoefficientTarget, Vec<u32>>,
    overlay_by_param: HashMap<ParamId, Vec<u32>>,
    // Lazy global variable index over the base (None until first use).
    var_index: Option<PackedVarIndex>,
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

impl PackedStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Bulk-insert one constant block for a fresh target (P1.5B fast path).
    ///
    /// Caller preconditions (same contract as the P0 block primitive):
    /// `vars` are unique, no cell exists yet for `(target, var)`, values
    /// finite. `vars` must be sorted ascending (canonical row order); debug
    /// builds assert this. Returns the new `CoeffId`s in input order.
    pub fn build_constant_block(
        &mut self,
        target: CoefficientTarget,
        vars: &[VarId],
        values: &[f64],
    ) -> Vec<CoeffId> {
        debug_assert_eq!(vars.len(), values.len());
        debug_assert!(
            vars.windows(2).all(|w| w[0] < w[1]),
            "rows canonicalized by VarId"
        );
        let n = vars.len();
        self.identity_reserve(n);
        self.base_vars.reserve(n);
        self.base_values.reserve(n);
        self.base_ids.reserve(n);
        let start = self.base_vars.len() as u32;
        let mut ids = Vec::with_capacity(n);
        for (var, value) in vars.iter().zip(values.iter()) {
            let (index, generation) =
                self.identity_allocate(CellLocation::Packed(self.base_vars.len() as u32));
            let id = CoeffId::new(index, generation);
            self.base_vars.push(*var);
            self.base_values.push(*value);
            self.base_ids.push(id);
            ids.push(id);
        }
        let slice_idx = self.target_slices.len();
        self.target_slices.push(TargetSlice {
            target,
            start,
            len: n as u32,
        });
        self.target_directory.insert(target, slice_idx);
        ids
    }

    fn identity_reserve(&mut self, additional: usize) {
        self.identity.reserve(additional);
    }

    fn identity_allocate(&mut self, loc: CellLocation) -> (u32, Generation) {
        self.identity.allocate(loc)
    }

    fn slice_of(&self, target: CoefficientTarget) -> Option<&TargetSlice> {
        self.target_directory
            .get(&target)
            .map(|&i| &self.target_slices[i])
    }

    /// Canonical lookup: overlay first, then binary search in the target
    /// slice (rows canonicalized by VarId), honoring shadow/dead bits.
    pub fn for_cell(&self, target: CoefficientTarget, var: VarId) -> Option<(CoeffId, f64)> {
        if let Some(&oi) = self.overlay_by_cell.get(&(target, var)) {
            let cell = &self.overlay[oi as usize];
            if cell.tombstone {
                return None;
            }
            return Some((cell.coeff_id, cell.value));
        }
        let slice = self.slice_of(target)?;
        let base = &self.base_vars[slice.start as usize..(slice.start + slice.len) as usize];
        let pos = base.binary_search(&var).ok()?;
        let idx = slice.start + pos as u32;
        if bit_get(&self.dead, idx) || bit_get(&self.shadowed, idx) {
            return None;
        }
        Some((self.base_ids[idx as usize], self.base_values[idx as usize]))
    }

    /// Iterate all live cells of a target in a deterministic order (base
    /// slice order, then overlay insertion order for that target).
    pub fn iter_target(&self, target: CoefficientTarget) -> Vec<(CoeffId, VarId, f64)> {
        let mut out = Vec::new();
        if let Some(slice) = self.slice_of(target) {
            for k in 0..slice.len {
                let idx = slice.start + k;
                if bit_get(&self.dead, idx) || bit_get(&self.shadowed, idx) {
                    continue;
                }
                out.push((
                    self.base_ids[idx as usize],
                    self.base_vars[idx as usize],
                    self.base_values[idx as usize],
                ));
            }
        }
        if let Some(list) = self.overlay_by_target.get(&target) {
            for &oi in list {
                let cell = &self.overlay[oi as usize];
                if !cell.tombstone {
                    out.push((cell.coeff_id, cell.key.1, cell.value));
                }
            }
        }
        out
    }

    /// Remove a cell: overlay tombstone (+ arena invalidation) for overlay
    /// cells; dead bit + arena invalidation + tombstone record for packed
    /// cells. Re-adding later mints a fresh identity, as today.
    pub fn remove(&mut self, target: CoefficientTarget, var: VarId) -> bool {
        let key = (target, var);
        if let Some(&oi) = self.overlay_by_cell.get(&key) {
            let cell = &mut self.overlay[oi as usize];
            if cell.tombstone {
                return false;
            }
            cell.tombstone = true;
            let id = cell.coeff_id;
            self.identity.remove(id.index(), id.generation());
            return true;
        }
        let pos = match self.base_position(target, var) {
            Some(p) => p,
            None => return false,
        };
        bit_set(&mut self.dead, pos);
        let id = self.base_ids[pos as usize];
        self.identity.remove(id.index(), id.generation());
        // Tombstone record so cell-key resolution stops at the overlay.
        // It joins the delta lists like any overlay slot (the flag filters
        // it); a later re-add then needs no list surgery.
        let oi = self.overlay.len() as u32;
        self.overlay.push(OverlayCell {
            key,
            coeff_id: id,
            value_expr: ValueExpr::constant(f64::NAN),
            value: f64::NAN,
            tombstone: true,
        });
        self.overlay_by_cell.insert(key, oi);
        self.overlay_by_var.entry(var).or_default().push(oi);
        self.overlay_by_target.entry(target).or_default().push(oi);
        true
    }

    /// Update (or create) a cell, preserving its `CoeffId`. Packed cells are
    /// never mutated in place: the base position is shadowed and the new
    /// (possibly parameterized) representation lives in the overlay under
    /// the same logical identity.
    pub fn update(&mut self, target: CoefficientTarget, var: VarId, expr: ValueExpr, value: f64) {
        let key = (target, var);
        if let Some(&oi) = self.overlay_by_cell.get(&key) {
            let is_tombstone = self.overlay[oi as usize].tombstone;
            if is_tombstone {
                // Re-add after removal: fresh identity, as today. The
                // delta lists already reference `oi` (tombstones are
                // skipped, not unlinked); only parameter membership is
                // rebuilt for the new expression.
                let (index, generation) = self.identity_allocate(CellLocation::Overlay(oi));
                let id = CoeffId::new(index, generation);
                let cell = &mut self.overlay[oi as usize];
                cell.coeff_id = id;
                cell.value_expr = expr.clone();
                cell.value = value;
                cell.tombstone = false;
                Self::reindex_overlay_params(&mut self.overlay_by_param, oi, &expr.clone());
            } else {
                let cell = &mut self.overlay[oi as usize];
                cell.value_expr = expr.clone();
                cell.value = value;
                // Parameter index maintenance for changed expressions.
                Self::reindex_overlay_params(
                    &mut self.overlay_by_param,
                    oi,
                    &cell.value_expr.clone(),
                );
            }
            return;
        }
        if let Some(pos) = self.base_position(target, var) {
            bit_set(&mut self.shadowed, pos);
            let id = self.base_ids[pos as usize];
            if let Some(slot) = self.identity.get_mut(id.index(), id.generation()) {
                *slot = CellLocation::Overlay(self.overlay.len() as u32);
            }
            let oi = self.overlay.len() as u32;
            let cell = OverlayCell {
                key,
                coeff_id: id,
                value_expr: expr.clone(),
                value,
                tombstone: false,
            };
            self.overlay.push(cell);
            self.overlay_by_cell.insert(key, oi);
            let cell = &self.overlay[oi as usize];
            Self::index_overlay_cell(
                &mut self.overlay_by_var,
                &mut self.overlay_by_target,
                &mut self.overlay_by_param,
                oi,
                cell,
            );
            return;
        }
        // Create (matches scalar add() for a fresh cell).
        let oi = self.overlay.len() as u32;
        let (index, generation) = self.identity_allocate(CellLocation::Overlay(oi));
        let id = CoeffId::new(index, generation);
        let cell = OverlayCell {
            key,
            coeff_id: id,
            value_expr: expr.clone(),
            value,
            tombstone: false,
        };
        self.overlay.push(cell);
        self.overlay_by_cell.insert(key, oi);
        let cell = &self.overlay[oi as usize];
        Self::index_overlay_cell(
            &mut self.overlay_by_var,
            &mut self.overlay_by_target,
            &mut self.overlay_by_param,
            oi,
            cell,
        );
    }

    fn index_overlay_cell(
        by_var: &mut HashMap<VarId, Vec<u32>>,
        by_target: &mut HashMap<CoefficientTarget, Vec<u32>>,
        by_param: &mut HashMap<ParamId, Vec<u32>>,
        oi: u32,
        cell: &OverlayCell,
    ) {
        by_var.entry(cell.key.1).or_default().push(oi);
        by_target.entry(cell.key.0).or_default().push(oi);
        for p in cell.value_expr.dependencies() {
            by_param.entry(p).or_default().push(oi);
        }
    }

    fn reindex_overlay_params(
        by_param: &mut HashMap<ParamId, Vec<u32>>,
        oi: u32,
        new_expr: &ValueExpr,
    ) {
        // Sparse overlay: drop stale memberships by scan of the small
        // per-param lists, then insert current ones. Overlay-local only.
        for list in by_param.values_mut() {
            if let Some(pos) = list.iter().position(|&x| x == oi) {
                list.swap_remove(pos);
            }
        }
        for p in new_expr.dependencies() {
            by_param.entry(p).or_default().push(oi);
        }
    }

    fn base_position(&self, target: CoefficientTarget, var: VarId) -> Option<u32> {
        let slice = self.slice_of(target)?;
        let base = &self.base_vars[slice.start as usize..(slice.start + slice.len) as usize];
        let pos = base.binary_search(&var).ok()?;
        let idx = slice.start + pos as u32;
        if bit_get(&self.dead, idx) || bit_get(&self.shadowed, idx) {
            return None;
        }
        Some(idx)
    }

    /// Global variable lookup. Builds the packed-base index lazily on first
    /// use; overlay mutations maintain only their delta lists.
    pub fn for_var(&mut self, var: VarId) -> Vec<(CoeffId, CoefficientTarget, f64)> {
        if self.var_index.is_none() {
            self.var_index = Some(PackedVarIndex::build(&self.base_vars));
        }
        let index = self.var_index.as_ref().unwrap();
        let mut out = Vec::new();
        for &pos in index.positions(var) {
            if bit_get(&self.dead, pos) || bit_get(&self.shadowed, pos) {
                continue;
            }
            // Reverse-map base position to its target via slice directory.
            let target = self
                .target_slices
                .iter()
                .find(|s| pos >= s.start && pos < s.start + s.len)
                .map(|s| s.target);
            if let Some(target) = target {
                out.push((
                    self.base_ids[pos as usize],
                    target,
                    self.base_values[pos as usize],
                ));
            }
        }
        if let Some(list) = self.overlay_by_var.get(&var) {
            for &oi in list {
                let cell = &self.overlay[oi as usize];
                if !cell.tombstone {
                    out.push((cell.coeff_id, cell.key.0, cell.value));
                }
            }
        }
        out
    }

    // Prototype introspection for the harness; production exposes what it needs.
    #[allow(dead_code)]
    pub fn len_live(&self) -> usize {
        self.base_vars.len() + self.overlay.iter().filter(|c| !c.tombstone).count()
            - self.dead_count()
            - self.shadow_count()
    }

    fn dead_count(&self) -> usize {
        self.dead.iter().map(|w| w.count_ones() as usize).sum()
    }

    fn shadow_count(&self) -> usize {
        self.shadowed.iter().map(|w| w.count_ones() as usize).sum()
    }

    /// Overlay cells currently shadowing base positions (prototype introspection).
    #[allow(dead_code)]
    pub fn overlay_live_count(&self) -> usize {
        self.overlay.iter().filter(|c| !c.tombstone).count()
    }

    pub fn var_index_built(&self) -> bool {
        self.var_index.is_some()
    }

    /// For tests: resolve a logical id to its location.
    pub fn locate(&self, id: CoeffId) -> Option<CellLocation> {
        self.identity.get(id.index(), id.generation()).copied()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use roml::id::{Generation, ObjId};

    fn target() -> CoefficientTarget {
        CoefficientTarget::Objective(ObjId::new(0, Generation::new()))
    }

    fn vars(n: u32) -> Vec<VarId> {
        (0..n).map(|i| VarId::new(i, Generation::new())).collect()
    }

    #[test]
    fn build_lookup_iterate_remove_update() {
        let mut store = PackedStore::new();
        let t = target();
        let vs = vars(16);
        let vals: Vec<f64> = (0..16).map(|i| i as f64 + 0.5).collect();
        let ids = store.build_constant_block(t, &vs, &vals);
        assert_eq!(ids.len(), 16);
        for (i, v) in vs.iter().enumerate() {
            assert_eq!(store.for_cell(t, *v), Some((ids[i], vals[i])));
        }
        assert_eq!(store.iter_target(t).len(), 16);
        // Update preserves identity, shadows base.
        let (old_id, _) = store.for_cell(t, vs[3]).unwrap();
        store.update(t, vs[3], ValueExpr::constant(99.0), 99.0);
        assert_eq!(store.for_cell(t, vs[3]), Some((old_id, 99.0)));
        assert_eq!(store.locate(old_id), Some(CellLocation::Overlay(0)));
        // Remove then re-add mints fresh identity.
        assert!(store.remove(t, vs[4]));
        assert_eq!(store.for_cell(t, vs[4]), None);
        store.update(
            t,
            vs[4],
            ValueExpr::param(ParamId::new(1, Generation::new())),
            7.0,
        );
        let (new_id, val) = store.for_cell(t, vs[4]).unwrap();
        assert_ne!(new_id, ids[4]);
        assert_eq!(val, 7.0);
        assert_eq!(store.iter_target(t).len(), 16);
    }

    #[test]
    fn lazy_var_index_with_overlay_delta() {
        let mut store = PackedStore::new();
        let t = target();
        let vs = vars(8);
        let vals = vec![1.0; 8];
        store.build_constant_block(t, &vs, &vals);
        assert!(!store.var_index_built());
        assert_eq!(store.for_var(vs[2]).len(), 1);
        assert!(store.var_index_built());
        // Overlay update still resolves through the lazy index + delta.
        store.update(t, vs[2], ValueExpr::constant(5.0), 5.0);
        let hits = store.for_var(vs[2]);
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].2, 5.0);
    }

    #[test]
    fn distinct_targets_share_base() {
        let mut store = PackedStore::new();
        let t0 = CoefficientTarget::Objective(ObjId::new(0, Generation::new()));
        let t1 = CoefficientTarget::Objective(ObjId::new(1, Generation::new()));
        let vs = vars(4);
        store.build_constant_block(t0, &vs, &[1.0; 4]);
        store.build_constant_block(t1, &vs, &[2.0; 4]);
        assert_eq!(store.for_cell(t1, vs[0]).unwrap().1, 2.0);
        assert_eq!(store.iter_target(t0).len(), 4);
    }
}
