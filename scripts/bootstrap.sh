#!/usr/bin/env bash
# Bootstrap the reproducible ROML model-build benchmark environment.
#
# 1. requires Python 3.13 and uv
# 2. uv sync (creates .venv, writes/uses uv.lock)
# 3. clones/fetches sk-surya/roml into .cache/roml, checks out the pinned SHA
# 4. builds the ROML Python extension in release mode with maturin
# 5. installs that wheel into .venv
# 6. verifies `import roml`
# 7. builds rust-core in release mode
# 8. prints exact versions/SHAs
set -euo pipefail

ROML_SHA="c590692ace5446cc20c7eb91cb8fa0d594a054b0"
ROML_REPO="https://github.com/sk-surya/roml.git"

cd "$(dirname "$0")/.."

# The pin must match src/roml_bench/schema.py exactly; two sources of truth
# caused the d6afabd-mislabeled provenance incident.
SCHEMA_SHA="$(grep -o 'ROML_SHA = "[0-9a-f]*"' src/roml_bench/schema.py | grep -o '[0-9a-f]*')"
if [ "$SCHEMA_SHA" != "$ROML_SHA" ]; then
  echo "error: scripts/bootstrap.sh pins $ROML_SHA but schema.py pins $SCHEMA_SHA" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required but not on PATH" >&2
  exit 1
fi

PY313="$(uv python find 3.13 2>/dev/null || true)"
if [ -z "$PY313" ]; then
  echo "error: Python 3.13 not found (uv python find 3.13 failed)" >&2
  exit 1
fi
echo "python3.13: $PY313 ($("$PY313" --version))"

export UV_PROJECT_ENVIRONMENT=".venv"
uv sync

if [ ! -d .cache/roml ]; then
  git clone "$ROML_REPO" .cache/roml
fi
git -C .cache/roml fetch origin
git -C .cache/roml checkout "$ROML_SHA"
ACTUAL_ROML_SHA="$(git -C .cache/roml rev-parse HEAD)"
if [ "$ACTUAL_ROML_SHA" != "$ROML_SHA" ]; then
  echo "error: ROML checkout $ACTUAL_ROML_SHA != pinned $ROML_SHA" >&2
  exit 1
fi

# Build the ROML Python extension (release) with maturin and install into .venv.
uv tool run --python 3.13 --with maturin maturin --version >/dev/null
mkdir -p .cache/wheels
(
  cd .cache/roml
  uv tool run --python 3.13 --with maturin maturin build --release --out ../../.cache/wheels
)
WHEEL="$(ls -t .cache/wheels/roml_python-*.whl 2>/dev/null | head -n 1)"
if [ -z "${WHEEL:-}" ]; then
  echo "error: no built wheel found in .cache/wheels" >&2
  exit 1
fi
VIRTUAL_ENV="$PWD/.venv" uv pip install --python "$PWD/.venv/bin/python" --force-reinstall "$PWD/$WHEEL"

uv run python -c 'import roml; print("roml", roml.__version__)'

cargo build --release --locked -p roml-bench-core -p roml-store-proto

echo "=== provenance ==="
uv run python --version
uv run python -c 'import pulp, pyomo, pyoptinterface; print("pulp", pulp.__version__); import pyomo.version as _pv; print("pyomo", _pv.__version__); print("pyoptinterface", pyoptinterface.__version__)'
cargo --version
rustc --version
echo "benchmark_sha: $(git rev-parse HEAD)"
echo "roml_sha: $ACTUAL_ROML_SHA"
echo "wheel_sha256: $(sha256sum "$WHEEL" | cut -d' ' -f1)  $WHEEL"
uv run python -c 'import roml, pathlib, hashlib; [print("native_ext_sha256:", hashlib.sha256(p.read_bytes()).hexdigest(), p.name) for p in [pathlib.Path(roml.__file__).parent] for p in p.iterdir() if p.suffix == ".so"]'
echo "core_binary_sha256: $(sha256sum target/release/roml-bench-core | cut -d' ' -f1)"
