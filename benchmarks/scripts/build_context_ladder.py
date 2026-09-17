#!/usr/bin/env python3
"""Build the context-ladder prompt document and verify token counts via llama-server /tokenize."""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIRS = ["internal", "cmd", "webUI/src", "benchmarks/scripts", "run-commands", "services"]
SUFFIXES = {".go", ".svelte", ".js", ".py", ".sh", ".json", ".md", ".css", ".html"}


def gather_corpus():
    chunks = []
    for rel in CORPUS_DIRS:
        base = ROOT / rel
        if not base.exists():
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
            chunks.append(f"### FILE: {path.relative_to(ROOT)} ###\n{text}\n")
    return "\n".join(chunks)


def tokenize(base_url, api_key, content):
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{base_url}/tokenize",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        return len(json.load(response)["tokens"])


def build_target(base_url, api_key, corpus, target_tokens, instruction):
    low, high = 0, len(corpus)
    best = corpus
    for _ in range(12):
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
        if high - low <= 256:
            break
    # fine trim / extend by lines
    while True:
        count = tokenize(base_url, api_key, best)
        if count <= target_tokens or len(best) < 200:
            break
        best = best[:-256]
    return best, tokenize(base_url, api_key, best)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--api-key", default="sk-0123456789")
    parser.add_argument("--targets", default="10000,75000")
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks/prompts/context-ladder.json")
    args = parser.parse_args()

    corpus = gather_corpus()
    print(f"corpus chars: {len(corpus)}")

    instruction = (
        "Прочитай следующий текст из репозитория проекта. "
        "Затем ответь кратко (до 64 токенов): перечисли первые три имени файлов, "
        "которые встречаются в тексте, и назови общее число строк в файле, "
        "который упомянут первым."
    )
    cases = [
        {
            "id": "hello",
            "messages": [{"role": "user", "content": "Привет"}],
            "max_tokens": 64,
        }
    ]
    for target in [int(x) for x in args.targets.split(",")]:
        text, count = build_target(args.base_url, args.api_key, corpus, target, instruction)
        case_id = f"context-{target // 1000}k"
        cases.append(
            {
                "id": case_id,
                "messages": [{"role": "user", "content": text}],
                "max_tokens": 128,
                "target_tokens": target,
                "actual_tokens": count,
            }
        )
        print(f"{case_id}: requested {target}, actual {count}, chars {len(text)}")

    args.out.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
