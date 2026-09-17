#!/usr/bin/env bash
# Qwen3.6-35B-A3B on 2xCMP 50HX + RTX 2080 Ti (all sm_75).
# Adopted profile: RTX is the tail stage, MTP n-max=3, ubatch 448.
# Runtime: patched llama.cpp (DP2A) + nvcc -fmad=false.
#
# Overridable environment: PORT, CTX_SIZE, TENSOR_SPLIT, UBATCH_SIZE,
# BATCH_SIZE, SPEC_N_MAX, DEVICES, LLAMA_SERVER, MODEL, MMPROJ, API_KEY.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

LLAMA_SERVER="${LLAMA_SERVER:-$ROOT_DIR/llama.cpp/runtime/bin/llama-server}"
MODEL="${MODEL:-$ROOT_DIR/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf}"
MMPROJ="${MMPROJ:-$ROOT_DIR/models/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf}"
EXPECTED_MODEL_SIZE=24322493952
EXPECTED_RUNTIME_COMMIT="df03399"

ALIAS="${ALIAS:-qwen3.6-35B-A3B-uncensored-MTP-Q4_K_P}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8085}"
CTX_SIZE="${CTX_SIZE:-262144}"
TENSOR_SPLIT="${TENSOR_SPLIT:-1,1,2.5}"
DEVICES="${DEVICES:-CUDA0,CUDA2,CUDA1}"
BATCH_SIZE="${BATCH_SIZE:-1024}"
UBATCH_SIZE="${UBATCH_SIZE:-448}"
SPEC_N_MAX="${SPEC_N_MAX:-3}"
CACHE_RAM_MIB="${CACHE_RAM_MIB:-8192}"
THREADS="${THREADS:-4}"

if [[ ! -x "$LLAMA_SERVER" ]]; then
  printf 'llama-server not found or not executable: %s\n' "$LLAMA_SERVER" >&2
  printf 'Use the bundled runtime or build one with scripts/build-df03399.sh.\n' >&2
  exit 1
fi

runtime_version="$($LLAMA_SERVER --version 2>&1)"
if [[ "$runtime_version" != *"$EXPECTED_RUNTIME_COMMIT"* ]]; then
  printf 'Warning: llama-server was not built from %s:\n%s\n' "$EXPECTED_RUNTIME_COMMIT" "$runtime_version" >&2
fi

if [[ ! -f "$MODEL" ]]; then
  printf 'Model not found: %s\nSee models/README.md for download instructions.\n' "$MODEL" >&2
  exit 1
fi

model_size="$(stat -c '%s' "$MODEL")"
if [[ "$model_size" -ne "$EXPECTED_MODEL_SIZE" ]]; then
  printf 'Warning: model size is %s, expected %s bytes. Check the SHA-256.\n' "$model_size" "$EXPECTED_MODEL_SIZE" >&2
fi

if command -v ss >/dev/null && ss -ltnH "sport = :$PORT" | read -r _; then
  printf 'Port %s is already in use; set PORT=<port>.\n' "$PORT" >&2
  exit 1
fi

if pgrep -x 'llama-server' >/dev/null; then
  printf 'Another llama-server is already running; stop it first.\n' >&2
  pgrep -ax 'llama-server' >&2 || true
  exit 1
fi

if [[ "$(nvidia-smi --query-gpu=count --format=csv,noheader 2>/dev/null | wc -l)" -lt 3 ]]; then
  printf 'This profile requires three CUDA devices (2xCMP 50HX + RTX 2080 Ti).\n' >&2
  exit 1
fi

# CUDA0/CUDA1/CUDA2 map to CMP 50HX, RTX 2080 Ti, CMP 50HX by PCI bus order.
# DEVICES puts the RTX last (tail) so the output head and the MTP layer stay
# co-located on the RTX; moving the tail back to a CMP costs about 35% decode.
export CUDA_DEVICE_ORDER=PCI_BUS_ID
exec "$LLAMA_SERVER" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  --mmproj-device CUDA1 \
  --image-min-tokens 1024 \
  --jinja \
  -a "$ALIAS" \
  --device "$DEVICES" \
  --split-mode layer \
  --tensor-split "$TENSOR_SPLIT" \
  -ngl all \
  --fit off \
  --kv-offload \
  --flash-attn on \
  --ctx-size "$CTX_SIZE" \
  --parallel 1 \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --batch-size "$BATCH_SIZE" \
  --ubatch-size "$UBATCH_SIZE" \
  --threads "$THREADS" \
  --reasoning on \
  --reasoning-budget -1 \
  --spec-type draft-mtp \
  --spec-draft-n-max "$SPEC_N_MAX" \
  --cache-prompt \
  --slot-prompt-similarity 0.0 \
  --cache-ram "$CACHE_RAM_MIB" \
  --cache-idle-slots \
  --kv-unified \
  --ctx-checkpoints 8 \
  --checkpoint-min-step 8192 \
  --n-predict -1 \
  --timeout 7200 \
  --metrics \
  --cont-batching \
  --host "$HOST" \
  --port "$PORT" \
  ${API_KEY:+--api-key "$API_KEY"}
