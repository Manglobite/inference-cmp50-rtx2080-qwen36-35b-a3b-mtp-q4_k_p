#!/usr/bin/env python3
"""Run a non-destructive, repeatable OpenAI-compatible serving benchmark."""

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
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


def request_json(url, payload, timeout=900):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    elapsed = time.perf_counter() - started
    usage = data.get("usage", {})
    completion = usage.get("completion_tokens", 0)
    message = data.get("choices", [{}])[0].get("message", {})
    return {
        "elapsed_s": elapsed,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion,
        "completion": message.get("content"),
        "tool_calls": message.get("tool_calls"),
        "finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
        "tokens_per_second": completion / elapsed if elapsed else 0,
    }


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


def run_case(base_url, model, case, concurrency):
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
        requests = list(executor.map(lambda _: request_json(f"{base_url}/v1/chat/completions", payload), range(concurrency)))
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
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--cases", default="decode-300,decode-500,prefill-4k")
    parser.add_argument("--prompts", type=Path, default=ROOT / "benchmarks/prompts/codebase-analysis.json")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "benchmarks/results")
    args = parser.parse_args()

    profile_path = args.profile if args.profile.is_absolute() else ROOT / args.profile
    profile = json.loads(profile_path.read_text())
    if args.variant not in profile["profiles"]:
        raise SystemExit(f"unknown variant {args.variant!r}; choices: {', '.join(profile['profiles'])}")
    variant = profile["profiles"][args.variant]
    concurrency = args.concurrency or variant["parallel_sequences"]
    if concurrency > variant["parallel_sequences"]:
        raise SystemExit("requested concurrency exceeds configured server slots")
    port = args.port or variant["port"]
    base_url = f"http://127.0.0.1:{port}"
    prompts_path = args.prompts if args.prompts.is_absolute() else ROOT / args.prompts
    prompt_document = json.loads(prompts_path.read_text())
    prompts = prompt_document.get("cases", prompt_document) if isinstance(prompt_document, dict) else prompt_document
    selected = set(args.cases.split(","))
    cases = [case for case in prompts if case["id"] in selected]
    if not cases:
        raise SystemExit("no selected benchmark cases")

    build_metadata = build_variant_metadata(profile)
    run_id_parts = [dt.datetime.now().strftime("%Y%m%d-%H%M%S"), profile["engine"]]
    if build_metadata["build_variant"]:
        run_id_parts.append(build_metadata["build_variant"])
    run_id_parts.append(args.variant)
    run_id = "-".join(run_id_parts)
    result_dir = args.results_dir / run_id
    result_dir.mkdir(parents=True, exist_ok=False)
    command, environment = command_for(profile, variant, port)
    (result_dir / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    (result_dir / "prompts.json").write_text(json.dumps(prompt_document, indent=2) + "\n")
    (result_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    (result_dir / "build-variant.json").write_text(json.dumps(build_metadata, indent=2) + "\n")
    (result_dir / "gpu-binding.json").write_text(json.dumps({
        "cuda_device_order": environment.get("CUDA_DEVICE_ORDER"),
        "cuda_visible_devices": environment.get("CUDA_VISIBLE_DEVICES"),
        "expected_pci_bus_id": profile["gpu"]["pci_bus_id"],
        "llama_device": profile["gpu"].get("llama_device"),
    }, indent=2) + "\n")
    with (result_dir / "environment.json").open("w") as output:
        collector_command = [sys.executable, str(ROOT / "benchmarks/scripts/collect_env.py"), "--binary", build_metadata["binary_path"]]
        if build_metadata["build_variant"]:
            collector_command.extend(["--build-variant", build_metadata["build_variant"]])
        if build_metadata["manifest_path"]:
            collector_command.extend(["--manifest", build_metadata["manifest_path"]])
        subprocess.run(collector_command, cwd=ROOT, stdout=output, check=True)

    print(f"Starting {profile['name']} ({args.variant}) on {base_url}")
    results = []
    telemetry_process, telemetry_output = start_gpu_telemetry(result_dir)
    try:
        with (result_dir / "server.log").open("w") as server_log:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=server_log, stderr=subprocess.STDOUT)
            try:
                wait_ready(base_url, process, 300)
                warmup = {"model": profile["served_model_name"], "messages": cases[0]["messages"], "max_tokens": 32, "temperature": 0.0}
                request_json(f"{base_url}/v1/chat/completions", warmup)
                for repetition in range(1, args.repetitions + 1):
                    for case in cases:
                        item = run_case(base_url, profile["served_model_name"], case, concurrency)
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
            "engine": profile["engine"],
            "profile": profile["name"],
            "variant": args.variant,
        }
        (result_dir / "result.json").write_text(json.dumps(failure, indent=2) + "\n")
        print(f"Failed run preserved at: {result_dir}", file=sys.stderr)
        raise
    finally:
        stop_process(telemetry_process)
        telemetry_output.close()
    raw_timings = parse_raw_timings(result_dir / "server.log") if profile["engine"] == "llama.cpp" else []
    measured_timings = raw_timings[1:]
    if concurrency == 1 and len(measured_timings) == len(results):
        for result, timing in zip(results, measured_timings):
            result["raw_server_timing"] = timing
    elif concurrency == 1:
        raise RuntimeError(
            f"could not match raw llama.cpp timings: expected {len(results)} measured tasks, got {len(measured_timings)}"
        )
    report = {
        "run_id": run_id,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine": profile["engine"],
        "profile": profile["name"],
        "variant": args.variant,
        "build_variant": build_metadata["build_variant"],
        "binary_path": build_metadata["binary_path"],
        "binary_sha256": build_metadata["binary_sha256"],
        "manifest_path": build_metadata["manifest_path"],
        "manifest_sha256": build_metadata["manifest_sha256"],
        "context_tokens": variant["context_tokens"],
        "configured_parallel_sequences": variant["parallel_sequences"],
        "request_concurrency": concurrency,
        "gpu_pci_bus_id": profile["gpu"]["pci_bus_id"],
        "raw_server_timings": raw_timings,
        "results": results,
    }
    (result_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Results: {result_dir}")


if __name__ == "__main__":
    main()
