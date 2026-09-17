# v2 post-MIR blocker — rank-2 dense numeric arrays (MIR-06 regression)

Status: **blocking benchmark v2 (A2/A3/A4/A5)**. Reported per the tranche rule
"if the benchmark exposes a genuine ROML defect: stop; report it; do not
benchmark-game around it". No ROML production code was changed and no
benchmark arm was adapted to dodge this.

## What happened

After repinning `roml-bench` to post-MIR ROML
(`8be9d35a76900f999e44e153b22a3ed0e0366bb5`), the validation gate fails:

```
.venv/bin/roml-bench validate
  status: failed
  problems: ["bess_96/1: no ROML bulk reference objective"]
  roml_python_vectorized: failed
```

The `roml_python_vectorized` BESS formulation arm builds its objective with
`rm.dot(price_grid, discharge - charge)` where `price_grid` is a rank-2 dense
numeric array. That call now raises:

```
roml.ShapeError: array composition: array shape mismatch: [1, 96] vs [96]
```

## Minimal reproduction (installed post-MIR wheel)

```python
import numpy as np, roml as rm
m = rm.Model(); x = m.vars("x", (2, 3), ub=1.0)
rm.dot(np.ones((2, 3)), x)        # ShapeError: [2, 3] vs [6]
m.add(x <= np.ones((2, 3)))       # ShapeError: [2, 3] vs [6]
rm.dot(np.ones(6), x)             # ShapeError: [6] does not match [2, 3]  (correct: flat != 2-D)
rm.dot(np.ones(6), m.vars("y", 6, ub=1.0))   # OK (rank-1)
rm.dot(m.params("p", np.ones((2, 3))), x)    # OK (parametric rank-2)
```

Scope: **every rank-2 (rank>1) dense numeric array used as a coefficient or a
constraint bound** fails; parametric arrays and rank-1 dense arrays are fine.
Affected public operations include `rm.dot(dense2d, expr2d)` and
`m.add(expr <= dense2d)` (also `>=`, `==`).

## Root cause (exact)

`roml-python/src/arrays.rs`, `array_operand` dense-numeric path (~line 1233):

```rust
scalar_constant_inner(
    owner_id,
    shape,                     // true array shape, e.g. [2, 3]
    roml::modeling::ConstantView::Dense {
        scale: 1.0,
        values: roml::modeling::NumView::from_vec(parsed.values),  // <-- 1-D [numel] = [6]
    },
)
```

`NumView::from_vec` builds a **1-D** contiguous view of length `numel`,
discarding `parsed.shape`. `LinArray::new(.., shape=[2,3], constant Dense[6])`
then fails in `validate_constant` (`src/modeling/coeff.rs`) with
`ShapeMismatch { left: [2,3], right: [6] }`, surfaced via `map_view_error` as
`array composition: ...`.

This is the only `NumView::from_vec(` dense-augmented call site in the binding
(`grep -n "NumView::from_vec(" roml-python/src/*.rs` -> one hit).

## Fix (one line, pending owner authorization)

```rust
values: roml::modeling::NumView::from_vec_shaped(shape.to_vec(), parsed.values)
    .map_err(map_view_error)?,
```

`NumView::from_vec_shaped(shape, values)` already exists
(`src/modeling/coeff.rs`, validates `product(shape) == values.len()` and builds
a row-major strided view), so the change is local to the binding and needs no
core change. A regression test should assert rank-2 dense `rm.dot` and rank-2
dense comparison bounds build, validate, and solve (`bess_96/1` would then pass
the existing validation gate).

## Provenance / coverage gap

- Worked at the benchmark's previous pin `c590692` (pre-MIR Python array IR,
  `dot_structural`); the defect appears after the MIR-06 shared-IR migration
  (`arrays.rs` rewritten across `1f329f2`, `8fe9a04`, `4caf5a5`, `27c9f4a`).
- ROML's own Python tests only exercise rank-1 `rm.dot` and use rank-2 shapes
  solely for a *rejection* case (`test_arrays.py`), so the regression is not
  caught by the current suite.

## Impact if unresolved

- `roml-bench validate` fails -> `check_validation_gate` refuses to run the
  orchestrator -> no post-MIR competitive construction numbers, no
  persistent-update family, no rules benchmark, no v2 plots, and PR 2 (README)
  has no accepted evidence to cite.
- It is also a real public-API regression for users (rank-2 dense
  coefficients/bounds), independent of the benchmark.

## Prepared branch state (no PR opened)

`roml-bench` branch `bench/v2-post-mir` (from `origin/main@0e90a77`) carries:
- ROML pin updated to `8be9d35...` in `schema.py`, `scripts/bootstrap.sh`,
  `rust-core/Cargo.toml`, `rust-core/src/main.rs`, the two probes, and
  `rust-store-proto/Cargo.toml`;
- `Cargo.lock` updated to the new `roml` git rev;
- `.cache/roml` checked out at `8be9d35`, wheel rebuilt and installed, core
  rebuilt.
No benchmark run was committed; the prior evidence under `results/` is
untouched.
