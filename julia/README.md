# JuMP benchmark runner

`jump_bench.jl` builds the contract workloads with idiomatic JuMP
containers (`@variable`/`@constraint`/`@objective`, HiGHS.jl) and emits
one JSON measurement record with the same CLI/record contract as the
other external runners (`--workload --size --seed --replicate --run-id
--benchmark-sha --roml-sha --timestamp-utc --implementation [--cpu]
[--prices-csv]`, plus `--solve` for the validation gate).

## Pinned toolchain

- Julia **1.12.7** via `juliaup` (`juliaup add 1.12.7`).
- `Project.toml` + `Manifest.toml` pin JuMP v1.31.2 and HiGHS.jl v1.25.2;
  do not float them without re-validating.

## Notes

- Each replicate is a fresh Julia process with an unrecorded JIT warmup
  outside the timer (a tiny model built and discarded first).
- BESS prices arrive via `--prices-csv` (suite-canonical, same as the
  native core runner) because NumPy's RNG stream is not reproducible
  from Julia.
- RSS comes from `/proc/self/status` (VmRSS/VmHWM), same as the native
  runner. Expect a large baseline (~0.5 GiB): that is the Julia runtime,
  not the model.
