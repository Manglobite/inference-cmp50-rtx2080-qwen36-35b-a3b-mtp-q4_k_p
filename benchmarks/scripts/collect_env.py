#!/usr/bin/env python3
"""Collect stable, machine-readable benchmark environment facts."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path


def command_output(command):
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable: {exc}"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binary_provenance(binary, build_variant, manifest):
    if binary is None:
        return {}
    binary = binary.resolve()
    provenance = {
        "binary_path": str(binary),
        "binary_version": command_output([str(binary), "--version"]),
        "binary_sha256": sha256_file(binary) if binary.is_file() else None,
    }
    if build_variant is not None:
        provenance["build_variant"] = build_variant
    if manifest is not None:
        manifest = manifest.resolve()
        provenance["manifest_path"] = str(manifest)
        provenance["manifest_sha256"] = sha256_file(manifest) if manifest.is_file() else None
        if manifest.is_file():
            try:
                provenance["manifest"] = json.loads(manifest.read_text())
            except json.JSONDecodeError as exc:
                provenance["manifest_error"] = f"invalid JSON: {exc}"
    return provenance


def http_json(url, api_key, timeout=10):
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": str(exc)}


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--build-variant")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--base-url", default=None, help="record provenance of a running server")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    environment = {
        "platform": platform.platform(),
        "python": sys.version,
        "git_head": command_output(["git", "rev-parse", "HEAD"]),
        "git_status": command_output(["git", "status", "--short"]),
        "gpus": command_output([
            "nvidia-smi",
            "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,driver_version,compute_cap",
            "--format=csv",
        ]),
        "vllm_version": command_output([
            str(root / ".venv/bin/python"), "-c", "import vllm; print(vllm.__version__)"
        ]),
    }
    environment.update(binary_provenance(args.binary, args.build_variant, args.manifest))
    if args.base_url:
        base = args.base_url.rstrip("/")
        props = http_json(f"{base}/props", args.api_key)
        environment["remote_server"] = {
            "base_url": base,
            "props": {k: props.get(k) for k in ("model_alias", "model_path", "build_info", "total_slots")
                      if isinstance(props, dict)},
            "models": http_json(f"{base}/v1/models", args.api_key),
        }
    print(json.dumps(environment, indent=2))


if __name__ == "__main__":
    main()
