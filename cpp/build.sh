#!/usr/bin/env bash
# Build the MathOpt C++ benchmark runner against the pinned OR-Tools
# checkout in ../../.cache/or-tools-v9.15 (v9.15, minimal MathOpt+HiGHS
# configuration; see that directory's cmake invocation history).
#
# Disabled-backend stubs: libortools.so references three Gurobi/GLOP solver
# symbols even when those backends are configured OFF. Our runner hardcodes
# SolverType::kHighs and can never reach them, so cpp/solver_stubs.cc
# provides abort-if-called definitions solely to complete the link graph.
# Strict linking is intentional: the binary must pass ldd -r with no
# undefined symbols and execute under LD_BIND_NOW=1.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p build

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
  mathopt_bench.cc solver_stubs.cc \
  -L"$OT/build/lib" -Wl,-rpath,'$ORIGIN/../../.cache/or-tools-v9.15/build/lib' \
  $LIBS
echo "built cpp/build/mathopt_bench"
