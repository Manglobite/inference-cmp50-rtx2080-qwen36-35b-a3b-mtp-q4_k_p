#!/usr/bin/env python3
"""Run a scripted multi-request context ladder against one llama-server configuration."""

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks/scripts"))
import run as run_mod  # noqa: E402

TASK_PATTERN = re.compile(
    r"id\s+(?P<slot>\d+)\s+\|\s+task\s+(?P<task>\d+)\s+\|\s+"
    r"(?P<kind>prompt eval time|eval time|total time|n_decoded|draft acceptance)\s*=\s*(?P<values>.*)"
)
PEVAL_PATTERN = re.compile(
    r"(?P<milliseconds>[\d.]+) ms /\s*(?P<tokens>\d+) tokens \([^,]+,\s*(?P<tokens_per_second>[\d.]+) tokens per second\)"
)
TOTAL_PATTERN = re.compile(r"(?P<milliseconds>[\d.]+) ms /\s*(?P<tokens>\d+) tokens")
TG_PATTERN = re.compile(
    r"(?P<decoded>\d+), tg =\s*(?P<tokens_per_second>[\d.]+) t/s, tg_3s =\s*(?P<tokens_per_second_3s>[\d.]+) t/s"
)
ACC_PATTERN = re.compile(
    r"(?P<acceptance>[\d.]+) \(\s*(?P<accepted>\d+) accepted /\s*(?P<generated>\d+) generated\), mean len =\s*(?P<mean_len>[\d.]+)"
)


