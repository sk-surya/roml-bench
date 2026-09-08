//! Arena allocator for ID generation.
//!
//! Provides monotonic ID allocation with generation tracking for staleness detection.
//! IDs are never reused - when an entity is deleted, its slot's generation is bumped.

use roml::id::Generation;

/// Slot state in the arena.
#[derive(Clone, Debug)]
pub struct Slot<T> {
    /// The data stored in this slot, if occupied.
    pub data: Option<T>,
    /// Current generation of this slot.
    pub generation: Generation,
}

impl<T> Default for Slot<T> {
    fn default() -> Self {
        Self {
            data: None,
            generation: Generation::new(),
        }
    }
}

/// Arena allocator for typed IDs.
///
/// # Design
///
/// - Uses monotonic allocation (always allocates from the end)
/// - Never reuses indices (deleted slots stay with bumped generation)
/// - O(1) allocation and lookup
/// - Generation tracking for stale ID detection
///
/// # Trade-offs
///
/// - Memory: Deleted slots are not reclaimed (intentional for ID stability)
/// - For most MILP models, this is acceptable as deletions are rare
/// - If memory becomes an issue, consider periodic compaction (not implemented, TODO - maybe never)
#[derive(Clone, Debug)]
pub struct IdArena<T> {
    slots: Vec<Slot<T>>,
    /// Count of occupied slots (for len())
    count: usize,
}

impl<T> Default for IdArena<T> {
    fn default() -> Self {
        Self::new()
    }
}

impl<T> IdArena<T> {
    /// Create a new empty arena.
    pub const fn new() -> Self {
        Self {
            slots: Vec::new(),
            count: 0,
        }
    }

    /// Create an arena with pre-allocated capacity.
    // Prototype-only allow: the copy keeps the full source; ROML uses this elsewhere.
    #[allow(dead_code)]
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            slots: Vec::with_capacity(capacity),
            count: 0,
        }
    }

    /// Allocate a new slot and return its index and generation.
    ///
    /// Always allocates from the end (monotonic). Never reuses indices.
    pub fn allocate(&mut self, data: T) -> (u32, Generation) {
        let index = self.slots.len() as u32;
        let generation = Generation::new();
        self.slots.push(Slot {
            data: Some(data),
            generation,
        });
        self.count += 1;
        (index, generation)
    }

    /// Reserve capacity for additional slots.
    ///
    /// Backs bulk-insertion paths that allocate many IDs at once so the
    /// slot vector grows once instead of rehashing/growing repeatedly.
    pub fn reserve(&mut self, additional: usize) {
        self.slots.reserve(additional);
    }

    /// Remove an entity by index and generation.
    ///
    /// Returns the data if the ID was valid, None if stale or out of bounds.
    /// Bumps the slot's generation to invalidate any remaining references.
    pub fn remove(&mut self, index: u32, generation: Generation) -> Option<T> {
        let slot = self.slots.get_mut(index as usize)?;
        if slot.generation != generation || slot.data.is_none() {
            return None;
        }
        slot.generation = slot.generation.next();
        self.count -= 1;
        slot.data.take()
    }

    /// Get a reference to the data at the given index and generation.
    ///
    /// Returns None if the ID is stale or out of bounds.
    pub fn get(&self, index: u32, generation: Generation) -> Option<&T> {
        let slot = self.slots.get(index as usize)?;
        if slot.generation != generation {
            return None;
        }
        slot.data.as_ref()
    }

    /// Get a mutable reference to the data at the given index and generation.
    ///
    /// Returns None if the ID is stale or out of bounds.
    pub fn get_mut(&mut self, index: u32, generation: Generation) -> Option<&mut T> {
        let slot = self.slots.get_mut(index as usize)?;
        if slot.generation != generation {
            return None;
        }
        slot.data.as_mut()
    }

    /// Check if an ID is valid (exists and generation matches).
    pub fn contains(&self, index: u32, generation: Generation) -> bool {
        self.get(index, generation).is_some()
    }

    /// Get the number of occupied slots.
    #[inline]
    pub fn len(&self) -> usize {
        self.count
    }

    /// Check if the arena is empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// Get the total number of slots (including deleted).
    #[inline]
    #[allow(dead_code)] // used by store unit tests; crate-private since P23
    pub fn capacity_used(&self) -> usize {
        self.slots.len()
    }

    /// Iterate over all occupied slots with their indices.
    ///
    /// Yields (index, generation, &data) for each occupied slot.
    pub fn iter(&self) -> impl Iterator<Item = (u32, Generation, &T)> {
        self.slots.iter().enumerate().filter_map(|(idx, slot)| {
            slot.data
                .as_ref()
                .map(|data| (idx as u32, slot.generation, data))
        })
    }

    /// Iterate mutably over all occupied slots with their indices.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = (u32, Generation, &mut T)> {
        self.slots.iter_mut().enumerate().filter_map(|(idx, slot)| {
            let generation = slot.generation;
            slot.data
                .as_mut()
                .map(|data| (idx as u32, generation, data))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allocate_and_get() {
        let mut arena: IdArena<i32> = IdArena::new();
        let (idx, generation) = arena.allocate(42);
        assert_eq!(arena.get(idx, generation), Some(&42));
        assert_eq!(arena.len(), 1);
    }

    #[test]
    fn remove_and_staleness() {
        let mut arena: IdArena<i32> = IdArena::new();
        let (idx, generation) = arena.allocate(42);

        // Remove returns the data
        let removed = arena.remove(idx, generation);
        assert_eq!(removed, Some(42));
        assert_eq!(arena.len(), 0);

        // ID is now stale
        assert!(arena.get(idx, generation).is_none());

        // Second remove with same ID fails
        assert!(arena.remove(idx, generation).is_none());
    }

    #[test]
    fn ids_never_reused() {
        let mut arena: IdArena<i32> = IdArena::new();
        let (idx1, gen1) = arena.allocate(1);
        let (idx2, _gen2) = arena.allocate(2);

        // Remove first
        arena.remove(idx1, gen1);

        // Allocate again - should get new index, not reuse idx1
        let (idx3, _gen3) = arena.allocate(3);
        assert_eq!(idx3, idx2 + 1);
        assert_ne!(idx3, idx1);
    }

    #[test]
    fn iteration() {
        let mut arena: IdArena<i32> = IdArena::new();
        arena.allocate(1);
        let (idx, generation) = arena.allocate(2);
        arena.allocate(3);

        // Remove middle element
        arena.remove(idx, generation);
        // Iteration should skip removed
        let values: Vec<_> = arena.iter().map(|(_, _, &v)| v).collect();
        assert_eq!(values, vec![1, 3]);
    }

    #[test]
    fn with_capacity_default_slot_and_iter_mut() {
        // Slot::default is an empty slot with a fresh generation.
        let slot: Slot<i32> = Slot::default();
        assert!(slot.data.is_none());

        let mut arena: IdArena<i32> = IdArena::with_capacity(4);
        assert!(arena.is_empty());
        let (idx, gen) = arena.allocate(1);
        arena.allocate(2);
        assert!(!arena.is_empty());
        assert_eq!(arena.len(), 2);

        // iter_mut mutates every occupied slot in place.
        for (_, _, v) in arena.iter_mut() {
            *v *= 10;
        }
        assert_eq!(arena.get(idx, gen), Some(&10));
    }
}
