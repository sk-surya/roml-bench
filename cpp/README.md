# C++ MathOpt benchmark runner

`mathopt_bench.cc` builds the contract workloads with the OR-Tools
MathOpt C++ API (`Model` / `AddVariable` / `AddLinearConstraint` /
`Maximize` / `Minimize`, HiGHS solver) and emits one JSON measurement
record with the same CLI/record contract as `roml-bench-core`
(`--workload --size --seed --replicate --run-id --benchmark-sha
--roml-sha --timestamp-utc --implementation [--cpu] [--prices-csv]`,
plus `--solve` for the validation gate).

## Pinned source

- OR-Tools **v9.15** shallow checkout lives outside the repo at
  `../.cache/or-tools-v9.15` (gitignored, same convention as
  `.cache/roml`).
- Minimal configuration: C++ only, no samples/examples/tests, only the
  HiGHS solver backend (`USE_HIGHS=ON`, all other `USE_*` solvers OFF).

Configure once (FetchContent downloads third-party deps):

```bash
cmake -S ../.cache/or-tools-v9.15 -B ../.cache/or-tools-v9.15/build \
  -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_CXX=ON -DBUILD_PYTHON=OFF -DBUILD_JAVA=OFF -DBUILD_DOTNET=OFF \
  -DBUILD_SAMPLES=OFF -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF \
  -DBUILD_DEPS=ON \
  -DUSE_BOP=OFF -DUSE_COINOR=OFF -DUSE_GLOP=OFF -DUSE_GLPK=OFF \
  -DUSE_GUROBI=OFF -DUSE_HIGHS=ON -DUSE_PDLP=OFF -DUSE_SCIP=OFF \
  -DUSE_XPRESS=OFF -DUSE_CPLEX=OFF
cmake --build ../.cache/or-tools-v9.15/build --target ortools -j 24
```

## Build this runner

```bash
bash cpp/build.sh   # produces cpp/build/mathopt_bench (gitignored)
```

The link needs the canonical OR-Tools defines
(`-DOR_PROTO_DLL="" -DPROTOBUF_USE_DLLS -DUSE_HIGHS -DUSE_MATH_OPT`)
and `-Wl,--unresolved-symbols=ignore-in-shared-libs`: `libortools.so`
carries references to the disabled Gurobi/GLOP solver backends, which
this benchmark can never reach (it hardcodes
`SolverType::kHighs`). Scoped to shared-library symbols only; our own
objects stay strict.