def parse_tasks(text):
    tasks = {}
    for line in text.splitlines():
        match = TASK_PATTERN.search(line)
        if not match:
            continue
        task_id = match.group("task")
        task = tasks.setdefault(task_id, {"task_id": int(task_id), "slot_id": int(match.group("slot"))})
        kind = match.group("kind")
        values = match.group("values")
        if kind in ("prompt eval time", "eval time"):
            entry = PEVAL_PATTERN.search(values)
            if entry:
                task["prompt_eval" if kind == "prompt eval time" else "eval"] = {
                    "milliseconds": float(entry.group("milliseconds")),
                    "tokens": int(entry.group("tokens")),
                    "tokens_per_second": float(entry.group("tokens_per_second")),
                }
        elif kind == "total time":
            entry = TOTAL_PATTERN.search(values)
            if entry:
                task["total"] = {
                    "milliseconds": float(entry.group("milliseconds")),
                    "tokens": int(entry.group("tokens")),
                }
        elif kind == "n_decoded":
            entry = TG_PATTERN.search(values)
            if entry:
                task["tg"] = {
                    "decoded_tokens": int(entry.group("decoded")),
                    "tokens_per_second": float(entry.group("tokens_per_second")),
                }
        else:
            entry = ACC_PATTERN.search(values)
            if entry:
                task["draft_acceptance"] = {
                    "acceptance": float(entry.group("acceptance")),
                    "accepted": int(entry.group("accepted")),
                    "generated": int(entry.group("generated")),
                    "mean_len": float(entry.group("mean_len")),
                }
    return [tasks[key] for key in sorted(tasks, key=int)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--variant", default=None)
    parser.add_argument("--steps", required=True, type=Path)
    parser.add_argument("--prompts", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "benchmarks/results")
    run_mod.add_endpoint_args(parser)
    parser.add_argument("--no-telemetry", action="store_true")
    args = parser.parse_args()

    base_url_override, api_key, model_override = run_mod.resolve_endpoint(args)
    attach = args.attach or base_url_override is not None

    profile = None
    build_metadata = {"build_variant": None, "binary_path": None, "binary_sha256": None,
                      "manifest_path": None, "manifest_sha256": None}
    command, environment = [], {}
    context_tokens = None
    if args.profile is not None:
        profile_path = args.profile if args.profile.is_absolute() else ROOT / args.profile
        profile = json.loads(profile_path.read_text())
        if args.variant not in profile["profiles"]:
            raise SystemExit(f"unknown variant {args.variant!r}")
        variant = profile["profiles"][args.variant]
        build_metadata = run_mod.build_variant_metadata(profile)
        served_model = model_override or profile["served_model_name"]
        context_tokens = variant["context_tokens"]
        port = args.port or variant["port"]
        if attach:
            base_url = base_url_override or f"http://127.0.0.1:{port}"
        else:
            base_url = f"http://127.0.0.1:{port}"
            command, environment = run_mod.command_for(profile, variant, port)
        variant_name = args.variant
    else:
        if not attach:
            raise SystemExit("provide --profile (managed) or --attach --model M --base-url URL")
        if not model_override:
            raise SystemExit("--model (or LLAMA_MODEL) is required in attach mode")
        base_url = base_url_override or "http://127.0.0.1:8080"
        served_model = model_override
        variant_name = "attach"

    steps_doc = json.loads((args.steps if args.steps.is_absolute() else ROOT / args.steps).read_text())
    prompts_path = args.prompts if args.prompts.is_absolute() else ROOT / args.prompts
    prompts = {case["id"]: case for case in json.loads(prompts_path.read_text())["cases"]}

    run_id = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{served_model}-{args.label}"
    result_dir = args.results_dir / run_id
    result_dir.mkdir(parents=True, exist_ok=False)
    if profile is not None:
        (result_dir / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    if command:
        (result_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    (result_dir / "build-variant.json").write_text(json.dumps(build_metadata, indent=2) + "\n")
    if environment:
        (result_dir / "gpu-binding.json").write_text(json.dumps({
            "cuda_device_order": environment.get("CUDA_DEVICE_ORDER"),
            "cuda_visible_devices": environment.get("CUDA_VISIBLE_DEVICES"),
            "llama_device": profile["gpu"].get("llama_device") if profile else None,
        }, indent=2) + "\n")
    (result_dir / "steps.json").write_text(json.dumps(steps_doc, indent=2) + "\n")

    telemetry = None
    if not attach and not args.no_telemetry and shutil.which("nvidia-smi"):
        telemetry = subprocess.Popen(
            [sys.executable, str(ROOT / "benchmarks/scripts/host_telemetry.py"), str(result_dir / "host-telemetry.csv"), "0.5"]
        )
    log_path = result_dir / "server.log"
    results = []
    status = "ok"
    error = None
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    process = None
    try:
        if attach:
            print(f"Attaching to {base_url} (model {served_model})")
        else:
            server_log = log_path.open("w")
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=server_log, stderr=subprocess.STDOUT)
            try:
                run_mod.wait_ready(base_url, process, 900)
            finally:
                server_log.close()
        for index, step in enumerate(steps_doc["steps"], start=1):
            case = prompts[step["case"]]
            max_tokens = step.get("max_tokens", case.get("max_tokens", 128))
            offset = log_path.stat().st_size if log_path.exists() else 0
            payload = {
                "model": served_model,
                "messages": case["messages"],
                "max_tokens": max_tokens,
                "temperature": 0.0,
                "stream": False,
            }
            started = time.perf_counter()
            response = run_mod.request_json(f"{base_url}/v1/chat/completions", payload,
                                            timeout=7200, api_key=api_key, retries=args.retries)
            elapsed = time.perf_counter() - started
            time.sleep(0.2)
            normalized = run_mod.normalize_timings(response.get("timings"))
            if normalized is not None:
                tasks = [normalized]
            else:
                with log_path.open() as handle:
                    handle.seek(offset)
                    tasks = parse_tasks(handle.read())
            prefill = next((t["prompt_eval"] for t in tasks if "prompt_eval" in t), None)
            generation = next((t["eval"] for t in tasks if "eval" in t), None)
            acceptance = next((t["draft_acceptance"] for t in tasks if "draft_acceptance" in t), None)
            evaluated = prefill["tokens"] if prefill else None
            prompt_total = response.get("prompt_tokens")
            cache_fraction = next((t["cache_hit_fraction"] for t in tasks if t.get("cache_hit_fraction") is not None), None)
            if cache_fraction is None and evaluated is not None and prompt_total:
                cache_fraction = max(0.0, 1.0 - evaluated / prompt_total)
            entry = {
                "step": index,
                "session": step.get("session", "A"),
                "case": step["case"],
                "elapsed_s": round(elapsed, 3),
                "prompt_tokens": prompt_total,
                "evaluated_tokens": evaluated,
                "cache_hit_fraction": round(cache_fraction, 4) if cache_fraction is not None else None,
                "completion_tokens": response.get("completion_tokens"),
                "finish_reason": response.get("finish_reason"),
                "wall_tokens_per_second": round(response.get("tokens_per_second") or 0, 3),
                "context_tokens": context_tokens,
                "context_fill_pct": round(100.0 * (prompt_total or 0) / context_tokens, 3) if context_tokens else None,
                "completion": (response.get("completion") or "")[:200],
                "tasks": tasks,
                "timings": response.get("timings") or {},
            }
            results.append(entry)
            prefill_rate = prefill["tokens_per_second"] if prefill else None
            generation_rate = generation["tokens_per_second"] if generation else None
            mean_len = acceptance["mean_len"] if acceptance else None
            print(f"[{index}] {entry['session']} {entry['case']}: prompt={prompt_total} "
                  f"evaluated={evaluated} cache={entry['cache_hit_fraction']} "
                  f"prefill={prefill_rate} tok/s gen={generation_rate} tok/s accept={mean_len}")
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = str(exc)
        (result_dir / "result.json").write_text(json.dumps({
            "run_id": run_id, "status": "failed", "error": str(exc),
            "base_url": base_url, "model": served_model, "label": args.label,
        }, ensure_ascii=False, indent=2) + "\n")
        raise
    finally:
        if process is not None:
            run_mod.stop_process(process)
        if telemetry is not None:
            telemetry.terminate()
            try:
                telemetry.wait(timeout=10)
            except subprocess.TimeoutExpired:
                telemetry.kill()

    report = {
        "run_id": run_id,
        "started_at": started_at,
        "status": status,
        "error": error,
        "mode": "attach" if attach else "managed",
        "base_url": base_url,
        "served_model": served_model,
        "label": args.label,
        "binary_path": build_metadata["binary_path"],
        "build_variant": build_metadata["build_variant"],
        "context_tokens": context_tokens,
        "steps": results,
    }
    (result_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Results: {result_dir}")


if __name__ == "__main__":
    main()
