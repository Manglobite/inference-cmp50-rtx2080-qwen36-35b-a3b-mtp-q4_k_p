# DP2A + `--fmad=false` on Qwen3.6-35B-A3B: A/B result (df03399)

**English** | [Русский](cmp50hx-dp2a-no-fmad-df03399-result.ru.md)

## Status

Completed 2026-09-16. Accepted and activated in production for the tested
three-GPU Qwen3.6-35B-A3B Q4_K_P profile. This document concludes the
`--fmad=false` follow-up item from `cmp50hx-next-session-handoff.md` and
supersedes `cmp50hx-dp2a-df03399-result.md` as the production default.

> **Same-day follow-up:** `--tensor-split 1,3,1` and `--ubatch-size 448` were
> then adopted on top of this runtime for the critical 262,144 context
> (prefill +26%, decode -1.1%). See
> `docs/benchmarks/cmp50hx-split-ubatch-mtp-df03399-result.md`.

## Question

Does adding the nvcc `-fmad=false` flag to the already accepted DP2A runtime
improve decode on the mixed three-GPU profile without changing output, VRAM or
stability, and how much of the effect comes from the two CMP 50HX cards?

Answers:

- Yes: median decode-500 improved by 15.0% over DP2A and 30.1% over baseline.
- The CMP-only control shows +29.6% over DP2A (+119.5% over baseline), so the
  two CMP stages gain much more; the RTX 2080 Ti stage dilutes the net gain
  because it also runs split FMAs.
- Output stayed byte-identical in every paired run and sampled VRAM did not
  change. Two runtime environment knobs (`GGML_CUDA_GRAPH_OPT=1`,
  `GGML_CUDA_P2P=1`) were neutral, and `--ubatch-size 512` runs out of VRAM.

## Provenance

- Source commit: `df03399b885831b2a1603b3abb0d8c156808e363`.
- Patch: the same ported PR #25834 patch as the DP2A runtime, SHA-256
  `dd73bdea36f9823c507918a997dbd279c1dff7a8d36cf0408d4151f4f2bf81d0`.
- Runtime: `tools/llama-cpp/qwen36-df03399-dp2a-no-fmad/` (manifest, hashes,
  README). Build options are identical to `qwen36-df03399-dp2a` plus
  `-DCMAKE_CUDA_FLAGS=-fmad=false`.
- Flag verification: `ggml/src/ggml-cuda/.../flags.make` starts with
  `-fmad=false`; a local nvcc probe showed that `-fmad=false` suppresses FFMA
  generation (FFMA=0, FMUL/FADD emitted) even when `-use_fast_math` appears
  later on the command line, which is the case in this build. The packaged
  `libggml-cuda.so` differs from both the baseline and the DP2A builds.
- Build guard: serial `systemd-run --user` unit with `MemoryMax=16G`,
  `MemorySwapMax=0`, `--parallel 12`; completed in 7m32s, peak 3.8 GiB,
  zero swap. NVCC 12.4.131, CMake 4.2.3.

## Method

- Profiles: the three matched Qwen3.6 profiles differ only in name, binary and
  build variant (`...-3gpu-df03399-baseline`, `...-dp2a`,
  `...-dp2a-no-fmad`), all `native-262k`: 262,144 context, one slot, q8_0 K/V,
  Flash Attention, native MTP `n-max=1`, `--tensor-split 1,2.25,1`.
- The DeepSeek-R1-Qwen3-8B Q4_K_M CMP-only pair plus its no-fmad sibling
  (`latency-32k-q8kv`, 32K, single isolated CMP) isolate the CMP stage.
- Test 1: alternating `baseline -> DP2A -> no-fmad` cycles, five cycles for
  `decode-500`, three for `prefill-4k` and `repo-28k`, three for the DeepSeek
  control.
- Test 2: environment-only A/B on the no-fmad runtime, three cycles per knob,
  `decode-500`.
- Test 3: `--ubatch-size` sweep on `prefill-4k` only, two repetitions per
  value.
