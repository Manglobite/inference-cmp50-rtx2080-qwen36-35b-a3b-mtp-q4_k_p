# DP2A on Qwen3.6-35B-A3B three-GPU profile: A/B result (df03399)

**English** | [Русский](cmp50hx-dp2a-df03399-result.ru.md)

## Status

Completed 2026-09-15. DP2A is accepted for the tested Qwen3.6-35B-A3B
Q4_K_P three-GPU profile. This document concludes
`cmp50hx-dp2a-ab-handoff.md`; it does not change the single-CMP DeepSeek/Seed
decision from 2026-08-11 or the two old packaged runtimes under
`tools/llama-cpp/`.

> **2026-09-16 update: superseded in production by DP2A + `--fmad=false`**
> (`docs/benchmarks/cmp50hx-dp2a-no-fmad-df03399-result.md`, +15.0% decode over
> DP2A). The DP2A runtime remains packaged as the intermediate rollback step.

## Question

Does replacing DP4A with the PR #25834 DP2A workaround in llama.cpp improve
real decode throughput of the active production-shaped Qwen3.6-35B-A3B Q4_K_P
layer-split profile without changing output, VRAM or stability?

Answer: yes. Median raw decode improved by 12.0-14.1% depending on case, HTTP
throughput by 6.1-12.9%, prompt eval was unchanged, sampled VRAM was identical
and every paired completion was byte-for-byte equal.

## Provenance

- Upstream llama.cpp commit: `df03399b885831b2a1603b3abb0d8c156808e363`
  (source worktree `research/qwen38-27b-autonomous-20260910/llama.cpp-upstream`).
- PR #25834 pinned patch (upstream `86d86ed`): SHA-256
  `641ba95eb0649c04759e6cdfbcaef4b99146b99efce569d9d4dd0d7019a450b2`.
  It does not apply cleanly on `df03399`; only context drift was adapted.
- Ported patch: `tools/llama-cpp/qwen36-df03399-dp2a/patches/25834-df03399-port.patch`,
  SHA-256 `dd73bdea36f9823c507918a997dbd279c1dff7a8d36cf0408d4151f4f2bf81d0`
  (4 files, 22 insertions: CMake option, CUDA compile definition,
  `ggml_cuda_dp4a` DP2A+PRMT path, build.md row).
- Runtimes (production flags `GGML_CUDA=ON`, `GGML_CUDA_NCCL=ON`, `Release`,
  `sm_75`, `CMAKE_BUILD_RPATH_USE_ORIGIN=ON`; DP2A adds
  `GGML_CUDA_DISABLE_DP4A=ON`):
  - `tools/llama-cpp/qwen36-df03399-baseline/` (manifest, hashes, README);
  - `tools/llama-cpp/qwen36-df03399-dp2a/` (manifest, hashes, README).
- Both builds report `version: 0.4.0-dev (build 1, commit df03399)`; NVCC
  12.4.131, CMake 4.2.3. `libggml-cuda.so.0.23.0` differs between the variants,
  confirming the option is compiled in. Both `ldd` and `RUNPATH=$ORIGIN`
  resolve from their own `bin/`; no `not found`.
- Build guard: serial `systemd-run --user` units with `MemoryMax=16G`,
  `MemorySwapMax=0`, `--parallel 12`; peaks 3.9 GiB each, zero swap.
- DeepSeek-R1-0528-Qwen3-8B Q4_K_M was re-downloaded to reproduce the
  single-CMP control; SHA-256
  `a86349a4180c4e6bb43f874c29c404fa2be3f90b15509bd6d86f697dba724ec1`,
  size 5,027,785,216 B (matches the 2026-07 findings).

## Method

- Profiles (only name, binary, build variant and port differ inside a pair):
  - `benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-{baseline,dp2a}.json`:
    exact live production argv for the model (three GPUs, `--device
    CUDA0,CUDA1,CUDA2`, `--split-mode layer`, `--tensor-split 1,2.25,1`,
    `-ngl all`, `--fit off`, q8_0 K/V, Flash Attention, 262,144 context, one
    slot, native MTP `--spec-draft-n-max 1`, prompt cache, reasoning on).
  - `benchmarks/profiles/llama-cpp-deepseek-r1-qwen3-8b-q4-cmp50hx-df03399-{baseline,dp2a}.json`:
    single isolated CMP, 32K, q8_0 K/V, Flash Attention, no MTP, reasoning off.
