#!/usr/bin/env python3
"""Sample host and GPU telemetry to a CSV until terminated."""

import csv
import os
import signal
import subprocess
import sys
import time


def read_cpu():
    with open("/proc/stat") as handle:
        fields = list(map(int, handle.readline().split()[1:]))
    idle = fields[3] + fields[4]
    return idle, sum(fields)


def cpu_temp_c():
    best = None
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return ""
    for zone in os.listdir(base):
        if not zone.startswith("thermal_zone"):
            continue
        try:
            value = int(open(os.path.join(base, zone, "temp")).read().strip())
        except (OSError, ValueError):
            continue
        if value > 1000:
            value /= 1000.0
        if 0 < value < 130 and (best is None or value > best):
            best = value
    return best if best is not None else ""


def read_mem():
    values = {}
    with open("/proc/meminfo") as handle:
        for line in handle:
            key, rest = line.split(":", 1)
            values[key] = int(rest.split()[0])
    used = (values["MemTotal"] - values["MemAvailable"]) / 1024 / 1024
    total = values["MemTotal"] / 1024 / 1024
    swap = (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) / 1024 / 1024
    return round(used, 2), round(total, 2), round(swap, 2)


def read_gpus():
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        gpus.append([x.strip() for x in line.split(",")])
    return gpus


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sample CPU/RAM/GPU telemetry to CSV")
    parser.add_argument("path", help="output CSV path")
    parser.add_argument("interval", nargs="?", type=float, default=0.5, help="seconds between samples (default 0.5)")
    parser.add_argument("--label", default="", help="free-form label stored in the first column")
    args = parser.parse_args()
    path = args.path
    interval = args.interval
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    header = ["ts", "label", "cpu_pct", "cpu_temp_c", "ram_used_gib", "ram_total_gib", "swap_used_gib"]
    for i in range(3):
        header += [f"gpu{i}_temp", f"gpu{i}_util", f"gpu{i}_mem_used", f"gpu{i}_mem_total", f"gpu{i}_power"]
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        prev = read_cpu()
        while running:
            started = time.time()
            idle, total = read_cpu()
            delta_total = total - prev[1]
            cpu_pct = 100 * (1 - (idle - prev[0]) / delta_total) if delta_total > 0 else 0
            prev = (idle, total)
            ram_used, ram_total, swap_used = read_mem()
            row = [
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                args.label,
                round(cpu_pct, 1),
                cpu_temp_c(),
                ram_used,
                ram_total,
                swap_used,
            ]
            gpus = read_gpus()
            for i in range(3):
                row += gpus[i][1:6] if i < len(gpus) else ["", "", "", "", ""]
            writer.writerow(row)
            handle.flush()
            time.sleep(max(0.0, interval - (time.time() - started)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
