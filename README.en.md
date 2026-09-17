# Qwen3.6-35B-A3B on 2×CMP 50HX + RTX 2080 Ti: optimized llama.cpp recipe

[Русский](README.md) | **English**

Open case study for a mixed three-GPU Turing rig. It contains the working
runtime, the patch, all launch/benchmark scripts, measured results and a
ready-to-execute prompt for another agent. Goal: let owners of similar
hardware skip the long research path and start from a proven configuration.

## TL;DR

- Hardware: **2× NVIDIA CMP 50HX 10 GiB + 1× RTX 2080 Ti 22 GiB** (all sm_75),
  30 GiB RAM, Xeon E5-2670 v3.
- Model: **Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP Q4_K_P** (24.3 GB GGUF,
  native MTP head), Q8_0 K/V, Flash Attention, 262,144 context (368,640 works).
- Two CMP-specific problems: DP4A executes at ~33 cycles (vs 2.25 for DP2A) and
  FP32 FMA is throttled (~0.43 vs 6.88 TFLOPS for split mul+add).
- Fixes: PR #25834 ported to `df03399` (`GGML_CUDA_DISABLE_DP4A=ON`) +
  nvcc `-fmad=false`.
- Best configuration: make the **RTX the tail stage** (`--device CUDA0,CUDA2,CUDA1`,
  `--tensor-split 1,1,2.5`) and use **MTP `--spec-draft-n-max 3`**; ubatch 448.

Measured on the decision profile (decode-500 / prefill-4k, raw server timings):

| Variant | decode-500 | prefill-4k | repo-28k prefill | repo-28k decode |
| --- | ---: | ---: | ---: | ---: |
| baseline DP4A | 47.8 t/s | 372.7 t/s | 372.4 t/s | ~53 t/s |
| + DP2A | 54.0 t/s | 373.3 t/s | - | - |
| + `-fmad=false` | 62.2 t/s | 431.8 t/s | - | - |
| **RTX tail + MTP n-max=3 (adopted)** | **95.5 t/s** | **465.8 t/s** | **405.4 t/s** | **82.3 t/s** |

CMP-only control (DeepSeek-R1-Qwen3-8B Q4_K_M, single CMP 50HX):
27.9 → 47.3 → 61.3 t/s for baseline → DP2A → DP2A+no-fmad, i.e. **+119%**.

The case was validated end-to-end from its own directory on 2026-09-17:
`benchmarks/scripts/run.py` with the adopted profile measured **91.4 tok/s** raw
eval (reference 95.5, -4%), and `scripts/launch-server.sh` started the server,
answered the smoke prompt (`2 + 2 = 4`) and stopped cleanly.

## Quick start (ready runtime)

```bash
# 1. get the runtime: download the release asset into llama.cpp/runtime/
bash scripts/fetch-runtime.sh
#    (or build it locally: bash scripts/build-df03399.sh no-fmad /tmp/llama-nofmad)

# 2. put the model files into ./models (see RUNBOOK.md and AGENT_PROMPT.md)
#    Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf
#    mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf

# 3. start the adopted three-GPU profile (RTX tail, MTP 3, 262144 ctx)
bash scripts/launch-server.sh

# 4. health + smoke
curl -s http://127.0.0.1:8085/health
```

The runtime is distributed as a GitHub release asset (~53 MB compressed,
DP2A patch + `-fmad=false`), so no compilation is required to run it; the
script verifies its SHA-256. Build artifacts and the source snapshot are not
tracked in Git - rebuild them with `scripts/build-df03399.sh` if you prefer
or need another mode.

## Repository layout

