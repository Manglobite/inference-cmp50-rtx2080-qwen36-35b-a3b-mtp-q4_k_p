# Runbook

**English** | [Русский](RUNBOOK.ru.md)

## 1. Download the model files

Put both files into `models/`. Only the GGUF is required for text; the
projector is needed for vision and is referenced by the launcher, so either
download it or override `MMPROJ=` with an existing file.

```bash
mkdir -p models
base=https://huggingface.co/morikomorizz/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP/resolve/main

curl -L -C - -o models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf \
  "$base/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf"
curl -L -C - -o models/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf \
  "$base/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf"
```

Checksums (verify before use; the model card may change over time, then
re-validate the numbers below on your copy):

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf` | 24,322,493,952 | `d4c1bc574fee76d0667e63cecec1a644eb0c3a13adbdc254af5b9b84a28de993` |
| `mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf` | 899,283,072 | `c8e702344a81f8c226a914aa980ed6e1f604bce9374f1fed8e65c896908af414` |

```bash
sha256sum models/*.gguf
```

Alternative: `huggingface-cli download morikomorizz/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP --local-dir models`.

## 2. Start the adopted profile (release runtime, no build)

The runtime is not tracked in Git; download the release asset first (it is
verified and unpacked into `llama.cpp/runtime/`), or build it locally:

```bash
bash scripts/fetch-runtime.sh
# or: bash scripts/build-df03399.sh no-fmad /tmp/llama-nofmad
#     cp -a /tmp/llama-nofmad/bin llama.cpp/runtime/
```

Then start the server:

```bash
bash scripts/launch-server.sh
```

Defaults: `--device CUDA0,CUDA2,CUDA1` (RTX tail), `--tensor-split 1,1,2.5`,
ctx 262144, ubatch 448, MTP `n-max=3`, Q8_0 K/V, Flash Attention,
`--cache-ram 8192`, port 8085, host 127.0.0.1.

Overrides (examples):

```bash
CTX_SIZE=368640 PORT=8085 bash scripts/launch-server.sh   # 360k context
API_KEY=secret bash scripts/launch-server.sh              # require an API key
UBATCH_SIZE=320 bash scripts/launch-server.sh             # if VRAM is tight
```

Smoke test in another terminal:

```bash
curl -s http://127.0.0.1:8085/health
curl -s -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-35B-A3B-uncensored-MTP-Q4_K_P","messages":[{"role":"user","content":"2+2="}],"max_tokens":32,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}' \
  http://127.0.0.1:8085/v1/chat/completions
```

Expected: HTTP 200 and a deterministic answer (in our runs `2 + 2 = 4`).

## 3. Compare with the baseline (A/B)

The bundled runtime is the adopted DP2A + `-fmad=false` build. To reproduce
the comparison, build the two other modes with the same script:

```bash
bash scripts/build-df03399.sh baseline /tmp/llama-baseline
bash scripts/build-df03399.sh dp2a     /tmp/llama-dp2a
# optional: keep them in the case tree
mkdir -p llama.cpp/runtime-baseline llama.cpp/runtime-dp2a
cp -a /tmp/llama-baseline/bin llama.cpp/runtime-baseline/
cp -a /tmp/llama-dp2a/bin     llama.cpp/runtime-dp2a/
```

Then run alternating pairs with the harness (from the case root):

```bash
# adopted runtime (RTX tail, MTP 3)
python3 benchmarks/scripts/run.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-rtx-tail-mtp3-split2p5.json \
  --variant native-262k --cases decode-500 --repetitions 1

# baseline (needs tools/llama-cpp/qwen36-df03399-baseline/bin -> your baseline build)
python3 benchmarks/scripts/run.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-baseline.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

Profiles reference `tools/llama-cpp/<build_variant>/bin`; the case ships a
symlink of the adopted variant to the bundled runtime. For baseline and DP2A,
replace the `bin` symlink in the matching `tools/llama-cpp/qwen36-df03399-*`
directory with your build. Results are written to `benchmarks/results/`.

Expected medians (262k, decode-500, raw server eval): baseline ~47.8,
DP2A ~54.0, no-fmad ~62.2, adopted RTX tail + MTP 3 ~95.5 tok/s. Treat
±10% as normal hardware/toolchain variation.

## 4. Context ladder and agent sessions

```bash
# single session ladder at 360k: hello -> 10k -> 75k -> repeat
python3 benchmarks/scripts/build_context_ladder.py --base-url http://127.0.0.1:8085 --targets 10000,75000 --out prompts/context-ladder.json
python3 benchmarks/scripts/run_context_ladder.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native --steps prompts/context-ladder-steps-test1.json \
  --prompts prompts/context-ladder.json --label test1-360k

# agent-style design session with simulated tools
python3 benchmarks/scripts/run_design_session.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native --script prompts/design-session-360k.json --label design
```

Each run directory contains `result.json`/`metrics.json`, `server.log`,
`host-telemetry.csv` (CPU load/temp, RAM, swap, per-GPU temp/util/mem/power at
0.5 s), `gpu-binding.json` and the copied inputs.

## 5. Rollback

- Adopted -> baseline: `bash scripts/launch-server-baseline.sh` (needs the
  baseline build), or start the adopted launcher with
  `SPEC_N_MAX=1 DEVICES=CUDA0,CUDA1,CUDA2 TENSOR_SPLIT=1,3,1 UBATCH_SIZE=448`.
- If anything on the live host is managed by `inference-hub`, stop/start the
  server through its API (`/api/backends/<pid>/stop`,
  `/api/profiles/<script>/start`) and keep `idleAfterSeconds` accounted for:
  the hub locks CMP clocks to 300 MHz after the idle timeout, which distorts
  benchmarks until the next wake.

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| CUDA OOM on a CMP during prefill | ubatch too large for the 10 GiB card | lower `UBATCH_SIZE` (448 -> 320 -> 256) or use `TENSOR_SPLIT=1,3,1` |
| CUDA OOM on the RTX at 360k | KV + buffers exceed ~22 GiB | lower `CTX_SIZE`, lower ubatch, or move some layers to the CMPs (`1,1,2.25`/`1,1,2`) |
| Decode suddenly slow with MTP on | MTP tensors placed on a different device than the tail | do not use `-ot` on `blk.40.*` alone; keep device order with the RTX last |
| Prompt cache never hits | different prompt text or cache disabled | send identical prefixes, keep `--cache-prompt --cache-ram 8192` |
| Swap fills and host slows | 360k ctx + two slots + 8 GiB prompt cache | lower `CACHE_RAM_MIB`, use one slot |
| `llama-server` exits at startup | model missing/wrong size, port busy, another server running | check `models/`, free the port, stop the other process |
| Build killed by OOM | bare `--parallel` on a 30 GiB host | use `scripts/build-df03399.sh` (systemd guard), never bare `--parallel` |

## 7. Measurement practice used in this case

1. Bind strictly: `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA_VISIBLE_DEVICES=0,1,2`,
   and record `gpu-binding.json` plus telemetry for every run.
2. One change per comparison; alternate A/B runs; keep everything else fixed.
3. Require byte-identical completions at temperature 0 before believing a
   speed difference.
4. Report raw server timings (`prompt eval`, `eval`) as the primary metric and
   HTTP throughput as the user-visible confirmation.
5. Preserve failed runs; they document the OOM/stability edges.
