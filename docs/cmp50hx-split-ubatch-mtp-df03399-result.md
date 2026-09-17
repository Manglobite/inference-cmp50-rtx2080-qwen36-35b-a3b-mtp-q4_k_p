# Layer split, ubatch and MTP placement on Qwen3.6-35B-A3B (df03399)

## Status

Completed 2026-09-16. Adopted: `--tensor-split 1,3,1` and
`--ubatch-size 448` for the 262,144-token three-GPU Qwen3.6-35B-A3B Q4_K_P
profile. The production server is intentionally stopped while the owner keeps
the host out of service for research; the launcher already contains the new
defaults.

## Questions

1. Can the native MTP head be forced onto the RTX 2080 Ti so it does not load
   the CMP cards?
2. Does shifting layers toward the RTX free CMP VRAM and allow a larger
   `--ubatch-size` at the critical 262,144 context?
3. Does a larger ubatch actually improve prefill, and what does it cost in
   decode?

## Answers

1. It can be forced with `-ot 'blk\.40\..*=CUDA1'`, but it is a clear
   regression: decode -16.7% with byte-identical output and unchanged draft
   acceptance. The mechanism is 15 extra scheduler splits per draft step.
2. Yes: `1,3,1` frees about 1 GB across the CMPs and lets `--ubatch-size 512`
   fit; `1:2.5:1` and `1:2.25:1` are the same discrete layer assignment, and
   `1:2.75:1` equals `1:3,1`.
3. Yes for prefill only: on `1,3,1`, prefill-4k rises from 456.0 (ub256) to
   545.9 tok/s (ub448); repo-28k (26,319 tokens) from 386.9 to 474.5 tok/s.
   Decode-500 changes by about -1.1%; all completions are byte-identical.

## MTP placement: what is guaranteed and what is not

- The MTP head of this GGUF is the full MoE layer `blk.40.*` (20 tensors,
  `n_layer = 40`, `n_layer_all = 41`) plus a separate context created on the
  same model; there is no second model to place.
- `--spec-draft-device` (and its aliases) is parsed but not consumed by
  `llama-server` in `df03399`; only `examples/speculative` uses it
  (`common/arg.cpp:4204`, `examples/speculative/speculative.cpp:89`). It does
  not constrain MTP. Earlier production runs that passed it were no-ops.
- `-ot/--override-tensor` uses `std::regex_search` on the tensor name and
  forces the buffer type (`llama-model-loader.cpp:1228`); with `-lv 5` it logs
  `tensor ... buffer type overridden to ...`. Pinning
  `blk\.40\..*=CUDA1` moves all 20 tensors to the RTX.
- Result of the pin (3 paired decode-500 runs):

  | Metric | Control | Pinned to CUDA1 |
  | --- | ---: | ---: |
  | draft acceptance | 231/267 = 86.52%, mean len 1.87 | identical |
  | eval time / 500 tokens | 8126 ms | 9725 ms |
  | decode | 61.4 tok/s | 51.3 tok/s (-16.7%) |
  | graphs reused | 279 | 279 |

- Scheduler dump (`GGML_SCHED_DEBUG=1`, case `dp2a-smoke-16`):
  - control MTP draft graph: 2 splits, `CPU` + `CUDA2` (the whole MTP layer and
    its inputs stay on the tail device);
  - pinned: 16 splits, `CPU` + 15 alternating `CUDA2`/`CUDA1` pieces
    (`mtp_tok_embd-40`, `norm-40`, `mtp_h_input`, `mtp_eh_proj-40`,
    `mtp_Qcur_full-40`, `leaf_*`, ...), roughly one or two nodes per split.
  - The target graph is unchanged (3 GPU splits in both cases).
- Conclusion: the slowdown is pipeline overhead (15 extra splits with
  synchronization and copies per draft step, about +6 ms per step), not draft
  quality. MTP must stay co-located with the tail device. If MTP on the RTX is
  ever wanted, the whole tail (last layers, output head, masks) must move with
  it, which is a different split design and not worth it here.

## Split shift

| Split | Layer assignment (VRAM peak CUDA0/1/2, MiB) | decode-500 | prefill-4k (ub256) |
| --- | --- | ---: | ---: |
| `1,2.25,1` (old) | 6787 / 16246 / 8685 | 61.96 (n=19) | 432.4 |
| `1,2.5,1` | 6787 / 16246 / 8685 (same assignment) | 61.65 (n=2) | 432.2 |
| `1,2.75,1` | 6739 / 17706 / 8939 | 61.10 (n=5) | 546.3 |
| `1,3,1` | 6739 / 17706 / 8939 (same assignment) | 61.28 (n=5) | 545.9 |