- Harness `benchmarks/scripts/run.py` with strict binding
  (`CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA_VISIBLE_DEVICES`, `--device`), one
  server per invocation, warm-up request, `--repetitions 1`, alternating
  `baseline -> DP2A` pairs. Every run saved `gpu-binding.json`,
  `gpu-telemetry.csv`, `environment.json`, `build-variant.json`, `server.log`
  and `result.json` with the raw llama.cpp timings.
- CMP binding: CMPs at `00000000:03:00.0` and `00000000:08:00.0`, RTX at
  `00000000:04:00.0`. During the DeepSeek control the RTX stayed at 1 MiB.
- Before the window `inference-hub` idle GPU clock lock was disabled
  (`idleAfterSeconds=0`) and clocks were reset; both were restored afterwards.
  The live Qwen3.6 server was stopped through the hub API and started again
  after the measurements; downtime was about 20 minutes.

## Results

Raw `eval` is llama.cpp server decode tokens/s; HTTP is end-to-end completion
throughput. This revision does not log `n_decoded`/`tg`, so `eval` is the raw
decode metric. Medians of five (Qwen) or three (DeepSeek) paired runs.

### Qwen3.6-35B-A3B Q4_K_P, three GPUs (decision target)

| Case | Metric | Baseline | DP2A | Delta |
| --- | --- | ---: | ---: | ---: |
| decode-500 | raw eval tok/s | 47.79 | 54.44 | **+13.92%** |
| decode-500 | HTTP tok/s | 44.508 | 50.234 | +12.86% |
| prefill-4k | raw prefill tok/s | 373.61 | 373.63 | +0.01% |
| prefill-4k | raw decode tok/s | 52.23 | 59.57 | +14.05% |
| prefill-4k | HTTP tok/s | 11.672 | 11.981 | +2.64% |
| repo-28k | raw decode tok/s | 44.08 | 49.37 | +12.00% |
| repo-28k | HTTP tok/s | 22.406 | 23.760 | +6.05% |

Per-run raw eval (tok/s), baseline then DP2A per pair:

- decode-500: 42.87/47.97/47.79/47.90/47.72 vs
  53.93/54.76/54.43/54.44/54.78.
- prefill-4k: 51.73/52.23/52.49/52.37/51.61 vs
  59.57/58.95/59.71/58.15/59.81.
- repo-28k: 43.88/44.26/43.98/44.08/44.32 vs
  49.50/49.36/49.77/49.28/49.37.

The first baseline decode-500 point (42.87) is a cold first-run outlier; the
median is robust and the remaining baseline points are 47.7-48.0.

### DeepSeek-R1-Qwen3-8B Q4_K_M, single isolated CMP (port control)

| Metric | Baseline | DP2A | Delta |
| --- | ---: | ---: | ---: |
| decode-500 raw eval tok/s | 27.95 | 47.38 | **+69.52%** |
| decode-500 HTTP tok/s | 27.157 | 44.997 | +65.69% |

This reproduces the previously accepted single-CMP DP2A behavior on the new
commit (`86d86ed` result was about +79%) and proves the port preserves the
intended workaround.

## Correctness, VRAM and stability

- All 18 measured pairs (3 DeepSeek, 5 Qwen decode, 5 Qwen prefill, 5 Qwen
  repo) returned byte-for-byte identical completions with equal
  prompt/completion token counts and finish reasons.
- The two deterministic 128-token smoke pairs (DeepSeek and Qwen) were also
  identical; DeepSeek raw eval 27.94 -> 48.20 tok/s in the smoke.
- Sampled peak VRAM is unchanged: Qwen GPUs `6787 / 16246 / 8685 MiB`
  (CUDA0/CUDA1/CUDA2) for both variants; DeepSeek CMP `7261 MiB` for both.
