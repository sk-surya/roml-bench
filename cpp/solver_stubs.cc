// Unreachable-solver stubs for the minimal OR-Tools build.
//
// Our pinned OR-Tools is configured with USE_GUROBI=OFF and USE_GLOP=OFF,
// but libortools.so still references three symbols from those disabled
// backends (via linear-solver wrapper code that is always compiled).
// This benchmark hardcodes SolverType::kHighs and can never reach them.
//
// These definitions exist solely to complete the dynamic-link graph so the
// binary binds strictly (no --unresolved-symbols workaround) and passes
// LD_BIND_NOW=1. The solve entry points abort if ever called; the
// IsCorrectlyInstalled query truthfully returns false. If any of these
// fires, the benchmark configuration is wrong and must be revisited
// rather than worked around.

#include <cstdio>
#include <cstdlib>

#include "ortools/linear_solver/gurobi_util.h"
#include "ortools/linear_solver/proto_solver/glop_proto_solver.h"
#include "ortools/linear_solver/proto_solver/gurobi_proto_solver.h"

namespace operations_research {

absl::StatusOr<MPSolutionResponse> GurobiSolveProto(
    LazyMutableCopy<MPModelRequest> request, GRBenv* gurobi_env) {
  (void)request;
  (void)gurobi_env;
  std::fprintf(stderr,
               "mathopt_bench: Gurobi backend is disabled in this build\n");
  std::abort();
}

bool GurobiIsCorrectlyInstalled() { return false; }

MPSolutionResponse GlopSolveProto(
    LazyMutableCopy<MPModelRequest> request,
    std::atomic<bool>* interrupt_solve,
    std::function<void(const std::string&)> logging_callback) {
  (void)request;
  (void)interrupt_solve;
  (void)logging_callback;
  std::fprintf(stderr,
               "mathopt_bench: GLOP backend is disabled in this build\n");
  std::abort();
}

}  // namespace operations_research
