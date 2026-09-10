# JuMP benchmark runner: builds the contract workloads with idiomatic
# JuMP containers and emits exactly one JSON measurement record.
# Timed region is populate only (first variable through objective
# installation); model creation, warmup, and data parsing are outside.
# Never solves unless --solve is given (validation gate only).

using Dates
using HiGHS
using JuMP

const BESS_T = 96
const BESS_DT = 0.25
const BESS_ETA = 0.95
const BESS_P = 2.0
const BESS_E = 4.0
const BESS_E0 = 2.0

function rss_bytes()
    rss = hwm = 0
    try
        for line in eachline("/proc/self/status")
            if startswith(line, "VmRSS:")
                rss = parse(Int, split(line)[2]) * 1024
            elseif startswith(line, "VmHWM:")
                hwm = parse(Int, split(line)[2]) * 1024
            end
        end
    catch
    end
    return rss, hwm
end

function cli_arg(args, flag, default=nothing)
    i = findfirst(==(flag), args)
    i === nothing && return default
    return args[i+1]
end

function build_sparse(model, n)
    t0 = time_ns()
    @variable(model, x[1:n], lower_bound = 0.0, upper_bound = 5.0)
    t_vars = time_ns() - t0
    rows = n ÷ 10
    t0 = time_ns()
    @constraint(model, [r = 1:rows], sum(x[10*(r-1)+k] for k = 1:10) <= 10.0)
    t_cons = time_ns() - t0
    t0 = time_ns()
    @objective(model, Min, sum(x))
    t_obj = time_ns() - t0
    return model, t_vars, t_cons, t_obj, n, rows, 10 * rows, n
end

function build_bess(model, b, prices)
    @assert length(prices) == BESS_T
    t = BESS_T
    t0 = time_ns()
    @variable(model, charge[1:b, 1:t], lower_bound = 0.0, upper_bound = BESS_P)
    @variable(model, discharge[1:b, 1:t], lower_bound = 0.0, upper_bound = BESS_P)
    @variable(model, energy[1:b, 1:(t+1)], lower_bound = 0.0, upper_bound = BESS_E)
    t_vars = time_ns() - t0
    t0 = time_ns()
    @constraint(model, [bb = 1:b], energy[bb, 1] == BESS_E0)
    @constraint(model, [bb = 1:b, tt = 1:t],
        energy[bb, tt+1] == energy[bb, tt] + BESS_DT * (BESS_ETA * charge[bb, tt] - discharge[bb, tt] / BESS_ETA))
    @constraint(model, [bb = 1:b, tt = 1:t], charge[bb, tt] + discharge[bb, tt] <= BESS_P)
    t_cons = time_ns() - t0
    t0 = time_ns()
    # dt scales power to energy per interval, matching the contract objective.
    @objective(model, Max, BESS_DT * sum(prices[tt] * (discharge[bb, tt] - charge[bb, tt]) for bb = 1:b, tt = 1:t))
    t_obj = time_ns() - t0
    vars = b * (3 * t + 1)
    cons = b * (2 * t + 1)
    return model, t_vars, t_cons, t_obj, vars, cons, b * (1 + 6 * t), b * (2 * t)
end

function main()
    args = ARGS
    workload = cli_arg(args, "--workload")
    size = parse(Int, cli_arg(args, "--size"))
    seed = parse(Int, cli_arg(args, "--seed"))
    replicate = parse(Int, cli_arg(args, "--replicate"))
    run_id = cli_arg(args, "--run-id")
    benchmark_sha = cli_arg(args, "--benchmark-sha")
    roml_sha = cli_arg(args, "--roml-sha")
    timestamp = cli_arg(args, "--timestamp-utc")
    cpu = cli_arg(args, "--cpu", nothing)
    impl = cli_arg(args, "--implementation", "jump_julia")
    do_solve = "--solve" in args

    # Canonical data parsing happens before every timer.
    prices = Float64[]
    if workload == "bess_96"
        csv = cli_arg(args, "--prices-csv")
        csv === nothing && error("bess_96 requires --prices-csv")
        prices = parse.(Float64, split(csv, ","))
    end

    # Workload-specific warmup on a discarded model: first-use method
    # compilation for the actual containers/expression paths used below
    # must not leak into the phase timers.
    if workload == "sparse_rows"
        build_sparse(Model(), 10)
    elseif workload == "bess_96"
        build_bess(Model(), 1, prices)
    else
        error("unknown workload: $workload")
    end

    # container_init measures only fresh Model() construction.
    t_init = time_ns()
    model = Model()
    container_init_ns = time_ns() - t_init
    rss_before, _ = rss_bytes()

    if workload == "sparse_rows"
        _, t_vars, t_cons, t_obj, nvars, ncons, nnz, onnz = build_sparse(model, size)
    elseif workload == "bess_96"
        _, t_vars, t_cons, t_obj, nvars, ncons, nnz, onnz = build_bess(model, size, prices)
    else
        error("unknown workload: $workload")
    end
    populate_ns = t_vars + t_cons + t_obj
    rss_after, peak = rss_bytes()

    solved_obj = nothing
    if do_solve
        set_optimizer(model, HiGHS.Optimizer)
        set_silent(model)
        optimize!(model)
        solved_obj = objective_value(model)
    end

    # Fixed schema field order (the orchestrator scans for a leading
    # {"schema_version" line); Julia Dicts do not preserve order.
    buf = IOBuffer()
    write(buf, "{\"schema_version\": 1")
    write(buf, ", \"run_id\": \"$(run_id)\"")
    write(buf, ", \"timestamp_utc\": \"$(timestamp)\"")
    write(buf, ", \"benchmark_sha\": \"$(benchmark_sha)\"")
    write(buf, ", \"roml_sha\": \"$(roml_sha)\"")
    write(buf, ", \"implementation\": \"$(impl)\"")
    write(buf, ", \"workload\": \"$(workload)\"")
    write(buf, ", \"size\": $(size)")
    write(buf, ", \"variables\": $(nvars)")
    write(buf, ", \"constraints\": $(ncons)")
    write(buf, ", \"constraint_nnz\": $(nnz)")
    write(buf, ", \"objective_nnz\": $(onnz)")
    write(buf, ", \"replicate\": $(replicate)")
    write(buf, ", \"seed\": $(seed)")
    write(buf, ", \"variant\": \"canonical\"")
    write(buf, ", \"container_init_ns\": $(container_init_ns)")
    write(buf, ", \"populate_ns\": $(populate_ns)")
    write(buf, ", \"phases\": {\"variables\": $(t_vars), \"constraints\": $(t_cons), \"objective\": $(t_obj)}")
    write(buf, ", \"rss_before_bytes\": $(rss_before)")
    write(buf, ", \"rss_after_bytes\": $(rss_after)")
    write(buf, ", \"peak_rss_bytes\": $(peak)")
    if cpu === nothing
        write(buf, ", \"cpu\": null")
    else
        write(buf, ", \"cpu\": $(parse(Int, cpu))")
    end
    write(buf, ", \"status\": \"ok\", \"error\": null")
    if solved_obj !== nothing
        write(buf, ", \"objective_value\": $(solved_obj)")
    end
    write(buf, "}")
    println(String(take!(buf)))
end

main()