- Same binding, telemetry, artifact and restore rules as the previous A/B. The
  production server was stopped through the hub, `idleAfterSeconds` was set to
  0 and GPU clocks were reset for the window, then everything was restored.

## Results

Raw `eval` is the llama.cpp server decode tokens/s; HTTP is end-to-end
completion throughput.

### Qwen3.6-35B-A3B Q4_K_P, three GPUs (decision target, n=5)

| Metric | Baseline | DP2A | DP2A+no-fmad | no-fmad vs DP2A |
| --- | ---: | ---: | ---: | ---: |
| decode-500 raw eval tok/s | 47.78 | 54.04 | **62.17** | **+15.04%** |
| decode-500 HTTP tok/s | 44.487 | 49.873 | 56.762 | +13.81% |
| vs baseline | - | +13.10% | **+30.12%** | - |

Per-run raw eval (tok/s): baseline 46.17/47.78/47.93/47.92/47.40; DP2A
53.87/54.53/54.17/54.03/54.04; no-fmad 62.17/62.33/61.59/61.96/62.23.

### Qwen3.6-35B-A3B Q4_K_P, prefill-4k (n=3)

| Metric | Baseline | DP2A | DP2A+no-fmad | no-fmad vs DP2A |
| --- | ---: | ---: | ---: | ---: |
| raw prefill tok/s | 372.690 | 373.290 | **431.780** | **+15.67%** |
| raw decode tok/s | 52.080 | 59.360 | 65.260 | +9.94% |
| HTTP tok/s | 11.647 | 11.987 | 13.623 | +13.65% |

Prefill also accelerates: the FMA-sensitive FP32 work in prefill benefits from
the split mul+add path on the CMP cards.

### Qwen3.6-35B-A3B Q4_K_P, repo-28k (n=3)

| Metric | Baseline | DP2A | DP2A+no-fmad | no-fmad vs DP2A |
| --- | ---: | ---: | ---: | ---: |
| raw decode tok/s | 43.900 | 49.130 | **52.770** | **+7.41%** |
| HTTP tok/s | 21.427 | 23.651 | 24.421 | +3.26% |
| vs baseline | - | +11.91% | +20.21% | - |

The repo-28k prompt is served from the prompt cache in this profile
(prompt eval ~4 tokens), so it is a decode-only point; `prefill-4k` above is the
prefill control.

### DeepSeek-R1-Qwen3-8B Q4_K_M, single isolated CMP (n=3)

| Metric | Baseline | DP2A | DP2A+no-fmad | no-fmad vs DP2A |
| --- | ---: | ---: | ---: | ---: |
| decode-500 raw eval tok/s | 27.91 | 47.27 | **61.27** | **+29.62%** |
| decode-500 HTTP tok/s | 27.114 | 44.962 | 58.289 | +29.65% |
| vs baseline | - | +69.37% | **+119.53%** | - |

This confirms the external CMP 50HX reports and isolates the source of the
gain: the CMP stage is almost 2.2x faster than baseline with DP2A+no-fmad.

### Test 2: environment knobs on the no-fmad runtime (n=3, decode-500)

| Knob | raw eval median | vs control |
| --- | ---: | ---: |
| control (no-fmad) | 61.96 | - |
| `GGML_CUDA_GRAPH_OPT=1` | 61.05 | -1.47% |
| `GGML_CUDA_P2P=1` | 61.64 | -0.52% |

Both are neutral within noise. No adoption.

### Test 3: `--ubatch-size` sweep, prefill-4k raw prefill tok/s

| ubatch | raw prefill tok/s | note |
| ---: | ---: | --- |
| 56 | 238.98 | n=2 |
| 64 | 258.61 | n=2 |
| 128 | 270.36 | n=2 |
| 256 | **432.56** | n=4, production value |
| 512 | - | CUDA OOM on CMP during prefill |

Larger ubatch is clearly better on this mixed rig; the production default 256 is
the best tested and the largest value that fits the 10 GiB CMP cards. The
`ub512` failure is preserved at
`benchmarks/results/20260916-083304-llama.cpp-qwen36-df03399-dp2a-no-fmad-ub512/`.

