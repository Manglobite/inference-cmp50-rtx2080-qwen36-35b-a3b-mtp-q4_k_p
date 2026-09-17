# What influences what: parameter to effect matrix

**English** | [Русский](WHAT_INFLUENCES_WHAT.ru.md)

All numbers below were measured on the reference rig (see `HARDWARE.md`) with
Qwen3.6-35B-A3B Q4_K_P, 262,144 context, Q8_0 K/V, Flash Attention, one slot,
unless stated otherwise. "decode" is the server `eval` rate (decode-500 case),
"prefill" is the server `prompt eval` rate for a cold ~3k-token prompt
(`prefill-4k`), "repo" is the 26,319-token repository prompt without prompt
cache.

## Quick matrix

| Parameter | Affects | Does not affect | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| `GGML_CUDA_DISABLE_DP4A=ON` (PR #25834) | quantized decode (+70-80% on Q4/Q5 single CMP, +13.9% on the 3-GPU Q4 model) | prefill (MMQ path), Q8 models (~+2%) | `docs/cmp50hx-dp2a-df03399-result.md` | enable for Q4/Q5 on CMP 40/50HX |
| `nvcc -fmad=false` | CMP FP32 work: decode +15.0% over DP2A, prefill +15.7%; CMP-only control +29.6% | draft acceptance, output bytes | `docs/cmp50hx-dp2a-no-fmad-df03399-result.md` | enable together with DP2A on CMP Turing; harmful on Ampere |
| Device order = RTX tail (`CUDA0,CUDA2,CUDA1`) | decode +54% (draft and output head land on RTX, single-device draft graph) | byte-identical output | `docs/cmp50hx-rtx-tail-mtp-df03399-result.md` | use on mixed CMP+RTX rigs |
| `--tensor-split 1,1,2.5` | VRAM balance and prefill throughput; 1:2.5,1 == 1:2.25,1; 1:2.75,1 == 1:3,1 | decode within ~1% | split study doc | 1,1,2.5 with RTX tail; 1,3,1 if RTX must stay middle |
| MTP `--spec-draft-n-max` | decode: 1/2/3/4 -> 84.5/93.6/95.5/86.5 (short ctx) and 66.5/68.3/82.3/84.2 (repo-28k) | prefill | RTX-tail doc | 3 (default), 4 only for long-context-only use |
| MTP placement (`-ot blk.40.*=CUDA1` alone) | decode **-16.7%**: 16 scheduler splits per draft step | acceptance (unchanged) | split/MTP doc | never separate MTP from the tail; move the whole tail |
| `--ubatch-size` | prefill only; non-monotonic: 256/320/384/448/512 -> 456/530/499/**546**/542 tok/s on `1,3,1`; 433 best of 56-512 on `1,2.25,1`; 512 OOMs there | decode | ubatch tables in the docs | 448 on the adopted split; verify VRAM headroom |
| `--batch-size` | only the logical batch cap | decode | code review | keep 1024 |
| Context size | KV memory: 2.92 GiB at 262k -> 4.11 GiB at 360k | prefill/decode rates (measured identical) | ladder doc | 262144 native; 368640 works, RoPE extrapolation caveat |
| Prompt cache (`--cache-prompt`, `--cache-ram`, `--cache-idle-slots`) | repeat requests: 4 evaluated tokens; two-session KV offload to RAM and back | first-request cost | ladder doc | keep enabled |
| `GGML_CUDA_GRAPH_OPT=1` | nothing measurable here (-1.5%) | | no-fmad doc | skip |
| `GGML_CUDA_P2P=1` | nothing measurable here (-0.5%) | | no-fmad doc | skip |
| `--spec-type ngram-mod` | 76.1 tok/s on a code-echo prompt vs 110.4 for MTP | | RTX-tail doc | skip while MTP is available |
| `--threads` | tokenization/batching only | decode | Phase 0 notes | 4 on this 24-thread host |

## Why these knobs matter (mechanism)

1. **DP4A vs DP2A (`GGML_CUDA_DISABLE_DP4A`).** CMP 50HX exposes DP4A but
   executes it at about 33 cycles instead of the usual ~2; DP2A on the same
   card is ~2.25 cycles. The patch replaces one DP4A with two PRMT shuffles
   plus two DP2A instructions in `ggml_cuda_dp4a`, used by MMVQ decode and the
   quantized-KV FlashAttention vec dot. Prefill is unaffected because Turing
   routes quantized matmuls through MMQ, whose int8 MMA path does not call the
   helper. This is why prefill did not change while decode did.
2. **FMA throttling (`-fmad=false`).** The same CMP class executes FP32 FMA at
   about 0.43 TFLOPS while separate mul+add reach about 6.88 TFLOPS. `-fmad=false`
   stops NVCC from contracting mul+add into FMA. On normal GPUs this doubles
   the FP32 instruction count and can hurt; on the RTX stage here the decode is
   memory-bound so the measured net is still positive. The flag must be passed
   to NVCC at build time (`-DCMAKE_CUDA_FLAGS=-fmad=false`), not at runtime,
   and it wins even when `-use_fast_math` appears later on the command line.
3. **Device order and tail placement.** In layer split every token traverses
   all stages in order, and the tail device computes the output head and (for
   this model) the MTP layer. When the tail is the RTX, the MTP draft graph is
   single-device, so the draft step runs entirely on the fastest card with no
   extra split; when the tail is a CMP, the draft runs on that CMP. Forcing the
   MTP tensors to the RTX while the tail stayed on a CMP splits the draft graph
   into 16 pieces and loses 16.7%.
4. **ubatch.** Only prefill uses large physical batches; decode runs with 1-2
   tokens per step. Larger ubatch improves kernel utilization but increases
   compute buffers, so it competes with KV memory on the 10 GiB CMPs. The
   measured curve is non-monotonic (kernel/config thresholds), so sweep it on
   your own hardware instead of copying a number.
5. **MTP depth.** Deeper drafts cost a little more per step but can accept more
   tokens per step. Acceptance falls (82% -> 71% -> 57% mean draft length
   1.8 -> 3.1 -> 3.3 from n-max 1 to 4) and the optimum depends on context
   length: n-max=3 at short context, n-max=4 on long context.
6. **Context and KV.** The model is hybrid (11 of 41 layers use full attention;
   the rest are linear attention with a fixed recurrent state). Only the 11
   attention layers scale KV with context: 2.92 GiB at 262k, 4.11 GiB at 360k
   for Q8_0 K/V. That is why 360k fits without changing the split.

## Tests that were conducted

| Test | Purpose | Method | Where |
| --- | --- | --- | --- |
| Deterministic smoke | prove the patch does not change math | 128-token request, temperature 0, byte-for-byte comparison | `docs/cmp50hx-dp2a-*.md` |
| Alternating A/B | fair throughput comparison | 3-5 alternating cycles per variant, one server per run | all result docs |
| Single-CMP control (DeepSeek Q4) | isolate the CMP effect from the RTX | same protocol on `CUDA_VISIBLE_DEVICES=0`, RTX idle | DP2A/no-fmad docs |
| ubatch sweeps | find the prefill optimum and the OOM edge | `prefill-4k` and cold `repo-28k`, 2 points per value | split/ubatch doc |
| split sweeps | balance layers and free VRAM | same cases, different `--tensor-split` | split and RTX-tail docs |
| MTP depth and placement | maximize speculative decode | decode-500 and repo-28k, acceptance from logs | RTX-tail doc |
| Scheduler diagnostics | explain the MTP pin regression | `GGML_SCHED_DEBUG=1` + `-lv 5`, count split sections | split/MTP doc |
| Context ladders | prompt cache, prefill, generation vs context | hello -> 10k -> 75k -> repeat, one and two sessions, 262k/360k | ladder doc |
| Agent/design sessions | practical usefulness and tool use | scripted dialogues with deterministic tool emulation | design-session docs |

## How to measure the same things on your hardware

1. Always bind by PCI bus order and keep telemetry; record raw server timings
   (`prompt eval time`, `eval time`) plus end-to-end HTTP.
2. For every comparison require byte-identical completions at temperature 0;
   a throughput win that changes output is a different experiment.
3. Change one axis at a time; alternate A and B within one session instead of
   running all A and then all B.
4. Sweep ubatch on your own rig: it is the most hardware-specific number here.
5. Check VRAM headroom after each change; the tightest card is the one that
   will OOM under a longer prompt.
