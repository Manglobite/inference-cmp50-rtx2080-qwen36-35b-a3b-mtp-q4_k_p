#!/usr/bin/env python3
"""Run a non-destructive, repeatable OpenAI-compatible serving benchmark."""

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK_TIMING_PATTERN = re.compile(r"id\s+(?P<slot>\d+)\s+\| task\s+(?P<task>\d+)\s+\|\s+(?P<kind>prompt eval time|eval time|total time|n_decoded)\s+=\s+(?P<values>.*)")
PROMPT_EVAL_PATTERN = re.compile(r"(?P<milliseconds>[\d.]+) ms /\s*(?P<tokens>\d+) tokens \([^,]+,\s*(?P<tokens_per_second>[\d.]+) tokens per second\)")
TOTAL_PATTERN = re.compile(r"(?P<milliseconds>[\d.]+) ms /\s*(?P<tokens>\d+) tokens")
TG_PATTERN = re.compile(r"(?P<decoded>\d+), tg =\s*(?P<tokens_per_second>[\d.]+) t/s, tg_3s =\s*(?P<tokens_per_second_3s>[\d.]+) t/s")


def request_json(url, payload, timeout=900, api_key=None, retries=0):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers)
    last_error = None
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(1.5 * (attempt + 1))
    else:  # pragma: no cover - loop always breaks or raises
        raise last_error
    elapsed = time.perf_counter() - started
    usage = data.get("usage", {})
    completion = usage.get("completion_tokens", 0)
    message = data.get("choices", [{}])[0].get("message", {})
    timings = data.get("timings") or {}
    return {
        "elapsed_s": elapsed,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion,
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "completion": message.get("content"),
        "reasoning": message.get("reasoning_content"),
        "tool_calls": message.get("tool_calls"),
        "finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
        "tokens_per_second": completion / elapsed if elapsed else 0,
        "timings": timings,
        "cache_hit_fraction": (
            timings.get("cache_n", 0) / usage["prompt_tokens"]
            if timings.get("cache_n") is not None and usage.get("prompt_tokens") else None
        ),
    }


def add_endpoint_args(parser):
    parser.add_argument("--base-url", default=None,
                        help="existing llama-server base URL; also LLAMA_BASE_URL or OPENAI_BASE_URL")
    parser.add_argument("--api-key", default=None,
                        help="bearer token; also LLAMA_API_KEY or OPENAI_API_KEY")
    parser.add_argument("--model", default=None,
                        help="served model alias for attach mode; also LLAMA_MODEL")
    parser.add_argument("--attach", action="store_true",
                        help="do not start/stop a server; talk to --base-url instead")
    parser.add_argument("--retries", type=int, default=1, help="HTTP retries on transport errors")


