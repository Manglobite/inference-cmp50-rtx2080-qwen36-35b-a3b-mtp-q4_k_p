#!/usr/bin/env bash
# Fail if backend/private markers appear in tracked files or anywhere in git
# history. Run before every push to a public remote.
set -euo pipefail

cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

PATTERNS='package api|package service|internal/api/|internal/service/|internal/model/|internal/store/|webUI/src/|/home/manglobite|manglobite|sk-[A-Za-z0-9]{13,}'
EXCL=(':(exclude)llama.cpp/src' ':(exclude)docs/dialogues' ':(exclude)scripts/check-public.sh')

echo "== working tree =="
if hits=$(git grep -lE "$PATTERNS" -- . "${EXCL[@]}"); then
  printf '%s\n' "$hits" >&2
  echo "FAIL: private markers found in the working tree" >&2
  exit 1
fi

echo "== git history =="
if hits=$(git grep -lE "$PATTERNS" $(git rev-list --all) -- . "${EXCL[@]}"); then
  printf '%s\n' "$hits" >&2
  echo "FAIL: private markers found in git history" >&2
  exit 1
fi

echo "OK: no private markers found"
