# Agent prompt: reproduce and validate the Qwen3.6-35B-A3B three-GPU setup

Copy the text below into an agent session running on the target machine, in the
root of this case directory. It is written to be executable end-to-end: the
agent checks the hardware, downloads the model, runs the bundled runtime,
optionally rebuilds the llama.cpp variants, runs the A/B and context tests, and
writes a report with a comparison against the expected numbers.

---

## Mission

You are on a machine that should be a close match to the reference rig: two
NVIDIA CMP 50HX 10 GiB cards and one RTX 2080 Ti 22 GiB (or a similar Turing
sm_75 mix), Xeon-class CPU, 30 GiB RAM, Ubuntu with an NVIDIA driver. Your job:
bring up the optimized llama.cpp serving setup for Qwen3.6-35B-A3B Q4_K_P from
this case, reproduce the key measurements, and report deviations. Do not
improvise new optimizations; validate what is here first.

## Ground rules

- Work from this case directory. Do not modify `llama.cpp/src`, `patches/`,
  `profiles/` or `docs/`; write all outputs under `benchmarks/results/` and new
  files under `reports/`.
- Change one experimental axis at a time and require byte-identical completions
  (temperature 0) before accepting any speed difference.
- Preserve failed runs. Never delete result directories.
- Check that the GPUs are free before every benchmark (`nvidia-smi`); do not
  benchmark while another compute workload runs.
- Builds must run serially under a memory guard (`scripts/build-df03399.sh`
  does this); never use bare `cmake --build --parallel` on a 30 GiB host.
- Do not expose or commit API keys. Default the server to `127.0.0.1`.
- Stop and report if a step fails twice, output becomes non-deterministic, a GPU
  exceeds 85 C, or the kernel log shows an OOM/Xid.

## Phase 0 - environment check

```bash
nvidia-smi --query-gpu=index,name,pci.bus_id,memory.total,compute_cap --format=csv
nvidia-smi topo -m
nvcc --version | tail -1
cmake --version | head -1
free -h
df -h .
```

Pass criteria: three GPUs visible, all compute capability 7.5, at least
2×10240 + 22528 MiB VRAM, at least 30 GiB RAM (or adjust expectations),
at least 40 GB free disk, CUDA toolkit 12.x with nvcc, CMake >= 3.20.
Record the output in `reports/00-environment.txt`.

## Phase 1 - read the case

Read `README.en.md`, `HARDWARE.md`, `CHRONOLOGY.md`, `WHAT_INFLUENCES_WHAT.md`
and the result documents under `docs/`. Confirm the adopted configuration:

```text
devices CUDA0,CUDA2,CUDA1 (RTX is the tail), tensor-split 1,1,2.5,
ctx 262144, K/V q8_0, Flash Attention, MTP n-max=3, ubatch 448,
runtime = df03399 + ported PR #25834 + nvcc -fmad=false
```

## Phase 2 - model download and verification

```bash
mkdir -p models
base=https://huggingface.co/morikomorizz/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP/resolve/main
curl -L -C - -o models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf \
  "$base/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf"
curl -L -C - -o models/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf \
  "$base/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf"
sha256sum models/*.gguf
```

Expected:

- model: 24,322,493,952 bytes, SHA-256
  `d4c1bc574fee76d0667e63cecec1a644eb0c3a13adbdc254af5b9b84a28de993`;
- projector: 899,283,072 bytes, SHA-256
  `c8e702344a81f8c226a914aa980ed6e1f604bce9374f1fed8e65c896908af414`.

If a hash differs, stop and report; do not benchmark an unknown model.

## Phase 3 - run the bundled runtime

The runtime is not tracked in Git. Get it first:

```bash
# download the release asset (verifies SHA-256 and unpacks to llama.cpp/runtime/)
bash scripts/fetch-runtime.sh
# or build it locally (about 8 minutes):
# bash scripts/build-df03399.sh no-fmad /tmp/llama-nofmad
# cp -a /tmp/llama-nofmad/bin llama.cpp/runtime/
```

Then start the server:

```bash
bash scripts/launch-server.sh > reports/01-server.log 2>&1 &
# wait for health
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8085/health && break; sleep 5; done
```

