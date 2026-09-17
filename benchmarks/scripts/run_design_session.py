#!/usr/bin/env python3
"""Multi-turn design session against one llama-server configuration with a simulated agent environment."""

import argparse
import ast
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks/scripts"))
import run as run_mod  # noqa: E402
import run_context_ladder as ladder  # noqa: E402

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sqlite",
            "description": "Выполнить SQL (DDL/DML/PRAGMA) в изолированной in-memory SQLite и вернуть результат или ошибку. Используй для проверки схемы и запросов.",
            "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Сохранить артефакт проектирования (DDL, JSON, markdown) в файл песочницы.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать ранее сохранённый артефакт из песочницы.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc",
            "description": "Вычислить арифметическое выражение (например, оценку объёма хранилища).",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
        },
    },
]

CALC_WHITELIST = {name: getattr(math, name) for name in ("ceil", "floor", "sqrt", "log", "log2", "log10")}
CALC_WHITELIST.update({"abs": abs, "min": min, "max": max, "round": round, "pow": pow})


def calc(expression):
    node = ast.parse(expression, mode="eval")
    for item in ast.walk(node):
        if isinstance(item, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load,
                             ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
                             ast.USub, ast.UAdd, ast.Constant)):
            continue
        if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) and item.value.id == "math":
            continue
        raise ValueError(f"недопустимый элемент выражения: {type(item).__name__}")
    return eval(compile(node, "<calc>", "eval"), {"__builtins__": {}, "math": math, **CALC_WHITELIST})


def tool_run_sqlite(args, _ctx):
    sql = args.get("sql", "")
    try:
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        statements = [s for s in re.split(r";\s*\n", sql) if s.strip()]
        outputs = []
        for statement in statements:
            cursor.execute(statement)
            if cursor.description:
                rows = cursor.fetchmany(50)
                outputs.append(" | ".join(c[0] for c in cursor.description) + "\n" + "\n".join(" | ".join(str(v) for v in row) for row in rows))
            else:
                outputs.append(f"OK ({cursor.rowcount if cursor.rowcount >= 0 else 0} rows)")
        conn.commit()
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        conn.close()
        return "Выполнено успешно. Таблицы: " + ", ".join(tables) + "\n" + "\n".join(outputs[:20])
    except Exception as exc:  # noqa: BLE001
        return f"SQL ERROR: {exc}"


def tool_write_file(args, ctx):
    path = args.get("path", "artifact.txt")
    content = args.get("content", "")
    sandbox = ctx["artifacts"] / Path(path).name
    sandbox.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"Сохранено: {sandbox.name} ({len(content.encode())} байт, sha256:{digest})"


def tool_read_file(args, ctx):
    path = args.get("path", "")
    sandbox = ctx["artifacts"] / Path(path).name
    if not sandbox.exists():
        return f"Файл не найден: {sandbox.name}"
    return sandbox.read_text(encoding="utf-8")[:8000]


def tool_calc(args, _ctx):
    expression = args.get("expression", "0")
    try:
        return f"{expression} = {calc(expression)}"
    except Exception as exc:  # noqa: BLE001
        return f"CALC ERROR: {exc}"


