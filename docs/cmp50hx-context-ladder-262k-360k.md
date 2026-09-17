# Context ladder study 262K / 360K on Qwen3.6-35B-A3B (RTX-tail, MTP n-max=3)

## Status

Completed 2026-09-16. Server configuration: `--device CUDA0,CUDA2,CUDA1`,
`--tensor-split 1,1,2.5`, `--ubatch-size 448`, MTP `n-max=3`, no-fmad runtime.
The host stays out of service for research; all harness servers were stopped
after the runs.

## Setup

- Ladder prompts are generated from the repository corpus
  (`benchmarks/scripts/build_context_ladder.py`,
  `benchmarks/prompts/context-ladder.json`): `hello` (13 tokens),
  `context-10k` (9,897 target / 9,907 with chat template), `context-75k`
  (74,999 / 75,009). They contain the same corpus prefix, so a 75k request also
  exercises partial prefix reuse of the 10k request.
- Steps: `context-ladder-steps-test1.json` (one session: hello, 10k, 75k, 75k)
  and `context-ladder-steps-test2.json` (two sessions: A hello/10k/75k/75k,
  B hello/10k/75k/75k, then A and B 75k again).
- Runner: `benchmarks/scripts/run_context_ladder.py`; host/GPU telemetry:
  `benchmarks/scripts/host_telemetry.py` (0.5 s: CPU load/temp, RAM, swap, and
  per-GPU temp/util/mem/power). Raw timing, slot id and draft acceptance are
  parsed from `server.log`.
- 360K runs use context 368,640. The model was trained at 262,144; positions
  beyond that use RoPE extrapolation and quality was not measured here.

## Decode and cache results

`pref_eval` is the raw prompt-eval rate for the tokens actually evaluated;
`eff_prefill` is the full prompt (75,009 tokens) divided by the whole prompt
eval time, i.e. the user-visible prefill throughput; `cache` is the fraction of
the prompt served from the prompt cache.

### Test 1, one session, ctx 262,144 and ctx 368,640

| step | case | prompt | evaluated | cache | pref_eval t/s | eff_prefill t/s | gen t/s | acc len | wall s |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | hello | 13 | 13 | 0% | 29.8 | 29.8 | 95.91 | n/a | 1.1 |
| 2 | 10k | 9,907 | 9,907 | 0% | 472.5 | 472.5 | 102.30 | n/a | 22.6 |
| 3 | 75k | 75,009 | 65,618 | 12.5% | 289.6 | 331.1 | 60.47 | n/a | 229.6 |
| 4 | 75k repeat | 75,009 | 4 | ~100% | 3.9 | - | 60.53 | n/a | 6.9 |
| 1 | hello (360k) | 13 | 13 | 0% | 30.1 | 30.1 | 97.36 | 3.44 | 1.1 |
| 2 | 10k (360k) | 9,907 | 9,907 | 0% | 473.0 | 473.0 | 100.73 | 3.63 | 22.6 |
| 3 | 75k (360k) | 75,009 | 65,618 | 12.5% | 289.4 | 330.8 | 59.77 | 3.17 | 229.8 |
| 4 | 75k repeat (360k) | 75,009 | 4 | ~100% | 3.7 | - | 59.27 | 3.17 | 7.0 |

Acceptance for Test 1 was recorded from step 3 onward after a parser fix; the
3.1-3.6 mean draft length is stable across both context sizes.

### Test 2, two sessions with host-RAM prompt cache (`--parallel 2`)

| step | session | case | prompt | evaluated | cache | pref_eval t/s | eff_prefill t/s | gen t/s | acc len | wall s |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | A | hello | 13 | 13 | 0% | 30.7 | 30.7 | 95.70 | 3.44 | 1.1 |
| 2 | A | 10k | 9,907 | 9,907 | 0% | 472.7 | 472.7 | 102.82 | 3.63 | 22.6 |
| 3 | A | 75k | 75,009 | 75,009 | 0% | 305.9 | 305.9 | 59.99 | 3.17 | 248.3 |
| 4 | A | 75k | 75,009 | 65,618 | 12.5% | 195.0 | 222.9 | 58.90 | 3.26 | 343.0 |
| 5 | B | hello | 13 | 13 | 0% | 40.3 | 40.3 | 104.76 | 3.44 | 4.7 |
| 6 | B | 10k | 9,907 | 9,907 | 0% | 473.2 | 473.2 | 100.01 | 3.53 | 22.3 |
| 7 | B | 75k | 75,009 | 4 | ~100% | 3.8 | - | 59.04 | 3.26 | 7.0 |
| 8 | B | 75k | 75,009 | 4 | ~100% | 3.7 | - | 46.65 | 3.26 | 10.4 |
| 9 | A | 75k | 75,009 | 4 | ~100% | 3.8 | - | 45.81 | 3.10 | 10.5 |
| 10 | B | 75k | 75,009 | 4 | ~100% | 3.8 | - | 45.48 | 3.17 | 10.4 |