- No `server.log` contains a CUDA error, illegal instruction, assertion,
  OOM, segfault or fallback. Kernel journal had no OOM/Xid events.
- The `repo-28k` prompt-eval figure is not a clean prefill comparison because
  the production profile enables `--cache-prompt` and the warm-up populated the
  cache; `prefill-4k` (3082 actual prompt tokens) is the prefill control.

## Artifacts

- DeepSeek smoke: `20260915-215123-*baseline-latency-32k-q8kv`,
  `20260915-215208-*dp2a-latency-32k-q8kv`.
- DeepSeek decode-500 pairs: `20260915-215245`, `215331`; `215408`, `215454`;
  `215532`, `215617`.
- Qwen smoke: `20260915-213057-*baseline-native-262k`,
  `20260915-213235-*dp2a-native-262k`.
- Qwen decode-500 pairs: `20260915-213422`, `213604`; `213739`, `213914`;
  `214047`, `214223`; `214356`, `214531`; `214705`, `214840`.
- Qwen prefill-4k pairs: `20260915-215717`, `215947`; `220127`, `220302`;
  `220436`, `220611`; `220745`, `220919`; `221054`, `221228`.
- Qwen repo-28k pairs: `20260915-221402`, `221652`; `221941`, `222231`;
  `222520`, `222810`; `223059`, `223349`; `223639`, `223929`.
- Preserved failed run from the same session:
  `20260915-213003-*baseline-latency-32k-q8kv` (DeepSeek GGUF was absent at
  that moment; kept, not deleted).

## Decision

- **Adopt DP2A for the Qwen3.6-35B-A3B Q4_K_P three-GPU profile.** It exceeds
  the 10% median decode threshold with no correctness, VRAM, prefill or
  stability regression.
- Activated in production on 2026-09-15: the hub-managed profile
  `run-commands/actual/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native.sh`
  now defaults `LLAMA_SERVER` to
  `tools/llama-cpp/qwen36-df03399-dp2a/bin/llama-server`. The service was
  stopped and started through the hub API; `/health` returned 200 after about
  85 s, the hub backend reports the DP2A binary as `healthy`, and a live
  inference smoke returned `2 + 2 = 4` with `finish_reason=stop`.
- Rollback: the baseline runtime remains packaged, and
  `run-commands/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native-baseline.sh`
  plus the `LLAMA_SERVER=<baseline path>` override restore DP4A without a
  rebuild.
- The activated launcher follows the script as edited before the test, which
  does not set `--spec-draft-device CUDA1`; the benchmarked argv did set it.
  This is a placement difference only, and the tested placement was the
  pessimistic one for the RTX DP2A path, so the accepted gain is expected to
  carry over at least.
- Do not generalize this result to other quantizations or profiles. The Q8
  single-CMP result from 2026-08-11 remained below the threshold, and the RTX
  2080 Ti also runs the DP2A kernels because the option is compile-time
  binary-wide; the measured three-GPU gain is the net of both CMPs and the RTX
  stage. The result is therefore conservative for CMP-only deployments.

## Caveats

- The tested benchmark argv contains `--spec-draft-device CUDA1`, which the
  live launcher script no longer sets (the script was edited after the live
  server was started). The comparison is an intrinsic kernel difference; the
  measured profile placed the MTP draft head on the RTX, which is the
  pessimistic placement for the RTX DP2A path.
- This is a `df03399` research result, not an upstream recommendation. PR
  #25834 is still unmerged; the local port must be rebased for any later
  commit.
- Qwen3.6 `content` fields are often empty in short runs because reasoning
  consumes the budget; correctness is established by byte equality, token
  counts and finish reasons, plus the DeepSeek control.

## Reproduce

```bash
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-baseline.json \
  --variant native-262k --cases decode-500 --repetitions 1

python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

Builds: CMake configure from the `df03399` worktree with the flags above and
`cmake --build <dir> --target llama-server` inside the memory-guarded
`systemd-run` unit.