HANDLERS = {"run_sqlite": tool_run_sqlite, "write_file": tool_write_file, "read_file": tool_read_file, "calc": tool_calc}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--tool-rounds", type=int, default=8)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "benchmarks/results")
    args = parser.parse_args()

    profile = json.loads((args.profile if args.profile.is_absolute() else ROOT / args.profile).read_text())
    variant = profile["profiles"][args.variant]
    port = args.port or variant["port"]
    base_url = f"http://127.0.0.1:{port}"
    script = json.loads((args.script if args.script.is_absolute() else ROOT / args.script).read_text())

    metadata = run_mod.build_variant_metadata(profile)
    run_id = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{profile['name']}-{args.label}"
    result_dir = args.results_dir / run_id
    artifacts = result_dir / "artifacts"
    result_dir.mkdir(parents=True, exist_ok=False)
    artifacts.mkdir()
    command, environment = run_mod.command_for(profile, variant, port)
    (result_dir / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    (result_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    (result_dir / "build-variant.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (result_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n")
    (result_dir / "tools.json").write_text(json.dumps(TOOLS, ensure_ascii=False, indent=2) + "\n")

    telemetry = subprocess.Popen(
        [sys.executable, str(ROOT / "benchmarks/scripts/host_telemetry.py"), str(result_dir / "host-telemetry.csv"), "0.5"]
    )
    log_path = result_dir / "server.log"
    transcript_path = result_dir / "transcript.jsonl"
    dialogue_path = result_dir / "dialogue.md"
    ctx = {"artifacts": artifacts}
    events = []
    api_calls = []
    conversation = [{"role": "system", "content": script["system"]}]
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        with log_path.open("w") as server_log, transcript_path.open("w") as transcript, dialogue_path.open("w") as dialogue:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=server_log, stderr=subprocess.STDOUT)
            dialogue.write("# Сессия проектирования (360k)\n\n**System:** " + script["system"] + "\n\n")
            try:
                run_mod.wait_ready(base_url, process, 900)
                for user_index, user_text in enumerate(script["user"], start=1):
                    conversation.append({"role": "user", "content": user_text})
                    dialogue.write(f"## Пользователь, шаг {user_index}\n\n{user_text}\n\n")
                    transcript.write(json.dumps({"type": "user", "step": user_index, "content": user_text}, ensure_ascii=False) + "\n")
                    for round_index in range(1, args.tool_rounds + 1):
                        offset = log_path.stat().st_size
                        payload = {
                            "model": profile["served_model_name"],
                            "messages": conversation,
                            "max_tokens": args.max_tokens,
                            "temperature": 0.0,
                            "stream": False,
                            "tools": TOOLS,
                            "tool_choice": "auto",
                            "chat_template_kwargs": {"enable_thinking": False},
                        }
                        started = time.perf_counter()
                        started_epoch = time.time()
                        response = run_mod.request_json(f"{base_url}/v1/chat/completions", payload, timeout=7200)
                        ended_epoch = time.time()
                        elapsed = time.perf_counter() - started
                        time.sleep(0.3)
                        with log_path.open() as handle:
                            handle.seek(offset)
                            tasks = ladder.parse_tasks(handle.read())
                        pre = next((t["prompt_eval"] for t in tasks if "prompt_eval" in t), None)
                        gen = next((t["eval"] for t in tasks if "eval" in t), None)
                        acc = next((t["draft_acceptance"] for t in tasks if "draft_acceptance" in t), None)
                        context_tokens = variant["context_tokens"]
                        fill_pct = (100.0 * (response.get("prompt_tokens") or 0) / context_tokens) if context_tokens else None
                        call = {
                            "step": user_index,
                            "round": round_index,
                            "elapsed_s": round(elapsed, 3),
                            "started_epoch": round(started_epoch, 3),
                            "ended_epoch": round(ended_epoch, 3),
                            "context_tokens": context_tokens,
                            "context_fill_pct": round(fill_pct, 2) if fill_pct is not None else None,
                            "prompt_tokens": response.get("prompt_tokens"),
                            "completion_tokens": response.get("completion_tokens"),
                            "evaluated_tokens": pre["tokens"] if pre else None,
                            "prefill_tps": pre["tokens_per_second"] if pre else None,
                            "gen_tps": gen["tokens_per_second"] if gen else None,
                            "accept_mean_len": acc["mean_len"] if acc else None,
                            "content_chars": len(response.get("completion") or ""),
                            "tool_calls": [tc.get("function", {}).get("name") for tc in (response.get("tool_calls") or [])],
                        }
                        api_calls.append(call)
                        print(f"[{user_index}.{round_index}] prompt={call['prompt_tokens']} eval={call['evaluated_tokens']} "
                              f"prefill={call['prefill_tps']} gen={call['gen_tps']} acc={call['accept_mean_len']} "
                              f"tools={call['tool_calls']} chars={call['content_chars']} "
                              f"ctx={call['context_fill_pct']}%")
                        dialogue.write(
                            f"> Метрики сообщения {user_index}.{round_index}: prompt={call['prompt_tokens']} "
                            f"(контекст заполнен {call['context_fill_pct']}%), пересчитано={call['evaluated_tokens']}, "
                            f"prefill={call['prefill_tps']} tok/s, генерация={call['gen_tps']} tok/s, "
                            f"draft mean len={call['accept_mean_len']}, время={call['elapsed_s']} с\n\n"
                        )
                        if response.get("tool_calls"):
                            assistant = {"role": "assistant", "content": response.get("completion") or "",
                                         "tool_calls": response["tool_calls"]}
                            conversation.append(assistant)
                            transcript.write(json.dumps({"type": "assistant_tool_calls", "step": user_index,
                                                         "tool_calls": response["tool_calls"]}, ensure_ascii=False) + "\n")
                            dialogue.write("**Ассистент (вызов инструментов):**\n\n```json\n"
                                           + json.dumps(response["tool_calls"], ensure_ascii=False, indent=2)[:4000] + "\n```\n\n")
                            for tool_call in response["tool_calls"]:
                                name = tool_call.get("function", {}).get("name")
                                raw_args = tool_call.get("function", {}).get("arguments") or "{}"
                                try:
                                    tool_args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    tool_args = {}
                                handler = HANDLERS.get(name)
                                result = "неизвестный инструмент" if handler is None else str(handler(tool_args, ctx))
                                conversation.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": result})
                                transcript.write(json.dumps({"type": "tool_result", "step": user_index, "name": name,
                                                             "arguments": tool_args, "result": result}, ensure_ascii=False) + "\n")
                                dialogue.write(f"**Инструмент `{name}`** → \n\n```\n{result[:2000]}\n```\n\n")
                            continue
                        content = response.get("completion") or ""
                        conversation.append({"role": "assistant", "content": content})
                        transcript.write(json.dumps({"type": "assistant", "step": user_index, "content": content}, ensure_ascii=False) + "\n")
                        dialogue.write(f"**Ассистент:**\n\n{content}\n\n")
                        break
            finally:
                run_mod.stop_process(process)
    finally:
        telemetry.terminate()
        try:
            telemetry.wait(timeout=10)
        except subprocess.TimeoutExpired:
            telemetry.kill()

    (result_dir / "metrics.json").write_text(json.dumps({"run_id": run_id, "started_at": started_at,
                                                         "calls": api_calls}, ensure_ascii=False, indent=2) + "\n")
    import csv
    with (result_dir / "messages.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["call", "step", "round", "started_epoch", "ended_epoch", "elapsed_s", "prompt_tokens",
                         "context_fill_pct", "evaluated_tokens", "prefill_tps", "gen_tps", "accept_mean_len",
                         "completion_tokens", "tools"])
        for index, call in enumerate(api_calls, start=1):
            writer.writerow([index, call["step"], call["round"], call["started_epoch"], call["ended_epoch"],
                             call["elapsed_s"], call["prompt_tokens"], call["context_fill_pct"],
                             call["evaluated_tokens"], call["prefill_tps"], call["gen_tps"],
                             call["accept_mean_len"], call["completion_tokens"],
                             ",".join(call["tool_calls"])])
    print(f"Results: {result_dir}")


if __name__ == "__main__":
    main()
