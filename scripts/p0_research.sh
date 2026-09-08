#!/usr/bin/env bash
# P0 objective research runs (timing + counting).
#
# Timing evidence comes ONLY from roml-bench-core (unmodified build path).
# roml-ops-probe runs the same construction code under a counting allocator;
# its timings are NOT authoritative. Both binaries pin ROML @ $ROML_SHA.
# ROML itself is untouched; all changes live in roml-bench.
set -euo pipefail

cd "$(dirname "$0")/.."

ROML_SHA="6062398b418c4bc0c7718b2ce569da8b9e42766e"
OUT="results/research/p0-objective"
RUN_ID="p0-objective-$(date -u +%Y%m%dT%H%M%SZ)"
BENCH_SHA="$(git rev-parse --short HEAD)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CPU="${P0_CPU:-4}"

mkdir -p "$OUT"
: > "$OUT/timings.jsonl"
: > "$OUT/probes.jsonl"
: > "$OUT/commands.txt"

TIMER="target/release/roml-bench-core"
PROBE="target/release/roml-ops-probe"

cargo build --release -p roml-bench-core --offline 2>&1 | tail -n 1

run_timer() { # workload size mode anonflag replicate
  local workload="$1" size="$2" mode="$3" anon="$4" rep="$5" extra="${6:-}"
  # shellcheck disable=SC2086
  taskset -c "$CPU" "$TIMER" \
    --workload "$workload" --size "$size" --seed 20260908 \
    --replicate "$rep" --run-id "$RUN_ID" --benchmark-sha "$BENCH_SHA" \
    --roml-sha "$ROML_SHA" --timestamp-utc "$TS" \
    --implementation "$anon" --phase-breakdown \
    --objective-mode "$mode" $extra >> "$OUT/timings.jsonl"
  echo "timer $workload $size $mode $anon rep=$rep" | tee -a "$OUT/commands.txt"
}

run_probe() { # workload size mode anonflag extra
  local workload="$1" size="$2" mode="$3" anon="$4" extra="${5:-}"
  local anonflag=""
  [ "$anon" = "anon" ] && anonflag="--anonymous"
  # shellcheck disable=SC2086
  taskset -c "$CPU" "$PROBE" \
    --workload "$workload" --size "$size" --seed 20260908 \
    --replicate 0 --run-id "$RUN_ID" --benchmark-sha "$BENCH_SHA" \
    --roml-sha "$ROML_SHA" --timestamp-utc "$TS" \
    $anonflag --objective-mode "$mode" $extra >> "$OUT/probes.jsonl"
  echo "probe $workload $size $mode $anon" | tee -a "$OUT/commands.txt"
}

PRICES_96="$(python3 -c "
import numpy as np
rng = np.random.default_rng(20260908)
print(','.join(repr(float(v)) for v in (20.0 + 60.0*rng.random(96)).tolist()))
")"

echo "== sparse 1M constant named x3 (timing) =="
for rep in 0 1 2; do
  run_timer sparse_rows 1000000 constant roml_core_rust "$rep"
done

echo "== sparse 100k constant/parameterized x5 (timing) =="
for rep in 0 1 2 3 4; do
  run_timer sparse_rows 100000 constant roml_core_rust "$rep"
  run_timer sparse_rows 100000 parameterized roml_core_rust "$rep"
done

echo "== sparse 1M anon x1 + bess_96 300 x1 (context timing) =="
run_timer sparse_rows 1000000 constant roml_core_rust_anon 0
run_timer bess_96 300 constant roml_core_rust 0 "--prices-csv $PRICES_96"

echo "== counting probes (not authoritative for latency) =="
run_probe sparse_rows 1000000 constant named
run_probe sparse_rows 100000 constant named
run_probe sparse_rows 100000 parameterized named

python3 - "$OUT" "$RUN_ID" "$CPU" "$BENCH_SHA" <<'EOF'
import json, platform, subprocess, sys
out, run_id, cpu_pin, bench_sha = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None
cpu = next((l.split(":",1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), None)
mem = next((l.strip() for l in open("/proc/meminfo") if l.startswith("MemTotal")), None)
env = {
    "run_id": run_id,
    "bench_sha": bench_sha,
    "roml_sha": "6062398b418c4bc0c7718b2ce569da8b9e42766e",
    "rustc": sh(["rustc", "--version"]),
    "cargo": sh(["cargo", "--version"]),
    "cpu_model": cpu,
    "mem_total": mem,
    "kernel": platform.release(),
    "pinned_cpu": cpu_pin,
    "build": "cargo build --release -p roml-bench-core --offline",
    "note": "timings: roml-bench-core (clean). probes: roml-ops-probe (counting allocator; timings non-authoritative).",
}
json.dump(env, open(f"{out}/environment.json", "w"), indent=2)
EOF

echo "wrote $OUT/timings.jsonl $OUT/probes.jsonl $OUT/environment.json"
wc -l "$OUT/timings.jsonl" "$OUT/probes.jsonl"
