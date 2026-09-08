//! Kernel A: verbatim copy of the P0 coefficient topology
//! (`CoefficientIndex` + `IdArena` from the P0 worktree), import-rewritten
//! to `roml::` with visibility lifted. Behavior identical; proves the copy
//! via its own ported unit tests.
pub mod arena;
pub mod store;