## Correctness, VRAM and stability

- All 21 measured pairs (3 smoke pairs plus 5+3+3 Qwen and 3+3 DeepSeek
  performance pairs, and the neutral env runs) returned byte-for-byte identical
  completions with equal token counts and finish reasons.
- Sampled peak VRAM is unchanged across variants: Qwen `6787 / 16246 / 8685 MiB`
  (CUDA0/CUDA1/CUDA2) and DeepSeek `7261 MiB` on the CMP.
- No server log contains a CUDA error, illegal instruction, assertion or
  segfault except the deliberate `ub512` OOM. No kernel OOM/Xid events.

## Activation

- The hub-managed production profile
  `run-commands/actual/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native.sh`
  now defaults to
  `tools/llama-cpp/qwen36-df03399-dp2a-no-fmad/bin/llama-server`.
- Restart through the hub API: `/health` 200 after about 90 s, backend reports
  the no-fmad binary as `healthy`, live smoke returned `2 + 2 = 4` with
  `finish_reason=stop`; `idleAfterSeconds=300` was restored.
- Rollback: baseline DP4A launcher
  `run-commands/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native-baseline.sh`,
  or point `LLAMA_SERVER` at the DP2A runtime `qwen36-df03399-dp2a` for an
  intermediate step. Both runtimes stay packaged.

## Caveats

- `--fmad=false` is a whole-binary flag; the RTX 2080 Ti is also sm_75 and
  therefore also executes split FMAs. The mixed-profile gain (+15.0%) is much
  smaller than the CMP-only gain (+29.6%). Per-device selection is impossible
  by architecture alone and would require per-device kernel variants.
- The patch and the flag are local research artifacts, not upstream. PR #25834
  is still unmerged; any later commit requires a rebase and a new matched pair.
- Q8_0 was not re-tested here. External reports say DP2A does not help Q8_0 and
  `fmad` affects FP32 work rather than dp4a, so no Q8 benefit is claimed.
- `--ubatch-size 512` is not viable on this hardware; keep 256.
- Do not generalize to other quantizations, profiles or Ampere CMP cards
  (`fmad=false` makes FP32 about 2x slower on Ampere and CMP 90HX).

## Artifacts

All run directories are under `benchmarks/results/20260916-*`:

- Smoke (dp2a-smoke-128): `063650` baseline, `063859` DP2A, `064030` no-fmad
  (Qwen); `064209` baseline, `064302` DP2A, `064332` no-fmad (DeepSeek).
- Qwen decode-500 cycles: baseline `064420/064930/065412/065854/070337`, DP2A
  `064618/065105/065547/070029/070513`, no-fmad
  `064757/065239/065721/070204/070648`.
- Qwen prefill-4k: baseline `070843/071325/071808`, DP2A
  `071018/071500/071943`, no-fmad `071152/071635/072117`.
- Qwen repo-28k: baseline `072250/073113/073935`, DP2A
  `072541/073404/074227`, no-fmad `072832/073655/074516`.
- DeepSeek control: baseline `074822/075033/075230`, DP2A
  `074920/075118/075316`, no-fmad `074958/075156/075353`.
- Test 2: no-fmad control runs `075454/075940/080313/080623/080930/081237`,
  GRAPH_OPT `075802/080138/080448`, P2P `080756/081103/081411`.
- Test 3: ub128 `081802/082430`, ub256 `081627/082256/082943/083116`, ub56
  `081940/082608`, ub64 `082118/082746`.
- Failed `ub512` run preserved at `083304-...-ub512`.

## Reproduce

```bash
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a.json \
  --variant native-262k --cases decode-500 --repetitions 1

python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

Build: configure the `df03399` worktree with the DP2A patch and
`-DCMAKE_CUDA_FLAGS=-fmad=false` next to the production flags, then
`cmake --build <dir> --target llama-server` inside the memory-guarded
`systemd-run` unit.