`1,3,1` also measured +27.4% raw prefill on repo-28k without prompt cache
(372.4 -> 474.5 tok/s) and +3% raw decode inside that case.

## ubatch sweep (split `1,3,1`)

prefill-4k raw prefill tok/s (n=2 unless noted), and repo-28k without prompt
cache (26,319 actual prompt tokens, n=2):

| ubatch | prefill-4k | repo-28k | note |
| ---: | ---: | ---: | --- |
| 256 | 456.0 | 386.9 | |
| 320 | 530.0 | 454.8 | |
| 384 | 499.4 | 431.5 | |
| 448 | **545.9** (n=2) | **474.5** (n=2) | adopted |
| 512 | 542.3 | 468.7 | fits only on `1,3,1` |

For comparison, `--ubatch-size 448` on the old `1,2.25,1` split also fits:
prefill-4k 517.8 (+19.7%), repo-28k 457.3 (+22.8%), decode-500 61.58
(-0.6%), but CUDA2 peaks at 9529 MiB (about 0.7 GiB headroom) versus 8943 MiB
on `1,3,1` (about 1.3 GiB headroom).

## Adopted configuration and cost

- `--tensor-split 1,3,1`, `--ubatch-size 448`, `--batch-size 1024`, context
  262,144 (unchanged), q8_0 K/V, Flash Attention, native MTP `n-max=1`,
  runtime `qwen36-df03399-dp2a-no-fmad`.
- Expected effect versus the previous production defaults:
  prefill-4k +26% (432.4 -> 545.9), repo-28k +27% (372.4 -> 474.5),
  decode-500 -1.1% (61.96 -> 61.28). All completions byte-identical in every
  paired run of this session.

## Method and safety

- Matched profiles differ only in `--tensor-split`, `--ubatch-size`, the MTP
  override or the binary under test; each run keeps strict CMP binding,
  `gpu-binding.json`, `gpu-telemetry.csv`, `server.log` and `result.json`.
- Alternating pairs; byte-for-byte completion equality required for every
  comparison; no CUDA error, illegal instruction or OOM in the adopted runs.
- The only deliberate failure is the earlier `--ubatch-size 512` OOM on the old
  split (preserved under `benchmarks/results/20260916-083304-...`); on `1,3,1`
  ub512 succeeds but is not faster than 448.
- Runtime environment knobs were re-confirmed neutral in the same day:
  `GGML_CUDA_GRAPH_OPT=1` -1.5%, `GGML_CUDA_P2P=1` -0.5%.

## Artifacts

All runs are under `benchmarks/results/20260916-13*` through `20260916-17*`:

- MTP pin Phase 1 (decode-500): control `134452/134756/135059/135453/135926`;
  pinned `134625/134928/135231`.
- MTP placement debug: `133813` (-lv 4), `134100` (-lv 5, nextn pattern),
  `164727` (control scheduler dump), `164852` (pinned scheduler dump).
- Split comparison (decode/prefill): `14*` runs for `1,2.5,1` and `1,3,1`.
- ubatch sweep on `1,3,1` (prefill-4k): ub256 `140943/141710`, ub320
  `141112/141842`, ub384 `141239/142009`, ub448 `141409/142139`, ub512
  `141538/142307`.
- Long-prompt ubatch validation (repo-28k, no prompt cache):
  ub256 `16*`, ub320/384/448/512 `17*`.
- Control-split ub448 comparison: `17*` (prefill-4k, decode-500, repo-28k).
- Final decode-500 medians: control n=19 (5 splits phase + 5 phase 2 + 3 final
  + 6 env-control), `1,3,1` ub448 n=5.

## Reproduce

```bash
# decision case, split 1,3,1 + ubatch 448
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-split31-ubatch.json \
  --variant ub448 --cases decode-500 --repetitions 1

# long-prompt validation without prompt cache
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-split31-ub448-nocache.json \
  --variant native-262k --cases repo-28k \
  --prompts benchmarks/prompts/repository-context.json --repetitions 1

# MTP placement diagnostic (needs -lv 5 in the profile, GGML_SCHED_DEBUG=1)
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-scheddbg-pin.json \
  --variant native-262k-scheddbg --cases dp2a-smoke-16 \
  --prompts benchmarks/prompts/dp2a-smoke-16.json --repetitions 1
```
