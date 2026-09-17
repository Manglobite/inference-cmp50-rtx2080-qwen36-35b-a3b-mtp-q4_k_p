#!/usr/bin/env python3
"""Build prompt documents (context ladder or repository-context) with verified token counts.

Text source is synthetic by default - no project files are read, so the
generated fixtures are safe to publish. Point --corpus-dir at your own text
files to build a domain-specific corpus instead. Token counts are verified
against a running llama-server /tokenize endpoint.

Examples:
  build_context_ladder.py --mode ladder --out prompts/context-ladder.json
  build_context_ladder.py --mode repo   --out prompts/repository-context-synthetic.json
  build_context_ladder.py --mode ladder --corpus-dir /path/to/text --targets 10000,75000
"""

import argparse
import json
import os
import random
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".txt", ".md", ".py", ".go", ".sh", ".json", ".svelte", ".js", ".css", ".html"}

WORDS = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron "
    "pi rho sigma tau upsilon phi chi psi omega channel buffer window packet stream "
    "segment cursor index schema queue worker cache token matrix vector sum range"
).split()

INSTRUCTIONS = {
    "ladder": (
        "Прочитай следующий текст. Затем ответь кратко (до 64 токенов): перечисли "
        "первые три идентификатора блоков, которые встречаются в тексте, и назови "
        "общее число строк."
    ),
    "repo": (
        "You are a precise long-context assistant. Read the text below and answer "
        "briefly (up to 64 tokens): list the first three block identifiers and state "
        "how many blocks the text contains."
    ),
}


def synthetic_corpus(seed=20260917, paragraphs=6000):
    rnd = random.Random(seed)
    lines = []
    for i in range(paragraphs):
        length = rnd.randint(40, 90)
        sentence = " ".join(rnd.choice(WORDS) for _ in range(length))
        lines.append(f"[block {i:05d}] {sentence.capitalize()}.")
        if i % 20 == 19:
            summary = " ".join(rnd.choice(WORDS) for _ in range(30))
            lines.append(f"[section {i // 20:03d}] Summary of blocks {i - 19}-{i}: {summary.capitalize()}.")
    return "\n".join(lines)


def gather_corpus(directories):
    chunks = []
    for directory in directories:
        base = Path(directory)
        if not base.is_absolute():
            base = ROOT / base
        if not base.exists():
            print(f"warning: corpus dir does not exist: {base}", file=sys.stderr)
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            if len(text) < 200:
                continue
            chunks.append(f"===== FILE: {path.name} =====\n{text}\n")
    return "\n".join(chunks) if chunks else synthetic_corpus()


def tokenize(base_url, api_key, content, timeout=300, retries=2):
    body = json.dumps({"content": content}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(f"{base_url}/tokenize", data=body, headers=headers)
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return len(json.load(response)["tokens"])
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt >= retries:
                raise
    raise last


def build_target(base_url, api_key, corpus, target_tokens, instruction):
    low, high = 0, len(corpus)
    best = corpus
    for _ in range(14):
        mid = (low + high) // 2
        text = instruction + "\n" + corpus[:mid]
        count = tokenize(base_url, api_key, text)
        if count < target_tokens:
            low = mid
            best = text
        elif count > target_tokens:
            high = mid
        else:
            return text, count
        if high - low <= 128:
            break
    while True:
        count = tokenize(base_url, api_key, best)
        if count <= target_tokens or len(best) < 200:
            return best, count
        best = best[:-128]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("ladder", "repo"), default="ladder")
    parser.add_argument("--targets", default=None,
                        help="token targets, comma separated (default 10000,75000 for ladder, 8000,16000,28000 for repo)")
    parser.add_argument("--corpus-dir", action="append", default=[],
                        help="directory with your own .txt/.md/.py files; repeatable; default is synthetic text")
    parser.add_argument("--base-url", default=os.environ.get("LLAMA_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "http://127.0.0.1:8085")
    parser.add_argument("--api-key", default=os.environ.get("LLAMA_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    targets_raw = args.targets or ("10000,75000" if args.mode == "ladder" else "8000,16000,28000")
    targets = [int(x) for x in targets_raw.split(",")]
    corpus = gather_corpus(args.corpus_dir) if args.corpus_dir else synthetic_corpus()
    instruction = INSTRUCTIONS[args.mode]
    print(f"mode={args.mode} corpus_chars={len(corpus)} targets={targets}")

    cases = []
    if args.mode == "ladder":
        cases.append({"id": "hello", "messages": [{"role": "user", "content": "Привет"}], "max_tokens": 64})
    for target in targets:
        text, count = build_target(args.base_url, args.api_key, corpus, target, instruction)
        case_id = f"context-{target // 1000}k" if args.mode == "ladder" else f"repo-{target // 1000}k"
        cases.append({
            "id": case_id,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": 128,
            "target_tokens": target,
            "actual_tokens": count,
        })
        print(f"{case_id}: requested {target}, actual {count}, chars {len(text)}")

    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
