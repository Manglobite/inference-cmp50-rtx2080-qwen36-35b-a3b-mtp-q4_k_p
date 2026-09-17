# Chronology: what was tried, why, and what it produced

**English** | [Русский](CHRONOLOGY.ru.md)

This file is the short history of the project. Each step lists the reason
("why"), the action, and the measured outcome. Negative results are kept on
purpose: they save other people time.

## Phase 0 - single CMP 50HX serving (July - August 2026)

- **Why**: the host has two CMP 50HX mining cards and one RTX 2080 Ti; the
  first question was whether the CMPs are usable for local LLM serving.
- **What**: strict CMP binding was introduced (`CUDA_DEVICE_ORDER=PCI_BUS_ID`,
  `CUDA_VISIBLE_DEVICES=0`, `--device CUDA0`, `gpu-binding.json`,
  `gpu-telemetry.csv`). Small models were measured: Qwen2.5-Coder-3B Q8_0
  (95.8 tok/s decode-300), Qwen3.5-4B Q8_0 (66.9), DeepSeek-R1-8B Q4_K_M
  (29.4), Seed-Coder-8B Q5_K_M (28.5). Flash Attention mattered for long
  contexts; prompt cache worked for repeated repository prompts.
- **Outcome**: CMP cards are usable but slow; the 10 GiB limit and prefill on
  long contexts are the main constraints.

## Phase 1 - DP2A discovery and single-CMP A/B (2026-08-11)

