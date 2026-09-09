// MathOpt C++ benchmark runner: builds the contract workloads with the
// documented MathOpt modeling API and emits exactly one JSON measurement
// record. Timed region is populate only (first variable through objective
// installation); model creation, warmup, and data parsing are outside.
// Never solves unless --solve is given (validation gate only).

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "ortools/math_opt/cpp/model.h"
#include "ortools/math_opt/cpp/parameters.h"
#include "ortools/math_opt/cpp/solve.h"

namespace math_opt = operations_research::math_opt;

namespace {

constexpr int kBessT = 96;
constexpr double kBessDt = 0.25;
constexpr double kBessEta = 0.95;
constexpr double kBessP = 2.0;
constexpr double kBessE = 4.0;
constexpr double kBessE0 = 2.0;
constexpr double kInf = std::numeric_limits<double>::infinity();

int64_t NowNs() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

void ReadRss(uint64_t* rss, uint64_t* hwm) {
  *rss = 0;
  *hwm = 0;
  std::ifstream status("/proc/self/status");
  std::string key;
  while (status >> key) {
    if (key == "VmRSS:") {
      uint64_t v;
      std::string unit;
      status >> v >> unit;
      *rss = v * 1024;
    } else if (key == "VmHWM:") {
      uint64_t v;
      std::string unit;
      status >> v >> unit;
      *hwm = v * 1024;
    } else {
      std::string rest;
      std::getline(status, rest);
    }
  }
}

std::string Arg(const std::vector<std::string>& args, const std::string& flag,
                const std::string& dflt = "") {
  for (size_t i = 0; i + 1 < args.size(); ++i) {
    if (args[i] == flag) return args[i + 1];
  }
  return dflt;
}

bool Has(const std::vector<std::string>& args, const std::string& flag) {
  for (const auto& a : args) {
    if (a == flag) return true;
  }
  return false;
}

std::vector<double> ParseCsv(const std::string& csv) {
  std::vector<double> out;
  std::stringstream ss(csv);
  std::string item;
  while (std::getline(ss, item, ',')) {
    out.push_back(std::stod(item));
  }
  return out;
}

void Warmup() {
  // Named like the target: naming-related lazy initialization must not be
  // first encountered inside the measured timer.
  math_opt::Model m("warmup");
  const math_opt::Variable x =
      m.AddVariable(0.0, 1.0, /*is_integer=*/false, "x[0]");
  const math_opt::Variable y =
      m.AddVariable(0.0, 1.0, /*is_integer=*/false, "x[1]");
  m.AddLinearConstraint(x + y <= 1.0, "row[0]");
  m.Minimize(x);
}

}  // namespace

