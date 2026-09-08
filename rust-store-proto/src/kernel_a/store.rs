//! Coefficient storage with multi-indexing.
//!
//! Coefficients are first-class objects linking variables to targets (constraints or objectives).
//! They support efficient lookup by:
//! - Variable (for deletion, solver projection)
//! - Constraint (for deletion, iteration)
//! - Objective (for deletion, iteration)
//! - Parameter (for value propagation)
//!
//! Key idea is the use of expr from which value can be evaluated.

use std::collections::{HashMap, HashSet};

use super::arena::IdArena;
use roml::id::{CoeffId, ConId, ObjId, ParamId, VarId};
use roml::value_expr::ValueExpr;

/// Target of a coefficient (constraint or objective).
// Prototype-only allow: this single-target harness never constructs the
// constraint variant (the copied implementation and its ported tests do).
#[allow(dead_code)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CoefficientTarget {
    /// Coefficient belongs to a constraint.
    Constraint(ConId),
    /// Coefficient belongs to an objective.
    Objective(ObjId),
}

/// Internal data for a coefficient.
#[derive(Clone, Debug)]
pub struct CoefficientData {
    /// The variable this coefficient is multiplied with.
    pub var: VarId,
    /// The target (constraint or objective) this coefficient belongs to.
    pub target: CoefficientTarget,
    /// The value expression (constant or can depend on parameters).
    pub value_expr: ValueExpr,
    /// Cached evaluated value (updated on parameter changes)
    pub cached_value: f64,
}

impl CoefficientData {
    /// Create a new coefficient.
    pub fn new(
        var: VarId,
        target: CoefficientTarget,
        value_expr: ValueExpr,
        initial_value: f64,
    ) -> Self {
        Self {
            var,
            target,
            value_expr,
            cached_value: initial_value,
        }
    }
}

/// A unique cell key: one cell per (target, variable) pair.
pub type CellKey = (CoefficientTarget, VarId);

/// Multi-indexed coefficient storage.
///
/// Provides O(1) lookup in multiple dimensions:
/// - By coefficient ID (primary)
/// - By variable (for deletion cascades)
/// - By constraint (for constraint operations)
/// - By objective (for objective operations)
/// - By parameter (for value propagation)
/// - By cell key (for canonical uniqueness: one cell per (target, variable))
///
/// When a coefficient is added for a cell that already exists, the
/// expressions are algebraically combined rather than creating a duplicate.
#[derive(Clone, Debug, Default)]
pub struct CoefficientIndex {
    /// Primary Storage
    arena: IdArena<CoefficientData>,

    /// Coefficients by variable: VarId -> Set of CoeffIds.
    by_var: HashMap<VarId, HashSet<CoeffId>>,

    /// Coefficients by constraint: ConId -> Set of CoeffIds.
    by_constraint: HashMap<ConId, HashSet<CoeffId>>,

    /// Coefficients by objective: ObjId -> Set of CoeffIds.
    by_objective: HashMap<ObjId, HashSet<CoeffId>>,

    /// Coefficients by parameter (dependency graph): ParamId -> Set of CoeffIds.
    by_param: HashMap<ParamId, HashSet<CoeffId>>,

    /// Canonical cell index: exactly one CoeffId per (target, variable) pair.
    by_cell: HashMap<CellKey, CoeffId>,
}

/// Methods used by Model and backend adapters.
#[allow(dead_code)]
impl CoefficientIndex {
    /// Create an empty coefficient index.
    pub fn new() -> Self {
        Self {
            arena: IdArena::new(),
            by_var: HashMap::new(),
            by_constraint: HashMap::new(),
            by_objective: HashMap::new(),
            by_param: HashMap::new(),
            by_cell: HashMap::new(),
        }
    }