- **Why**: CMP 50HX reports sm_75 but executes DP4A at a reduced rate; issue
  #24616 proposed replacing one DP4A with two DP2A plus PRMT shuffles
  (PR #25834, commit `c499d2f4`).
- **What**: baseline and DP2A runtimes were built from `86d86ed` with the same
  flags; alternating A/B on the isolated CMP.
- **Outcome**: DeepSeek Q4 decode +79%, Seed Q5 +77%, Qwen Q8 +2% - DP2A was
  adopted only for the Q4/Q5 profiles; the Q8 profiles kept the baseline.
  This established the test protocol used everywhere later (byte-identical
  completions, CMP binding, telemetry, five alternating pairs).
- **Artifacts**: `tools/llama-cpp/{baseline,cmp50-dp2a}` (outside this case).

## Phase 2 - the Qwen3.6-35B three-GPU target (2026-09-15)

- **Why**: the working model became Qwen3.6-35B-A3B Q4_K_P (24.3 GB), split
  across both CMPs and the RTX (`--tensor-split 1,2.25,1`), 262,144 context,
  Q8_0 K/V, Flash Attention, native MTP `n-max=1`. The existing DP2A runtime
  was built on `86d86ed`, not on the production commit `df03399`.
- **What**: the PR patch was ported to `df03399` (only context drift; 22
  insertions; ported patch `dd73bdea...`); matched baseline and DP2A runtimes
  were built under a 16 GiB memory guard.
- **Outcome**: decode-500 47.79 -> 54.44 tok/s (+13.9%), HTTP +12.9%,
  prefill unchanged (373.61 -> 373.63), repo-28k decode +12%, all completions
  byte-identical, VRAM unchanged. CMP-only DeepSeek control reproduced +69.5%.
  Production switched to DP2A (`docs/cmp50hx-dp2a-df03399-result.md`).

## Phase 3 - `-fmad=false` for CMP FP32 throttling (2026-09-16)

- **Why**: external evidence for CMP 50HX: FP32 FMA is throttled about 16x
  versus split mul+add, so `nvcc -fmad=false` should help beyond DP2A.
- **What**: a third runtime with the same patch plus
  `-DCMAKE_CUDA_FLAGS=-fmad=false`; verified that the flag survives
  `-use_fast_math` (a local nvcc probe shows FFMA=0). Three-way A/B, plus a
  CMP-only control, plus environment-knob and ubatch tests.
- **Outcome**: decode-500 47.78 -> 54.04 -> **62.17** tok/s
  (no-fmad +15.0% over DP2A, +30.1% over baseline); prefill-4k raw
  372.69 -> 431.78 (+15.7%); repo-28k decode +7.4%; CMP-only
  27.91 -> 47.27 -> **61.27** (+119.5% over baseline). `GGML_CUDA_GRAPH_OPT=1`
  (-1.5%) and `GGML_CUDA_P2P=1` (-0.5%) are neutral. ubatch 512 OOMs on the
  old split. Adopted no-fmad (`docs/cmp50hx-dp2a-no-fmad-df03399-result.md`).

## Phase 4 - split, ubatch and MTP placement (2026-09-16)

- **Why**: the CMPs were still the bottleneck; larger ubatch was expected to
  help prefill, and the MTP head placement was suspected to load a CMP.
- **What**:
  1. **MTP pin experiment**: forcing the MTP layer (`blk.40.*`) to the RTX
     with `-ot 'blk\.40\..*=CUDA1'` while the tail stayed on a CMP.
  2. **Split comparison**: `1,2.5,1`, `1,2.75,1`, `1,3,1`.
  3. **ubatch sweep** `56/64/128/256/320/384/448/512` on prefill-4k and on a
     cold 26,319-token repository prompt.
- **Outcome**:
  - MTP pin works technically but decode drops **-16.7%** with identical draft
    acceptance. `GGML_SCHED_DEBUG=1` shows the draft graph growing from 2 to
    16 scheduler splits (about +6 ms per draft step). **MTP must stay
    co-located with the tail device.**
  - `1,2.5,1` equals `1,2.25,1` and `1,2.75,1` equals `1,3,1` in discrete layer
    assignment; `1,3,1` frees about 1 GiB across the CMPs and makes ubatch 512
    fit. ubatch on `1,3,1`: prefill-4k 456/530/499/**546**/542 tok/s and repo
    387/455/432/**475**/469 for 256/320/384/448/512 -> **448 is best**.
  - Intermediate adoption: `1,3,1` + ub448 (prefill +26%, decode -1.1%).
  - `docs/cmp50hx-split-ubatch-mtp-df03399-result.md`

## Phase 5 - RTX as the tail stage and deeper MTP (2026-09-16)

- **Why**: the MTP pin failed because the draft was split across devices. If
  instead the whole tail (last layers + output head + MTP) is placed on the
  RTX by device order, the draft stays single-device and runs on the fastest
  card.
- **What**: device order `CUDA0,CUDA2,CUDA1` with `--tensor-split 1,1,2.5`;
  split sweep `1,1,3 / 1,1,2.5 / 1,1,2.25 / 1,1,2`; MTP depth sweep
  `n-max 1/2/3/4`; n-gram (`ngram-mod`) comparison on a verbatim echo prompt.
- **Outcome**: decode-500 61.28 -> **95.47** tok/s (+54% versus the previous
  production and +99% versus the original baseline), repo-28k decode 82.3,
  prefill-4k 465.8 and repo prefill 405.4 (both above the original profile).
  Best balance at `1,1,2.5`. MTP depth: 84.5 / 93.6 / **95.5** / 86.5 tok/s on
  decode-500 and 66.5 / 68.3 / 82.3 / 84.2 on repo-28k for n-max 1/2/3/4 ->
  **n-max=3** chosen (n-max=4 only wins on long context). `ngram-mod` on echo
  gives 76.1 vs 110.4 for MTP -> rejected.
  `docs/cmp50hx-rtx-tail-mtp-df03399-result.md`.

## Phase 6 - context ladders at 262K and 360K (2026-09-16)

- **Why**: production is long-context; the question was how prefill, prompt
  cache and generation behave as a session grows, and whether 360k is usable.
- **What**: ladder `hello -> 10k -> 75k -> 75k repeat` in one session and in
  two sessions with host-RAM KV offload; both repeated at ctx 368,640.
- **Outcome**: exact repeat costs 4 evaluated tokens (~100% cache); the 10k
  prefix is reused inside the 75k request (12.5%); prefill 473 tok/s at 10k,
  ~331 tok/s effective for a cold 75k (~230 s); generation ~60 tok/s at 75k
  occupied context, ~46 tok/s in the two-session steady state. 360k fits
  without layer redistribution (attention KV 2.92 -> 4.11 GiB; RTX peak
  21,940 MiB). Swap reached 3.98 GiB in the 360k two-session run.
  `docs/cmp50hx-context-ladder-262k-360k.md`.

## Phase 7 - agent-style design sessions at 360K (2026-09-16/17)

- **Why**: a practical check that the served model is useful as an agent:
  tool calling, long dialogues, a chaotic non-technical user.
- **What**: a microblog design session, then two Go applications (URL
  shortener, expense tracker) with a deliberately chaotic user; tools
  `run_sqlite`, `write_file`, `read_file`, `calc` executed by the harness.
- **Outcome**: the model stayed on task, pushed back on bad ideas, was honest
  about impossible asks, and produced parseable Go scaffolds; minor drift and
  code gaps were found (shortener never registers its redirect handler,
  expenses use a toy cookie login and mix currencies).
  `docs/cmp50hx-design-session-360k.md`,
  `docs/cmp50hx-design-sessions-go-2apps.md`.

## Final adopted configuration

```text
runtime:        llama.cpp df03399 + ported PR #25834 + -fmad=false
devices:        --device CUDA0,CUDA2,CUDA1        (RTX is the tail)
split:          --tensor-split 1,1,2.5
context:        262144 (368640 tested and usable)
cache:          K/V q8_0, Flash Attention on
MTP:            --spec-type draft-mtp --spec-draft-n-max 3
batching:       --batch-size 1024 --ubatch-size 448
prompt cache:   --cache-prompt --cache-ram 8192 --cache-idle-slots
```

Net effect versus the untouched DP4A baseline on the same rig:
decode-500 47.8 -> 95.5 tok/s (**x2.0**), prefill-4k 372.7 -> 465.8 tok/s
(**+25%**), plus working 360k context, MTP co-location and prompt cache reuse.