Verify provenance and smoke:

```bash
llama.cpp/runtime/bin/llama-server --version            # must contain df03399
sha256sum -c <(python3 - <<'PY'
import json,hashlib,pathlib
m=json.load(open('llama.cpp/runtime/manifest.json'))
for rel,sha in m['files'].items():
    p=pathlib.Path('llama.cpp/runtime')/rel
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    print(f"{h}  {p}")
PY
)
curl -s -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-35B-A3B-uncensored-MTP-Q4_K_P","messages":[{"role":"user","content":"2+2="}],"max_tokens":32,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}' \
  http://127.0.0.1:8085/v1/chat/completions
```

Expected: health 200, version contains `df03399`, all manifest hashes match,
completion content `2 + 2 = 4` with `finish_reason=stop`.

## Phase 4 - optional rebuild and A/B

Build the comparison runtimes (about 8 minutes each, serial):

```bash
bash scripts/build-df03399.sh baseline /tmp/llama-baseline
bash scripts/build-df03399.sh no-fmad  /tmp/llama-nofmad
```

Verify that the no-fmad build really has the flag:

```bash
grep -m1 -- '-fmad=false' /tmp/llama-nofmad/ggml/src/ggml-cuda/CMakeFiles/ggml-cuda.dir/flags.make
```

Stop the bundled server, then run alternating pairs with the harness
(from this case root), for the three configurations available:

```bash
# adopted (bundled)
python3 benchmarks/scripts/run.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-rtx-tail-mtp3-split2p5.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

For baseline and DP2A: point the `bin` symlink in
`tools/llama-cpp/qwen36-df03399-baseline/` (or `...-dp2a/`) at the matching
build, then run the corresponding profile the same way. Alternate A/B/A/B/A
(three to five pairs) and compare medians of the raw `eval` rate.

Expected medians (decode-500, 262k): baseline ~47.8, DP2A ~54.0,
DP2A+no-fmad ~62.2, adopted RTX-tail + MTP 3 ~95.5 tok/s. Accept ±10% as
toolchain/hardware variation; report anything outside that band.

## Phase 5 - context ladder check

Start the adopted server at 360k (`CTX_SIZE=368640 bash scripts/launch-server.sh`),
build the ladder prompts, and run the single-session test:

```bash
python3 benchmarks/scripts/build_context_ladder.py --base-url http://127.0.0.1:8085 \
  --targets 10000,75000 --out prompts/context-ladder.json
python3 benchmarks/scripts/run_context_ladder.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native --steps prompts/context-ladder-steps-test1.json \
  --prompts prompts/context-ladder.json --label test1-360k
```

Expected: the repeated 75k request evaluates only a handful of tokens
(~100% prompt cache), prefill for a cold 75k prompt is about 300-340 tok/s,
generation at 75k context is about 55-65 tok/s, RTX peak VRAM about 21.9 GiB.

## Phase 6 - report

Write `reports/FINAL-REPORT.md` containing:

1. Environment summary and any hardware differences.
2. Provenance: binary version, manifest hash check, model hashes.
3. Table: configuration -> decode-500 / prefill-4k / repo-28k medians, with the
   expected reference numbers and the deltas.
4. Ladder results with cache-hit evidence.
5. Any deviation, failure or OOM, with the preserved run directories.
6. Explicit statement of which configuration you recommend leaving running.

Link every claim to a run directory under `benchmarks/results/`. Do not delete
anything. If a step could not be completed, say so plainly and stop at that
step rather than guessing.

---

## Short version (if the agent has little context)

> Read `README.en.md` and `RUNBOOK.md`, verify the three sm_75 GPUs, download the
> model and projector with the checksums from the runbook, run
> `scripts/launch-server.sh`, confirm `--version` contains `df03399` and the
> smoke answer is `2 + 2 = 4`, then measure decode-500 with
> `benchmarks/scripts/run.py` using the `rtx-tail-mtp3-split2p5` profile.
> The expected decode rate is ~95 tok/s; report the measured value, telemetry
> and any deviation. Do not change other settings before reporting.