    /// Add a new coefficient or combine with an existing cell.
    ///
    /// If a coefficient already exists for this (target, variable) pair,
    /// the expressions are algebraically added and the existing coefficient
    /// is updated in place. Returns the (possibly existing) CoeffId.
    ///
    /// Automatically updates all secondary indexes based on the value
    /// expression's dependencies.
    pub fn add(
        &mut self,
        var: VarId,
        target: CoefficientTarget,
        value_expr: ValueExpr,
        initial_value: f64,
    ) -> CoeffId {
        let cell_key = (target, var);

        // Check if a cell already exists for this (target, variable) pair.
        if let Some(&existing_id) = self.by_cell.get(&cell_key) {
            // Combine expressions atomically.
            // First collect the old dependencies.
            let old_deps: Vec<ParamId> = self
                .arena
                .get(existing_id.index(), existing_id.generation())
                .map(|d| d.value_expr.dependencies().into_iter().collect::<Vec<_>>())
                .unwrap_or_default();

            // Remove old param dependencies
            for param in &old_deps {
                if let Some(set) = self.by_param.get_mut(param) {
                    set.remove(&existing_id);
                    if set.is_empty() {
                        self.by_param.remove(param);
                    }
                }
            }

            // Get the existing expression and combine
            if let Some(existing) = self
                .arena
                .get_mut(existing_id.index(), existing_id.generation())
            {
                let combined = existing.value_expr.clone() + value_expr;
                let new_cached = existing.cached_value + initial_value;

                existing.value_expr = combined.clone();
                existing.cached_value = new_cached;

                // Re-add param dependencies for combined expression
                for param in combined.dependencies() {
                    self.by_param.entry(param).or_default().insert(existing_id);
                }

                return existing_id;
            }
        }

        // New cell: allocate and index.
        let data = CoefficientData::new(var, target, value_expr.clone(), initial_value);
        let (index, generation) = self.arena.allocate(data);
        let id = CoeffId::new(index, generation);

        // Update by_var index
        self.by_var.entry(var).or_default().insert(id);

        // Update by_constraint or by_objective index
        match target {
            CoefficientTarget::Constraint(con) => {
                self.by_constraint.entry(con).or_default().insert(id);
            }
            CoefficientTarget::Objective(obj) => {
                self.by_objective.entry(obj).or_default().insert(id);
            }
        }

        // Update by_param based on dependencies
        for param in value_expr.dependencies() {
            self.by_param.entry(param).or_default().insert(id);
        }

        // Update by_cell index
        self.by_cell.insert(cell_key, id);

        id
    }

    /// Reserve index capacity for a bulk insertion of `additional` cells.
    ///
    /// Backs [`Self::add_constant_unique_block`]: every map grows once so a
    /// million-cell block does not pay repeated rehashing.
    pub fn reserve(&mut self, target: CoefficientTarget, additional: usize) {
        self.arena.reserve(additional);
        self.by_var.reserve(additional);
        match target {
            CoefficientTarget::Constraint(_) => {
                self.by_constraint.reserve(additional);
            }
            CoefficientTarget::Objective(_) => {
                self.by_objective.reserve(additional);
            }
        }
        self.by_cell.reserve(additional);
    }

    /// Insert a block of constant coefficients for distinct, previously
    /// empty cells.
    ///
    /// P0 bulk path. Unlike [`Self::add`], this performs no cell-existence
    /// probes, no parameter-dependency work (constants have none, so
    /// `by_param` is untouched), and no per-cell changelog handling — the
    /// caller journals one packed change. Storage for all cells is reserved
    /// once up front (see [`Self::reserve`]).
    ///
    /// # Caller contract
    ///
    /// Every `(target, var)` pair must be unique within `vars` and must not
    /// already hold a cell; otherwise an existing `by_cell` entry would be
    /// silently overwritten and its `CoeffId` leaked. The public bulk entry
    /// point establishes this (fresh objective + uniqueness scan with a
    /// general-path fallback for duplicates).
    ///
    /// Returns nothing; identities are deterministic (input order) and can
    /// be recovered per cell with [`Self::for_cell`].
    pub fn add_constant_unique_block(&mut self, target: CoefficientTarget, cells: &[(VarId, f64)]) {
        self.reserve(target, cells.len());
        for (var, value) in cells.iter() {
            let data = CoefficientData::new(*var, target, ValueExpr::constant(*value), *value);
            let (index, generation) = self.arena.allocate(data);
            let id = CoeffId::new(index, generation);
            self.by_var.entry(*var).or_default().insert(id);
            match target {
                CoefficientTarget::Constraint(con) => {
                    self.by_constraint.entry(con).or_default().insert(id);
                }
                CoefficientTarget::Objective(obj) => {
                    self.by_objective.entry(obj).or_default().insert(id);
                }
            }
            self.by_cell.insert((target, *var), id);
        }
    }

