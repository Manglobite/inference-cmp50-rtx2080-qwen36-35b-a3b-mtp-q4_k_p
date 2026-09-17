#!/usr/bin/env bash
# Baseline comparison launcher (DP4A, no fmad, RTX in the middle).
# Needs a baseline runtime built with:
#   scripts/build-df03399.sh baseline <build-dir>
# then either copy it to llama.cpp/runtime-baseline/ or point LLAMA_SERVER at it.
# Use this profile to reproduce the A/B numbers in the docs.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

LLAMA_SERVER="${LLAMA_SERVER:-$ROOT_DIR/llama.cpp/runtime-baseline/bin/llama-server}"
MODEL="${MODEL:-$ROOT_DIR/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf}"
MMPROJ="${MMPROJ:-$ROOT_DIR/models/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf}"

PORT="${PORT:-8086}"
CTX_SIZE="${CTX_SIZE:-262144}"
TENSOR_SPLIT="${TENSOR_SPLIT:-1,2.25,1}"
DEVICES="${DEVICES:-CUDA0,CUDA1,CUDA2}"
BATCH_SIZE="${BATCH_SIZE:-1024}"
UBATCH_SIZE="${UBATCH_SIZE:-256}"
SPEC_N_MAX="${SPEC_N_MAX:-1}"
CACHE_RAM_MIB="${CACHE_RAM_MIB:-8192}"
THREADS="${THREADS:-4}"

if [[ ! -x "$LLAMA_SERVER" ]]; then
  printf 'Baseline runtime not found: %s\n' "$LLAMA_SERVER" >&2
  printf 'Build it with: scripts/build-df03399.sh baseline /tmp/llama-baseline\n' >&2
  exit 1
fi
if [[ ! -f "$MODEL" ]]; then
  printf 'Model not found: %s\n' "$MODEL" >&2
  exit 1
fi
if pgrep -x 'llama-server' >/dev/null; then
  printf 'Another llama-server is already running; stop it first.\n' >&2
  exit 1
fi

export CUDA_DEVICE_ORDER=PCI_BUS_ID
exec "$LLAMA_SERVER" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  --mmproj-device CUDA1 \
  --image-min-tokens 1024 \
  --jinja \
  -a "qwen3.6-35B-A3B-uncensored-baseline" \
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
  --host "${HOST:-127.0.0.1}" \
  --port "$PORT"