def resolve_endpoint(args):
    base_url = args.base_url or os.environ.get("LLAMA_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    api_key = args.api_key or os.environ.get("LLAMA_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = args.model or os.environ.get("LLAMA_MODEL")
    return base_url, api_key, model


def normalize_timings(timings):
    """Convert the server 'timings' object into the same shape as the log parser."""
    if not timings:
        return None
    prompt_n = timings.get("prompt_n") or 0
    cache_n = timings.get("cache_n") or 0
    draft_n = timings.get("draft_n") or 0
    draft_accepted = timings.get("draft_n_accepted") or 0
    metrics = {
        "prompt_eval": {
            "tokens": prompt_n,
            "cached_tokens": cache_n,
            "milliseconds": timings.get("prompt_ms"),
            "tokens_per_second": timings.get("prompt_per_second"),
        },
        "eval": {
            "tokens": timings.get("predicted_n"),
            "milliseconds": timings.get("predicted_ms"),
            "tokens_per_second": timings.get("predicted_per_second"),
        },
        "cache_hit_fraction": (cache_n / (cache_n + prompt_n)) if (cache_n + prompt_n) else None,
    }
    if draft_n:
        metrics["draft_acceptance"] = {
            "acceptance": draft_accepted / draft_n,
            "accepted": draft_accepted,
            "generated": draft_n,
            "mean_len": 1 + draft_accepted / draft_n,
        }
    return metrics


def wait_ready(base_url, process, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited during startup with status {process.returncode}")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2):
                return
        except urllib.error.URLError:
            time.sleep(1)
    raise TimeoutError(f"server did not become ready at {base_url} within {timeout_s}s")


def run_case(base_url, model, case, concurrency, api_key=None, retries=0):
    messages = [dict(message) for message in case["messages"]]
    long_context = case.get("long_context")
    if long_context:
        index = long_context.get("message_index", 0)
        repeat_count = long_context["repeat_count"]
        filler = long_context["filler"]
        before = repeat_count // 2
        messages[index]["content"] = "".join((
            long_context["prefix"],
            filler * before,
            long_context["middle"],
            filler * (repeat_count - before),
            long_context["suffix"],
        ))
    repeat_count = case.get("repeat_user_content", 1)
    repeat_index = case.get("repeat_message_index")
    if repeat_count > 1:
        for index, message in enumerate(messages):
            if message["role"] == "user" and (repeat_index is None or index == repeat_index):
                message["content"] *= repeat_count
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": case["max_tokens"],
        "temperature": 0.0,
        "stream": False,
    }
    for field in ("tools", "tool_choice", "response_format"):
        if field in case:
            payload[field] = case[field]
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        started = time.perf_counter()
        requests = list(executor.map(
            lambda _: request_json(f"{base_url}/v1/chat/completions", payload, api_key=api_key, retries=retries),
            range(concurrency),
        ))
        elapsed = time.perf_counter() - started
    completions = sum(item["completion_tokens"] for item in requests)
    result = {
        "case": case["id"],
        "concurrency": concurrency,
        "wall_elapsed_s": elapsed,
        "total_completion_tokens": completions,
        "aggregate_tokens_per_second": completions / elapsed if elapsed else 0,
        "per_request_tokens_per_second": statistics.mean(item["tokens_per_second"] for item in requests),
        "requests": requests,
        "request_timings": [item.get("timings") or {} for item in requests],
    }
    if "expected_completion" in case:
        completions_match = [item["completion"] == case["expected_completion"] for item in requests]
        result["expected_completion"] = case["expected_completion"]
        result["completion_matches_expected"] = all(completions_match)
    return result


def command_for(profile, variant, port):
    model = str(ROOT / profile["model_path"])
    binary = str(ROOT / profile["binary"]) if not profile["binary"].startswith("/") else profile["binary"]
    if profile["engine"] == "llama.cpp":
        environment = os.environ.copy()
        environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        environment["CUDA_VISIBLE_DEVICES"] = profile["gpu"].get("cuda_visible_devices", "0")
        environment.update({str(key): str(value) for key, value in variant.get("environment", {}).items()})
        return [
            binary, "-m", model, "-a", profile["served_model_name"],
            "--device", profile["gpu"]["llama_device"], "--ctx-size", str(variant["context_tokens"]),
            "--parallel", str(variant["parallel_sequences"]), "--host", "127.0.0.1", "--port", str(port),
            *profile["base_args"], *variant.get("server_args", []),
        ], environment
    environment = os.environ.copy()
    environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    environment["CUDA_VISIBLE_DEVICES"] = profile["gpu"]["cuda_visible_devices"]
    environment.update({str(key): str(value) for key, value in variant.get("environment", {}).items()})
    vllm_bin_dir = str(Path(binary).parent)
    environment["PATH"] = f"{vllm_bin_dir}:{environment.get('PATH', '')}"
    return [
        binary, "serve", model, "--served-model-name", profile["served_model_name"],
        "--host", "127.0.0.1", "--port", str(port), "--max-model-len", str(variant["context_tokens"]),
        "--max-num-seqs", str(variant["parallel_sequences"]), *profile["base_args"], *variant.get("server_args", []),
    ], environment


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def build_variant_metadata(profile):
    binary = resolve_path(profile["binary"]).resolve()
    build_variant = profile.get("build_variant")
    manifest = None
    if build_variant:
        manifest = ROOT / "tools/llama-cpp" / build_variant / "manifest.json"
    return {
        "build_variant": build_variant,
        "binary_path": str(binary),
        "binary_sha256": sha256_file(binary) if binary.is_file() else None,
        "manifest_path": str(manifest.resolve()) if manifest and manifest.exists() else None,
        "manifest_sha256": sha256_file(manifest) if manifest and manifest.is_file() else None,
    }


def parse_raw_timings(log_path):
    timings = {}
    for line in log_path.read_text(errors="replace").splitlines():
        task_match = TASK_TIMING_PATTERN.search(line)
        if not task_match:
            continue
        task_id = task_match.group("task")
        timing = timings.setdefault(task_id, {"task_id": int(task_id), "slot_id": int(task_match.group("slot"))})
        kind = task_match.group("kind")
        values = task_match.group("values")
        if kind in {"prompt eval time", "eval time"}:
            match = PROMPT_EVAL_PATTERN.search(values)
            if match:
                timing["prompt_eval" if kind == "prompt eval time" else "eval"] = {
                    "milliseconds": float(match.group("milliseconds")),
                    "tokens": int(match.group("tokens")),
                    "tokens_per_second": float(match.group("tokens_per_second")),
                }
        elif kind == "total time":
            match = TOTAL_PATTERN.search(values)
            if match:
                timing["total"] = {
                    "milliseconds": float(match.group("milliseconds")),
                    "tokens": int(match.group("tokens")),
                }
        else:
            match = TG_PATTERN.search(values)
            if match:
                timing["tg"] = {
                    "decoded_tokens": int(match.group("decoded")),
                    "tokens_per_second": float(match.group("tokens_per_second")),
                    "tokens_per_second_3s": float(match.group("tokens_per_second_3s")),
                }
    return list(timings.values())


def stop_process(process):
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def start_gpu_telemetry(result_dir):
    command = [
        "nvidia-smi",
        "--query-gpu=index,uuid,pci.bus_id,name,temperature.gpu,power.draw,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
        "--loop-ms=500",
    ]
    output = (result_dir / "gpu-telemetry.csv").open("w")
    return subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT), output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=None,
                        help="managed mode: profile JSON that describes how to start the server")
    parser.add_argument("--variant", default=None)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--cases", default="decode-300,decode-500,prefill-4k")
    parser.add_argument("--prompts", type=Path, default=ROOT / "benchmarks/prompts/generic-analysis.json")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "benchmarks/results")
    add_endpoint_args(parser)
    parser.add_argument("--no-telemetry", action="store_true", help="skip local nvidia-smi telemetry")
    args = parser.parse_args()

    base_url_override, api_key, model_override = resolve_endpoint(args)
    attach = args.attach or base_url_override is not None

    profile = None
    build_metadata = {"build_variant": None, "binary_path": None, "binary_sha256": None,
                      "manifest_path": None, "manifest_sha256": None}
    command, environment, gpu_binding = [], {}, {}
    profile_name = "attach"
    context_tokens = None
    if args.profile is not None:
        profile_path = args.profile if args.profile.is_absolute() else ROOT / args.profile
        profile = json.loads(profile_path.read_text())
        if args.variant not in profile["profiles"]:
            raise SystemExit(f"unknown variant {args.variant!r}; choices: {', '.join(profile['profiles'])}")
        variant = profile["profiles"][args.variant]
        concurrency = args.concurrency or variant["parallel_sequences"]
        if concurrency > variant["parallel_sequences"]:
            raise SystemExit("requested concurrency exceeds configured server slots")
        port = args.port or variant["port"]
        base_url = base_url_override or f"http://127.0.0.1:{port}"
        served_model = model_override or profile["served_model_name"]
        context_tokens = variant["context_tokens"]
        profile_name = profile["name"]
        build_metadata = build_variant_metadata(profile)
        if not attach:
            command, environment = command_for(profile, variant, port)
            gpu_binding = {
                "cuda_device_order": environment.get("CUDA_DEVICE_ORDER"),
                "cuda_visible_devices": environment.get("CUDA_VISIBLE_DEVICES"),
                "expected_pci_bus_id": profile["gpu"]["pci_bus_id"],
                "llama_device": profile["gpu"].get("llama_device"),
            }
    else:
        if not attach:
            raise SystemExit("provide --profile (managed mode) or --attach --model M --base-url URL")
        if not model_override:
            raise SystemExit("--model (or LLAMA_MODEL) is required in attach mode")
        base_url = base_url_override or "http://127.0.0.1:8080"
        served_model = model_override
        concurrency = args.concurrency or 1

    prompts_path = args.prompts if args.prompts.is_absolute() else ROOT / args.prompts
    prompt_document = json.loads(prompts_path.read_text())
    prompts = prompt_document.get("cases", prompt_document) if isinstance(prompt_document, dict) else prompt_document
    selected = set(args.cases.split(","))
    cases = [case for case in prompts if case["id"] in selected]
    if not cases:
        raise SystemExit("no selected benchmark cases")

    variant_name = args.variant or "attach"
    run_id_parts = [dt.datetime.now().strftime("%Y%m%d-%H%M%S"), "llama.cpp"]
    if build_metadata["build_variant"]:
        run_id_parts.append(build_metadata["build_variant"])
    run_id_parts.append(variant_name)
    run_id = "-".join(run_id_parts)
    result_dir = args.results_dir / run_id
    result_dir.mkdir(parents=True, exist_ok=False)
    if profile is not None:
        (result_dir / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    (result_dir / "prompts.json").write_text(json.dumps(prompt_document, indent=2) + "\n")
    if command:
        (result_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    (result_dir / "build-variant.json").write_text(json.dumps(build_metadata, indent=2) + "\n")
    if gpu_binding:
        (result_dir / "gpu-binding.json").write_text(json.dumps(gpu_binding, indent=2) + "\n")
    with (result_dir / "environment.json").open("w") as output:
        collector_command = [sys.executable, str(ROOT / "benchmarks/scripts/collect_env.py")]
        if build_metadata["binary_path"]:
            collector_command.extend(["--binary", build_metadata["binary_path"]])
        if build_metadata["build_variant"]:
            collector_command.extend(["--build-variant", build_metadata["build_variant"]])
        if build_metadata["manifest_path"]:
            collector_command.extend(["--manifest", build_metadata["manifest_path"]])
        if attach:
            collector_command.extend(["--base-url", base_url])
            if api_key:
                collector_command.extend(["--api-key", api_key])
        subprocess.run(collector_command, cwd=ROOT, stdout=output, check=True)

    results = []
    raw_timings = []
    if attach:
        print(f"Attaching to {base_url} (model {served_model})")
        warmup = {"model": served_model, "messages": cases[0]["messages"], "max_tokens": 32, "temperature": 0.0}
        request_json(f"{base_url}/v1/chat/completions", warmup, api_key=api_key, retries=args.retries)
        for repetition in range(1, args.repetitions + 1):
            for case in cases:
                item = run_case(base_url, served_model, case, concurrency, api_key=api_key, retries=args.retries)
                item["repetition"] = repetition
                results.append(item)
                print(f"{case['id']} rep {repetition}: {item['aggregate_tokens_per_second']:.2f} aggregate tok/s")
    else:
        print(f"Starting {profile_name} ({args.variant}) on {base_url}")
        telemetry_process, telemetry_output = (None, None)
        if not args.no_telemetry and shutil.which("nvidia-smi"):
            telemetry_process, telemetry_output = start_gpu_telemetry(result_dir)
        try:
            with (result_dir / "server.log").open("w") as server_log:
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=server_log, stderr=subprocess.STDOUT)
                try:
                    wait_ready(base_url, process, 900)
                    warmup = {"model": served_model, "messages": cases[0]["messages"], "max_tokens": 32, "temperature": 0.0}
                    request_json(f"{base_url}/v1/chat/completions", warmup, api_key=api_key, retries=args.retries)
                    for repetition in range(1, args.repetitions + 1):
                        for case in cases:
                            item = run_case(base_url, served_model, case, concurrency, api_key=api_key, retries=args.retries)
                            item["repetition"] = repetition
                            results.append(item)
                            print(f"{case['id']} rep {repetition}: {item['aggregate_tokens_per_second']:.2f} aggregate tok/s")
                finally:
                    stop_process(process)
        except Exception as exc:
            failure = {
                "run_id": run_id,
                "status": "failed",
                "error": str(exc),
                "engine": "llama.cpp",
                "profile": profile_name,
                "variant": variant_name,
            }
            (result_dir / "result.json").write_text(json.dumps(failure, indent=2) + "\n")
            print(f"Failed run preserved at: {result_dir}", file=sys.stderr)
            raise
        finally:
            if telemetry_process is not None:
                stop_process(telemetry_process)
                telemetry_output.close()
        raw_timings = parse_raw_timings(result_dir / "server.log")
        measured_timings = raw_timings[1:]
        if concurrency == 1 and len(measured_timings) == len(results):
            for result, timing in zip(results, measured_timings):
                result["raw_server_timing"] = timing
        elif concurrency == 1 and measured_timings:
            print("warning: could not match raw llama.cpp timings; request_timings kept", file=sys.stderr)

    report = {
        "run_id": run_id,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "attach" if attach else "managed",
        "engine": "llama.cpp",
        "profile": profile_name,
        "variant": variant_name,
        "base_url": base_url,
        "served_model": served_model,
        "build_variant": build_metadata["build_variant"],
        "binary_path": build_metadata["binary_path"],
        "binary_sha256": build_metadata["binary_sha256"],
        "manifest_path": build_metadata["manifest_path"],
        "manifest_sha256": build_metadata["manifest_sha256"],
        "context_tokens": context_tokens,
        "configured_parallel_sequences": (profile["profiles"][args.variant]["parallel_sequences"] if profile is not None else concurrency),
        "request_concurrency": concurrency,
        "gpu_pci_bus_id": (profile["gpu"]["pci_bus_id"] if profile is not None else None),
        "raw_server_timings": raw_timings,
        "results": results,
    }
    (result_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Results: {result_dir}")


if __name__ == "__main__":
    main()