    /// Replace an existing coefficient's value expression, maintaining the
    /// parameter dependency index.
    ///
    /// The coefficient's identity and cell key are unchanged; only the
    /// expression and cached value are replaced (D11 replace-by-cell semantics).
    pub fn set_expr(&mut self, id: CoeffId, value_expr: ValueExpr, evaluated: f64) {
        // Drop the old parameter dependencies.
        let old_deps: Vec<ParamId> = self
            .arena
            .get(id.index(), id.generation())
            .map(|d| d.value_expr.dependencies().into_iter().collect())
            .unwrap_or_default();
        for param in &old_deps {
            if let Some(set) = self.by_param.get_mut(param) {
                set.remove(&id);
                if set.is_empty() {
                    self.by_param.remove(param);
                }
            }
        }

        // Update the expression and cached value, then re-index dependencies.
        if let Some(existing) = self.arena.get_mut(id.index(), id.generation()) {
            existing.value_expr = value_expr.clone();
            existing.cached_value = evaluated;
            for param in value_expr.dependencies() {
                self.by_param.entry(param).or_default().insert(id);
            }
        }
    }

    /// Remove a coefficient by ID.
    ///
    /// Returns the data if it existed. Automatically cleans up all secondary indices.
    pub fn remove(&mut self, id: CoeffId) -> Option<CoefficientData> {
        let data = self.arena.remove(id.index(), id.generation())?;

        // Clean up by_cell index
        let cell_key = (data.target, data.var);
        self.by_cell.remove(&cell_key);

        // Clean up by_var index
        if let Some(set) = self.by_var.get_mut(&data.var) {
            set.remove(&id);
            if set.is_empty() {
                self.by_var.remove(&data.var);
            }
        }

        // Clean up by_constraint or by_objective index
        match data.target {
            CoefficientTarget::Constraint(con) => {
                if let Some(set) = self.by_constraint.get_mut(&con) {
                    set.remove(&id);
                    if set.is_empty() {
                        self.by_constraint.remove(&con);
                    }
                }
            }
            CoefficientTarget::Objective(obj) => {
                if let Some(set) = self.by_objective.get_mut(&obj) {
                    set.remove(&id);
                    if set.is_empty() {
                        self.by_objective.remove(&obj);
                    }
                }
            }
        }

        // Clean up by_param index
        for param in data.value_expr.dependencies() {
            if let Some(set) = self.by_param.get_mut(&param) {
                set.remove(&id);
                if set.is_empty() {
                    self.by_param.remove(&param);
                }
            }
        }

        Some(data)
    }

    /// Get coefficient data by ID.
    pub fn get(&self, id: CoeffId) -> Option<&CoefficientData> {
        self.arena.get(id.index(), id.generation())
    }

    /// Get mutable coefficient data by ID.
    pub fn get_mut(&mut self, id: CoeffId) -> Option<&mut CoefficientData> {
        self.arena.get_mut(id.index(), id.generation())
    }

    /// Check if a coefficient ID is valid.
    pub fn contains(&self, id: CoeffId) -> bool {
        self.arena.contains(id.index(), id.generation())
    }

    // ========== By-Variable Queries ==========