int main(int argc, char** argv) {
  const std::vector<std::string> args(argv + 1, argv + argc);
  const std::string workload = Arg(args, "--workload");
  const int64_t size = std::stoll(Arg(args, "--size", "0"));
  const int64_t seed = std::stoll(Arg(args, "--seed", "0"));
  const int64_t replicate = std::stoll(Arg(args, "--replicate", "0"));
  const std::string run_id = Arg(args, "--run-id");
  const std::string benchmark_sha = Arg(args, "--benchmark-sha");
  const std::string roml_sha = Arg(args, "--roml-sha");
  const std::string timestamp = Arg(args, "--timestamp-utc");
  const std::string cpu_str = Arg(args, "--cpu");
  const std::string implementation =
      Arg(args, "--implementation", "ortools_mathopt_cpp");
  const bool do_solve = Has(args, "--solve");

  Warmup();

  // Canonical data parsing happens before every timer.
  std::vector<double> prices;
  if (workload == "bess_96") {
    const std::string csv = Arg(args, "--prices-csv");
    if (csv.empty()) {
      std::cerr << "bess_96 requires --prices-csv\n";
      return 2;
    }
    prices = ParseCsv(csv);
    if ((int)prices.size() != kBessT) {
      std::cerr << "prices-csv has wrong length\n";
      return 2;
    }
  }

  // container_init measures only fresh Model() construction.
  const int64_t t_init = NowNs();
  math_opt::Model model("bench");
  const int64_t container_init_ns = NowNs() - t_init;
  uint64_t rss_before = 0, unused = 0;
  ReadRss(&rss_before, &unused);

  int64_t nvars = 0, ncons = 0, nnz = 0, onnz = 0;
  int64_t t_vars = 0, t_cons = 0, t_obj = 0;
  double objective_value = 0.0;
  bool solved = false;

  if (workload == "sparse_rows") {
    const int64_t n = size;
    const int64_t rows = n / 10;
    int64_t t0 = NowNs();
    std::vector<math_opt::Variable> x;
    x.reserve(n);
    for (int64_t i = 0; i < n; ++i) {
      x.push_back(model.AddVariable(0.0, 5.0, /*is_integer=*/false,
                                    "x[" + std::to_string(i) + "]"));
    }
    t_vars = NowNs() - t0;
    t0 = NowNs();
    for (int64_t r = 0; r < rows; ++r) {
      math_opt::LinearExpression lhs;
      for (int k = 0; k < 10; ++k) lhs += x[10 * r + k];
      model.AddLinearConstraint(lhs <= 10.0, "row[" + std::to_string(r) + "]");
    }
    t_cons = NowNs() - t0;
    t0 = NowNs();
    math_opt::LinearExpression obj;
    for (int64_t i = 0; i < n; ++i) obj += x[i];
    model.Minimize(obj);
    t_obj = NowNs() - t0;
    nvars = n;
    ncons = rows;
    nnz = 10 * rows;
    onnz = n;
    if (do_solve) {
      auto result = math_opt::Solve(model, math_opt::SolverType::kHighs);
      if (!result.ok() || result->solutions.empty() ||
          !result->solutions[0].primal_solution.has_value()) {
        std::cerr << "solve failed\n";
        return 1;
      }
      objective_value = result->solutions[0].primal_solution->objective_value;
      solved = true;
    }
  } else if (workload == "bess_96") {
    const int64_t b = size;
    const int64_t t = kBessT;
    int64_t t0 = NowNs();
    std::vector<math_opt::Variable> charge, discharge, energy;
    charge.reserve(b * t);
    discharge.reserve(b * t);
    energy.reserve(b * (t + 1));
    for (int64_t i = 0; i < b * t; ++i) {
      const int64_t bb = i / t;
      const int64_t tt = i % t;
      charge.push_back(model.AddVariable(
          0.0, kBessP, /*is_integer=*/false,
          "charge[" + std::to_string(bb) + "," + std::to_string(tt) + "]"));
      discharge.push_back(model.AddVariable(
          0.0, kBessP, /*is_integer=*/false,
          "discharge[" + std::to_string(bb) + "," + std::to_string(tt) + "]"));
    }
    for (int64_t i = 0; i < b * (t + 1); ++i) {
      const int64_t bb = i / (t + 1);
      const int64_t tt = i % (t + 1);
      energy.push_back(model.AddVariable(
          0.0, kBessE, /*is_integer=*/false,
          "energy[" + std::to_string(bb) + "," + std::to_string(tt) + "]"));
    }
    t_vars = NowNs() - t0;
    t0 = NowNs();
    for (int64_t bb = 0; bb < b; ++bb) {
      model.AddLinearConstraint(energy[bb * (t + 1)] == kBessE0,
                                "init[" + std::to_string(bb) + "]");
      for (int64_t tt = 0; tt < t; ++tt) {
        const auto ch = charge[bb * t + tt];
        const auto di = discharge[bb * t + tt];
        const auto en0 = energy[bb * (t + 1) + tt];
        const auto en1 = energy[bb * (t + 1) + tt + 1];
        const std::string tag =
            "[" + std::to_string(bb) + "," + std::to_string(tt) + "]";
        model.AddLinearConstraint(
            en1 == en0 + kBessDt * (kBessEta * ch - di / kBessEta),
            "balance" + tag);
        model.AddLinearConstraint(ch + di <= kBessP, "mode" + tag);
      }
    }
    t_cons = NowNs() - t0;
    t0 = NowNs();
    // dt scales power to energy per interval, matching the contract objective.
    math_opt::LinearExpression obj;
    for (int64_t bb = 0; bb < b; ++bb) {
      for (int64_t tt = 0; tt < t; ++tt) {
        obj += kBessDt * prices[tt] * (discharge[bb * t + tt] - charge[bb * t + tt]);
      }
    }
    model.Maximize(obj);
    t_obj = NowNs() - t0;
    nvars = b * (3 * t + 1);
    ncons = b * (2 * t + 1);
    nnz = b * (1 + 6 * t);
    onnz = b * (2 * t);
    if (do_solve) {
      auto result = math_opt::Solve(model, math_opt::SolverType::kHighs);
      if (!result.ok() || result->solutions.empty() ||
          !result->solutions[0].primal_solution.has_value()) {
        std::cerr << "solve failed\n";
        return 1;
      }
      objective_value = result->solutions[0].primal_solution->objective_value;
      solved = true;
    }
  } else {
    std::cerr << "unknown workload: " << workload << "\n";
    return 2;
  }

  const int64_t populate_ns = t_vars + t_cons + t_obj;
  uint64_t rss_after = 0, peak = 0;
  ReadRss(&rss_after, &peak);

  std::printf(
      "{\"schema_version\": 1, \"run_id\": \"%s\", \"timestamp_utc\": \"%s\", "
      "\"benchmark_sha\": \"%s\", \"roml_sha\": \"%s\", \"implementation\": "
      "\"%s\", \"workload\": \"%s\", \"size\": %lld, \"variables\": %lld, "
      "\"constraints\": %lld, \"constraint_nnz\": %lld, \"objective_nnz\": "
      "%lld, \"replicate\": %lld, \"seed\": %lld, \"variant\": \"canonical\", "
      "\"container_init_ns\": %lld, \"populate_ns\": %lld, \"phases\": "
      "{\"variables\": %lld, \"constraints\": %lld, \"objective\": %lld}, "
      "\"rss_before_bytes\": %llu, \"rss_after_bytes\": %llu, "
      "\"peak_rss_bytes\": %llu, \"cpu\": %s, \"status\": \"ok\", \"error\": "
      "null",
      run_id.c_str(), timestamp.c_str(), benchmark_sha.c_str(),
      roml_sha.c_str(), implementation.c_str(), workload.c_str(),
      (long long)size, (long long)nvars, (long long)ncons, (long long)nnz,
      (long long)onnz, (long long)replicate, (long long)seed,
      (long long)container_init_ns, (long long)populate_ns, (long long)t_vars,
      (long long)t_cons, (long long)t_obj, (unsigned long long)rss_before,
      (unsigned long long)rss_after, (unsigned long long)peak,
      cpu_str.empty() ? "null" : cpu_str.c_str());
  if (solved) {
    std::printf(", \"objective_value\": %.17g", objective_value);
  }
  std::printf("}\n");
  return 0;
}
