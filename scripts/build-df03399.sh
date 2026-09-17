#!/usr/bin/env bash
# Build llama.cpp for this case from a pinned upstream commit.
#
# Usage: build-df03399.sh <mode> [build-dir] [src-dir]
#   mode = baseline | dp2a | no-fmad
#     baseline - unmodified upstream at df03399 (DP4A, fmad default)
#     dp2a     - ported PR #25834 patch (GGML_CUDA_DISABLE_DP4A=ON)
#     no-fmad  - dp2a plus nvcc -fmad=false (the adopted runtime; default)
#
# Requires: git, cmake >= 3.20, CUDA toolkit 12.x with nvcc, gcc, and about
# 10 GB free disk + 16 GB RAM during the build. The script builds only the
# llama-server target and uses a systemd memory guard when available.
set -euo pipefail

MODE="${1:-no-fmad}"
BUILD_DIR="${2:-/tmp/llama-df03399-${MODE}-build}"
SRC_DIR="${3:-/tmp/llama-df03399-${MODE}-src}"
COMMIT="df03399b885831b2a1603b3abb0d8c156808e363"
REPO_URL="https://github.com/ggml-org/llama.cpp.git"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$SCRIPT_DIR/../patches/25834-df03399-port.patch"

case "$MODE" in
  baseline|dp2a|no-fmad) ;;
  *) printf 'mode must be baseline | dp2a | no-fmad\n' >&2; exit 2;;
esac

# 1. Fetch the pinned commit into a fresh source directory.
if [[ ! -d "$SRC_DIR/.git" ]]; then
  mkdir -p "$SRC_DIR"
  git -C "$SRC_DIR" init -q
  git -C "$SRC_DIR" remote add origin "$REPO_URL" 2>/dev/null || git -C "$SRC_DIR" remote set-url origin "$REPO_URL"
  git -C "$SRC_DIR" fetch --depth 1 origin "$COMMIT"
  git -C "$SRC_DIR" checkout -q FETCH_HEAD
else
  printf 'Reusing existing source at %s\n' "$SRC_DIR"
fi

# 2. Apply the ported DP2A patch when needed.
if [[ "$MODE" != "baseline" ]]; then
  if git -C "$SRC_DIR" apply --check "$PATCH" 2>/dev/null; then
    git -C "$SRC_DIR" apply "$PATCH"
    printf 'Applied %s\n' "$PATCH"
  else
    printf 'Patch already applied or does not apply cleanly; check %s\n' "$SRC_DIR" >&2
  fi
fi

# 3. Configure. NCCL is optional; it was measured neutral on this topology.
CMAKE_FLAGS=(
  -DGGML_CUDA=ON
  -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_CUDA_ARCHITECTURES=75
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON
)
if [[ "$MODE" != "baseline" ]]; then
  CMAKE_FLAGS+=(-DGGML_CUDA_DISABLE_DP4A=ON)
fi
if [[ "$MODE" == "no-fmad" ]]; then
  CMAKE_FLAGS+=(-DCMAKE_CUDA_FLAGS=-fmad=false)
fi
if ldconfig -p 2>/dev/null | grep -q libnccl; then
  CMAKE_FLAGS+=(-DGGML_CUDA_NCCL=ON)
fi

cmake -S "$SRC_DIR" -B "$BUILD_DIR" "${CMAKE_FLAGS[@]}"

if [[ "$MODE" == "no-fmad" ]]; then
  FLAGS_FILE="$BUILD_DIR/ggml/src/ggml-cuda/CMakeFiles/ggml-cuda.dir/flags.make"
  if [[ -f "$FLAGS_FILE" ]] && ! grep -q -- '-fmad=false' "$FLAGS_FILE"; then
    printf 'ERROR: -fmad=false is not in the CUDA flags; check the toolkit.\n' >&2
    exit 1
  fi
  printf 'Verified: -fmad=false is present in CUDA compile flags.\n'
fi

# 4. Build under a memory guard when possible (about 4 GiB peak for this target).
if command -v systemd-run >/dev/null 2>&1; then
  systemd-run --user --wait --collect --property=MemoryMax=16G --property=MemorySwapMax=0 \
    --pipe cmake --build "$BUILD_DIR" --target llama-server --parallel 12
else
  cmake --build "$BUILD_DIR" --target llama-server --parallel 12
fi

printf '\nRuntime: %s/bin/llama-server\n' "$BUILD_DIR"
"$BUILD_DIR/bin/llama-server" --version | head -2
printf 'Copy %s/bin to llama.cpp/runtime (adopted mode) or use LLAMA_SERVER=<path>.\n' "$BUILD_DIR"