    /// Get all coefficients for a variable.
    pub fn for_var(&self, var: VarId) -> impl Iterator<Item = CoeffId> + '_ {
        self.by_var.get(&var).into_iter().flatten().copied()
    }

    /// Check if a variable has any coefficients.
    pub fn var_has_coefficients(&self, var: VarId) -> bool {
        self.by_var.get(&var).is_some_and(|s| !s.is_empty())
    }

    // ========== By-Constraint Queries ==========

    /// Get all coefficients for a constraint.
    pub fn for_constraint(&self, con: ConId) -> impl Iterator<Item = CoeffId> + '_ {
        self.by_constraint.get(&con).into_iter().flatten().copied()
    }

    /// Check if a constraint has any coefficients.
    pub fn constraint_has_coefficients(&self, con: ConId) -> bool {
        self.by_constraint.get(&con).is_some_and(|s| !s.is_empty())
    }

    // ========== By-Objective Queries ==========

    /// Get all coefficients for an objective.
    pub fn for_objective(&self, obj: ObjId) -> impl Iterator<Item = CoeffId> + '_ {
        self.by_objective.get(&obj).into_iter().flatten().copied()
    }

    /// Check if an objective has any coefficients.
    pub fn objective_has_coefficients(&self, obj: ObjId) -> bool {
        self.by_objective.get(&obj).is_some_and(|s| !s.is_empty())
    }

    // ========== By-Parameter Queries (Dependency Graph) ==========

    /// Get all coefficients that depend on a parameter.
    ///
    /// This is the dependency graph used for parameter propagation.
    pub fn for_param(&self, param: ParamId) -> impl Iterator<Item = CoeffId> + '_ {
        self.by_param.get(&param).into_iter().flatten().copied()
    }

    /// Check if a parameter has any dependent coefficients.
    pub fn param_has_dependents(&self, param: ParamId) -> bool {
        self.by_param.get(&param).is_some_and(|s| !s.is_empty())
    }

    /// Get the count of coefficients depending on a parameter.
    pub fn param_dependent_count(&self, param: ParamId) -> usize {
        self.by_param.get(&param).map_or(0, |s| s.len())
    }

    // ========== General Queries ==========

    /// Get the total number of coefficients.
    pub fn len(&self) -> usize {
        self.arena.len()
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        self.arena.is_empty()
    }

    /// Iterate over all coefficients.
    pub fn iter(&self) -> impl Iterator<Item = (CoeffId, &CoefficientData)> {
        self.arena
            .iter()
            .map(|(idx, gen, data)| (CoeffId::new(idx, gen), data))
    }

    /// Iterate mutably over all coefficients.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = (CoeffId, &mut CoefficientData)> {
        self.arena
            .iter_mut()
            .map(|(idx, gen, data)| (CoeffId::new(idx, gen), data))
    }

    // ========== Index Iteration (for invariant checking) ==========

    /// Iterate over the by_var index entries.
    pub fn by_var_iter(&self) -> impl Iterator<Item = (&VarId, &HashSet<CoeffId>)> {
        self.by_var.iter()
    }

    /// Iterate over the by_constraint index entries.
    pub fn by_constraint_iter(&self) -> impl Iterator<Item = (&ConId, &HashSet<CoeffId>)> {
        self.by_constraint.iter()
    }

    /// Iterate over the by_objective index entries.
    pub fn by_objective_iter(&self) -> impl Iterator<Item = (&ObjId, &HashSet<CoeffId>)> {
        self.by_objective.iter()
    }

    /// Iterate over the by_param index entries.
    pub fn by_param_iter(&self) -> impl Iterator<Item = (&ParamId, &HashSet<CoeffId>)> {
        self.by_param.iter()
    }

    // ========== Cell Queries ==========

    /// Get the coefficient ID for a specific (target, variable) cell.
    /// Returns `None` if no coefficient exists for that cell.
    pub fn for_cell(&self, target: CoefficientTarget, var: VarId) -> Option<CoeffId> {
        self.by_cell.get(&(target, var)).copied()
    }

    /// Check if a cell exists for (target, variable).
    pub fn cell_exists(&self, target: CoefficientTarget, var: VarId) -> bool {
        self.by_cell.contains_key(&(target, var))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use roml::id::Generation;

    fn make_var(index: u32) -> VarId {
        VarId::new(index, Generation::new())
    }

    fn make_con(index: u32) -> ConId {
        ConId::new(index, Generation::new())
    }

    fn make_obj(index: u32) -> ObjId {
        ObjId::new(index, Generation::new())
    }

    fn make_param(index: u32) -> ParamId {
        ParamId::new(index, Generation::new())
    }

    #[test]
    fn add_and_lookup() {
        let mut index = CoefficientIndex::new();
        let var = make_var(0);
        let con = make_con(0);

        let id = index.add(
            var,
            CoefficientTarget::Constraint(con),
            ValueExpr::constant(2.0),
            2.0,
        );

        assert!(index.contains(id));
        let data = index.get(id).unwrap();
        assert_eq!(data.var, var);
        assert_eq!(data.cached_value, 2.0);
    }

    #[test]
    fn by_var_index() {
        let mut index = CoefficientIndex::new();
        let var1 = make_var(0);
        let var2 = make_var(1);
        let con1 = make_con(0);
        let con2 = make_con(1);

        // Two coefficients for var1 on different constraints
        let id1 = index.add(
            var1,
            CoefficientTarget::Constraint(con1),
            ValueExpr::constant(1.0),
            1.0,
        );
        let id2 = index.add(
            var1,
            CoefficientTarget::Constraint(con2),
            ValueExpr::constant(2.0),
            2.0,
        );

        let var1_coeffs: HashSet<_> = index.for_var(var1).collect();
        assert_eq!(var1_coeffs.len(), 2);
        assert!(var1_coeffs.contains(&id1));
        assert!(var1_coeffs.contains(&id2));

        // var2 has no coefficients
        assert!(index.for_var(var2).next().is_none());
    }

    #[test]
    fn by_constraint_index() {
        let mut index = CoefficientIndex::new();
        let var = make_var(0);
        let con1 = make_con(0);
        let con2 = make_con(1);

        let id1 = index.add(
            var,
            CoefficientTarget::Constraint(con1),
            ValueExpr::constant(1.0),
            1.0,
        );
        let _id2 = index.add(
            var,
            CoefficientTarget::Constraint(con2),
            ValueExpr::constant(2.0),
            2.0,
        );

        let con1_coeffs: Vec<_> = index.for_constraint(con1).collect();
        assert_eq!(con1_coeffs, vec![id1]);
    }

    #[test]
    fn canonical_cell_combines_expressions() {
        let mut index = CoefficientIndex::new();
        let var = make_var(0);
        let con = make_con(0);
        let p1 = make_param(0);

        // Add first term: p1 * var
        let id1 = index.add(
            var,
            CoefficientTarget::Constraint(con),
            ValueExpr::param(p1),
            1.0,
        );

        // Add second term: 2.0 * var (constant) for the SAME cell
        // Should combine with existing: p1*var + 2.0*var = (p1+2.0)*var
        let id2 = index.add(
            var,
            CoefficientTarget::Constraint(con),
            ValueExpr::constant(2.0),
            2.0,
        );

        // Should return the same coefficient ID (combined in place)
        assert_eq!(id1, id2, "canonical cell should return same ID on combine");

        let data = index.get(id1).unwrap();
        // Cached value combines: 1.0 + 2.0 = 3.0
        assert_eq!(data.cached_value, 3.0);

        // p1 still depends on this coefficient
        assert!(index.param_has_dependents(p1));

        // Only one coefficient exists for this cell
        assert_eq!(index.len(), 1);
    }

    #[test]
    fn separate_cells_do_not_combine() {
        let mut index = CoefficientIndex::new();
        let var = make_var(0);
        let con1 = make_con(0);
        let con2 = make_con(1);
        let p1 = make_param(0);

        // Different constraints → different cells
        let id1 = index.add(
            var,
            CoefficientTarget::Constraint(con1),
            ValueExpr::param(p1),
            1.0,
        );
        let id2 = index.add(
            var,
            CoefficientTarget::Constraint(con2),
            ValueExpr::constant(3.0),
            3.0,
        );

        assert_ne!(id1, id2);
        assert_eq!(index.len(), 2);

        // p1 depends only on id1
        let p1_coeffs: Vec<_> = index.for_param(p1).collect();
        assert_eq!(p1_coeffs, vec![id1]);
    }

    #[test]
    fn remove_cleans_indexes() {
        let mut index = CoefficientIndex::new();
        let var = make_var(0);
        let con = make_con(0);
        let param = make_param(0);

        let id = index.add(
            var,
            CoefficientTarget::Constraint(con),
            ValueExpr::param(param),
            1.0,
        );

        assert!(index.var_has_coefficients(var));
        assert!(index.constraint_has_coefficients(con));
        assert!(index.param_has_dependents(param));

        index.remove(id);

        assert!(!index.var_has_coefficients(var));
        assert!(!index.constraint_has_coefficients(con));
        assert!(!index.param_has_dependents(param));
    }

    #[test]
    fn objective_coefficients() {
        let mut index = CoefficientIndex::new();
        let var = make_var(0);
        let obj = make_obj(0);

        let id = index.add(
            var,
            CoefficientTarget::Objective(obj),
            ValueExpr::constant(5.0),
            5.0,
        );

        assert!(index.objective_has_coefficients(obj));
        let obj_coeffs: Vec<_> = index.for_objective(obj).collect();
        assert_eq!(obj_coeffs, vec![id]);
    }
}
