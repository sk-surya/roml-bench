#!/usr/bin/env bash
# Build the MathOpt C++ benchmark runner against the pinned OR-Tools
# checkout in ../../.cache/or-tools-v9.15 (v9.15, minimal MathOpt+HiGHS
# configuration; see that directory's cmake invocation history).
#
# Link notes (pinned toolchain behavior, recorded here rather than
# discovered again):
# - Canonical OR-Tools defines are required:
#   -DOR_PROTO_DLL="" -DPROTOBUF_USE_DLLS -DUSE_HIGHS -DUSE_MATH_OPT
# - libortools.so leaves Gurobi/GLOP solver symbols unresolved (those
#   solver backends are disabled in our minimal build and this benchmark
#   hardcodes SolverType::kHighs, so they can never be reached):
#   -Wl,--unresolved-symbols=ignore-in-shared-libs scopes the allowance
#   to shared-library symbols only; our own objects stay strict.
set -euo pipefail
cd "$(dirname "$0")"

OT=../.cache/or-tools-v9.15
if [ ! -f "$OT/build/lib/libortools.so" ]; then
  echo "error: $OT/build/lib/libortools.so missing;" >&2
  echo "configure and build the pinned OR-Tools checkout first (see cpp/README.md)." >&2
  exit 1
fi
LIBS=$(ls "$OT/build/lib/"*.so | grep -v '\.so\.' | sed 's/.*lib/-l/;s/\.so$//' | tr '\n' ' ')
# shellcheck disable=SC2086
g++ -O2 -std=c++17 -fPIC -fwrapv \
  -DOR_PROTO_DLL="" -DPROTOBUF_USE_DLLS -DUSE_HIGHS -DUSE_MATH_OPT \
  -o build/mathopt_bench \
  -I"$OT" -I"$OT/build" \
  -isystem "$OT/build/_deps/protobuf-src/src" \
  -isystem "$OT/build/_deps/absl-src" \
  -isystem "$OT/build/_deps/protobuf-src/third_party/utf8_range" \
  -isystem "$OT/build/_deps/eigen3-src" \
  -isystem "$OT/build/_deps/highs-src" \
  -isystem "$OT/build/_deps/re2-src" \
  mathopt_bench.cc \
  -L"$OT/build/lib" -Wl,-rpath,'$ORIGIN/../../.cache/or-tools-v9.15/build/lib' \
  -Wl,--unresolved-symbols=ignore-in-shared-libs $LIBS
echo "built cpp/build/mathopt_bench"