```text
qwen36-35b-a3b/
├── README.en.md               <- this file (English)
├── README.md                  <- Russian version (default entry)
├── HARDWARE.md / .ru.md       <- exact test rig and minimum requirements
├── CHRONOLOGY.md / .ru.md     <- what was tried, why, and where it led
├── WHAT_INFLUENCES_WHAT.md / .ru.md  <- parameter -> effect matrix
├── RUNBOOK.md / .ru.md        <- run, benchmark, rollback, troubleshoot
├── AGENT_PROMPT.md            <- self-contained task for another agent (EN only)
├── LICENSE-NOTICE.md / .ru.md <- licenses for llama.cpp, patch, model
├── llama.cpp/
│   ├── runtime/               <- ready llama-server + libs (release asset, not in Git)
│   └── src/                   <- patched df03399 source (build artifact, not in Git)
├── patches/                   <- ported PR #25834 patch (df03399)
├── scripts/                   <- launchers, build script, benchmark harness
├── profiles/                  <- benchmark profile JSONs for every experiment
├── prompts/                   <- prompts for ladders and design sessions
├── docs/                      <- full result reports and dialogues
└── results-summary/           <- per-message tables of the design sessions
```

Language convention: every human-facing document has two versions with a
switcher line at the top; the default entry is the Russian `README.md`, the
English one is `README.en.md`. Other documents are English `*.md` plus Russian
`*.ru.md`. `AGENT_PROMPT.md` is English-only on purpose - it is written for an
automated agent. The result reports under `docs/` follow the EN + RU convention.

## What is here and where to read more

| Topic | Document |
| --- | --- |
| Hardware and software versions | [HARDWARE.md](HARDWARE.md) |
| Full research chronology and reasons | [CHRONOLOGY.md](CHRONOLOGY.md) |
| Which flag affects prefill/decode/VRAM | [WHAT_INFLUENCES_WHAT.md](WHAT_INFLUENCES_WHAT.md) |
| Run / rebuild / rollback / troubleshoot | [RUNBOOK.md](RUNBOOK.md) |
| Agent task: rebuild and validate automatically | [AGENT_PROMPT.md](AGENT_PROMPT.md) |
| Prefill/generation monitoring handoff for another host | [docs/monitoring-prefill-generation-handoff.md](docs/monitoring-prefill-generation-handoff.md) (RU) |
| DP2A A/B on the 3-GPU profile | [docs/cmp50hx-dp2a-df03399-result.md](docs/cmp50hx-dp2a-df03399-result.md) |
| DP2A + `-fmad=false` A/B | [docs/cmp50hx-dp2a-no-fmad-df03399-result.md](docs/cmp50hx-dp2a-no-fmad-df03399-result.md) |
| Split / ubatch / MTP placement study | [docs/cmp50hx-split-ubatch-mtp-df03399-result.md](docs/cmp50hx-split-ubatch-mtp-df03399-result.md) |
| RTX tail + MTP depth (final config) | [docs/cmp50hx-rtx-tail-mtp-df03399-result.md](docs/cmp50hx-rtx-tail-mtp-df03399-result.md) |
| Context ladders 262K/360K | [docs/cmp50hx-context-ladder-262k-360k.md](docs/cmp50hx-context-ladder-262k-360k.md) |
| Design sessions (agent-style, 360K) | [docs/cmp50hx-design-session-360k.md](docs/cmp50hx-design-session-360k.md), [docs/cmp50hx-design-sessions-go-2apps.md](docs/cmp50hx-design-sessions-go-2apps.md) |

## Caveats

- The patch is an **unmerged experimental** PR (#25834). It changes only the
  CUDA integer dot product helper; the arithmetic result is unchanged
  (byte-identical completions in every paired test).
- `-fmad=false` is a whole-binary NVCC flag. The RTX 2080 Ti is also sm_75, so
  its FP32 FMA is also split; the three-GPU net result is still strongly
  positive, but on an RTX-only or Ampere CMP system this flag can hurt.
- 368,640 context exceeds the model's native 262,144. It works (KV fits,
  speed unchanged) but quality above the native window was not measured.
- The model files (24.3 GB) are not included; download instructions and
  SHA-256 checksums are in `RUNBOOK.md`.
- RTX is the tightest card in the adopted config: 20.0-21.9 GiB of 22.5 GiB
  used depending on context size.

## License

llama.cpp is MIT-licensed; the ported patch is a modification of PR #25834
(MIT). Model weights have their own license - check the model card before
redistribution. See `LICENSE-NOTICE.md`.
