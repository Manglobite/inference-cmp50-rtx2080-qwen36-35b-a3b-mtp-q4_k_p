#!/usr/bin/env bash
# Download the prebuilt llama.cpp runtime (DP2A + -fmad=false) from GitHub
# Releases and unpack it into llama.cpp/runtime/.
#
# Usage: fetch-runtime.sh [asset-url] [sha256]
# Defaults point at the case repository release v1.0.0.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

URL="${1:-https://github.com/Manglobite/inference-cmp50-rtx2080-qwen36-35b-a3b-mtp-q4_k_p/releases/download/v1.0.0/runtime-no-fmad.tar.zst}"
SHA256="${2:-5c0371d41746ea8e3cdff1a7e7101b4f579e49d140838ef01fa393e8e462dd57}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading $URL"
curl -L --fail -C - -o "$TMP/runtime.tar.zst" "$URL"

echo "Verifying SHA-256"
echo "$SHA256  $TMP/runtime.tar.zst" | sha256sum -c -

mkdir -p "$ROOT_DIR"
tar --zstd -xf "$TMP/runtime.tar.zst" -C "$ROOT_DIR"

if [[ -x "$ROOT_DIR/llama.cpp/runtime/bin/llama-server" ]]; then
  echo "Runtime ready:"
  "$ROOT_DIR/llama.cpp/runtime/bin/llama-server" --version | head -2
else
  echo "Unexpected archive layout; expected llama.cpp/runtime/bin/llama-server" >&2
  exit 1
fi