Same shape at ctx 368,640: B restored the shared 75k prompt from host-RAM
cache with 4 evaluated tokens; the steady two-session generation was 45.4-46.1
t/s versus 58.3-59.0 for the first cached generation.

## Telemetry per run (maxima over 500 ms samples)

| run | CPU | CPU temp | RAM peak | swap peak | CMP0 (temp/util/mem/power) | RTX (temp/util/mem/power) | CMP2 (temp/util/mem/power) |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| Test 1, 262k | 20% | 47 C | 9.7 GiB | 1.27 GiB | 49 C / 100% / 7,373 MiB / 147 W | 55 C / 100% / 20,026 MiB / 283 W | 49 C / 100% / 6,679 MiB / 129 W |
| Test 2, 262k | 20% | 50 C | 10.6 GiB | 1.38 GiB | 50 C / 100% / 7,439 MiB / 148 W | 57 C / 100% / 20,156 MiB / 287 W | 50 C / 100% / 6,737 MiB / 129 W |
| Test 1, 360k | 19% | 50 C | 10.4 GiB | 1.39 GiB | 50 C / 100% / 8,221 MiB / 148 W | 58 C / 100% / 21,940 MiB / 289 W | 51 C / 100% / 7,527 MiB / 130 W |
| Test 2, 360k | 24% | 52 C | 9.8 GiB | **3.98 GiB** | 51 C / 100% / 8,287 MiB / 148 W | 59 C / 100% / 21,820 MiB / 286 W | 51 C / 100% / 7,585 MiB / 130 W |

## Findings

1. **Prompt cache works exactly.** Repeating the same 75k prompt costs 4
   evaluated tokens (~100% hit) and only the generation wall time: 6.9 s for
   Test 1 versus 229.6 s for the cold prefill.
2. **Prefix reuse works partially.** The 75k prompt shares the 10k corpus
   prefix; in single-session mode 9,391 tokens were reused (12.5% of 75k),
   raising effective prefill from 289.6 to 331.1 t/s. In two-session mode slot
   alternation can skip that prefix, which is why step 3 of Test 2 evaluated
   the full 75,009 tokens.
3. **Host-RAM KV cache restore works across sessions.** In Test 2 the second
   session B reused A's 75k state (4 evaluated tokens) without recompute, and
   later A/B repeats did the same after slot churn.
4. **Effective prefill**: ~473 t/s for 10k; ~331 t/s and ~331 s wall for a cold
   75k in single-session mode (75k × 0.29 ms/token plus attention growth).
   Context 360k does not change these rates.
5. **Generation**: 96-103 t/s at short context, ~60 t/s at 75k occupied
   context in single-session mode. In the two-session steady state it settles
   at ~45.5 t/s (-23% versus the first cached generation), with unchanged
   acceptance (mean draft length 3.1-3.3). The cause was not isolated here;
   thermal/power telemetry shows no throttling (RTX 57-59 C, 286-289 W), so
   this is likely server/KV handling with two live 75k states rather than the
   GPUs.
6. **360K fits without layer redistribution.** KV grows by ~1.2 GiB (2.92 ->
   4.11 GiB of attention KV); the adopted `1,1,2.5` split absorbs it. Sampled
   peaks: CMP0 8,287, RTX 21,940, CMP2 7,585 MiB. RTX headroom falls to about
   0.6 GiB, so 360k is viable but tight. The model's trained context is
   262,144; RoPE extrapolation quality above that was not measured.
7. **Host pressure at 360k with two slots**: swap reached 3.98 GiB of 4 GiB
   (`--cache-ram 8192` plus two 75k states and checkpoints). CPU load stayed
   below 25% and below 52 C in every run.

## Artifacts

- Test 1, 262k:
  `benchmarks/results/20260916-214800-*ladder-262k-p1-test1/`
- Test 2, 262k:
  `benchmarks/results/20260916-215357-*ladder-262k-p2-test2/`
- Test 1, 360k:
  `benchmarks/results/20260916-220700-*ladder-360k-p1-test1-360k/`
- Test 2, 360k:
  `benchmarks/results/20260916-221259-*ladder-360k-p2-test2-360k/`

Each directory contains `result.json`, `server.log`, `host-telemetry.csv`,
`gpu-binding.json`, `build-variant.json` and the copied steps/prompt documents.

## Reproduce

```bash
python3 benchmarks/scripts/run_context_ladder.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-262k-p1.json \
  --variant native \
  --steps benchmarks/prompts/context-ladder-steps-test1.json \
  --prompts benchmarks/prompts/context-ladder.json \
  --label test1
```
