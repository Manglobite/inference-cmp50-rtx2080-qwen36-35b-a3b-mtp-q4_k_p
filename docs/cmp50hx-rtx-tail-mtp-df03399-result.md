# RTX as the tail stage with deeper MTP on Qwen3.6-35B-A3B (df03399)
**English** | [Русский](cmp50hx-rtx-tail-mtp-df03399-result.ru.md)

## Status

Completed 2026-09-16. Adopted: `--device CUDA0,CUDA2,CUDA1`,
`--tensor-split 1,1,2.5`, `--spec-draft-n-max 3` (MTP depth 3) for the
262,144-token three-GPU Qwen3.6-35B-A3B Q4_K_P profile. The production server
is intentionally stopped while the host is out of service for research; the
launcher already contains the new defaults.

## Question

The earlier MTP pin experiment showed that forcing `blk.40.*` to the RTX while
the rest of the tail stayed on a CMP costs -16.7% decode (the draft graph broke
into 16 scheduler splits). If instead the whole tail stage (last layers, output
head and MTP layer) is placed on the RTX by device order, does decode improve,
and does deeper MTP speculation pay off there?

Answers:

- Yes: decode-500 rises from 61.96 to about 95.5 tok/s (+54%), repo-28k decode
  from about 53 to 82.3 tok/s (+55%), with byte-identical output.
- Prefill stays above the original production profile (465.8 vs 432.4 tok/s on
  prefill-4k; 405.4 vs 372.4 on repo-28k) but is below the prefill-optimized
  `1,3,1` configuration (545.9 / 474.5).
- On the RTX tail, deeper MTP drafts become profitable: n-max=3 is best at
  short context and n-max=4 slightly better at long context. n-gram speculation
  is not competitive with MTP here.

## Configuration and method

- Device order `CUDA0,CUDA2,CUDA1` with `--tensor-split 1,1,2.5` assigns
  CMP0 -> 22.2%, CMP2 -> 22.2%, RTX -> 55.6% of layers, and the RTX is the
  tail device: the output layer and the MTP block `blk.40.*` are assigned to it
  and stay co-located, so the MTP draft graph executes as a single-device graph.
- Everything else is unchanged: 262,144 context, one slot, q8_0 K/V, Flash
  Attention, `--ubatch-size 448`, runtime `qwen36-df03399-dp2a-no-fmad`.
- Matched runs with strict CMP binding, telemetry, byte-for-byte completion
  equality; 3 runs per decode-500 point unless noted.

## Results

### Decode and prefill (medians or individual points)

| Metric | Old production (1,2.25,1, ub256, mtp1) | Prefill-first (1,3,1, ub448, mtp1) | Adopted (RTX tail 1,1,2.5, ub448, mtp3) |
| --- | ---: | ---: | ---: |
| decode-500 raw eval | 61.96 | 61.28 | **95.47** |
| decode-500 HTTP | 56.49 | - | ~89 |
| prefill-4k raw prefill | 432.4 | 545.9 | 465.8 |
| repo-28k raw prefill (no cache) | 372.4 | 474.5 | 405.4 |
| repo-28k raw decode | ~53 | ~53 | **82.30** |
| CUDA2 / RTX sampled peak | 8685 / 16246 MiB | 8943 / 17706 MiB | 6675 / 20018 MiB |

### MTP depth on the RTX tail (1,1,2.5)

| n-max | decode-500 | acceptance / mean len | repo-28k decode | echo case |
| ---: | ---: | --- | ---: | ---: |
| 1 | 84.47 | 82.4% / 1.82 | 66.5 | - |
| 2 | 93.57 | 78.1% / 2.56 | 68.3 | - |
| 3 | 95.47 | 70.6% / 3.12 | 82.30 | 110.35 |
| 4 | 86.51 | 56.9% / 3.28 | **84.19** | - |

n-max=3 is adopted: best short-context result and within 2% of the n-max=4
long-context result. n-max=4 may be preferred for long-context-only use.

### Device order and split sweep on the RTX tail (mtp3)

| device order / split | decode-500 | prefill-4k | RTX peak |
| --- | ---: | ---: | ---: |
| CUDA0,CUDA1,CUDA2 / 1,3,1 (RTX middle) | 61.28 | 545.9 | 17706 |
| CUDA0,CUDA2,CUDA1 / 1,1,3 | 94.79 | 450.5 | 20590 |
| CUDA0,CUDA2,CUDA1 / 1,1,2.5 | **95.47** | **465.8** | 20018 |
| CUDA0,CUDA2,CUDA1 / 1,1,2.25 | 96.86 | 452.3 | 19234 |
| CUDA0,CUDA2,CUDA1 / 1,1,2 | 95.05 | 439.0 | 18632 |

The tail placement, not the exact share, drives the decode gain; 2.5 keeps the
best prefill balance among the tested shares.

### n-gram vs MTP

`--spec-type ngram-mod` (`--spec-ngram-mod-n-match 24 --spec-ngram-mod-n-min 48
--spec-ngram-mod-n-max 64`) on a verbatim code-echo prompt gives 76.09 tok/s
versus 110.35 tok/s for MTP `n-max=3`. n-gram is not adopted.

## Correctness and stability

- Every decode-500 completion is byte-for-byte identical to the control
  (baseline tokens, counts and finish reasons).
- No CUDA error, illegal instruction, assertion or OOM in any RTX-tail run.
- RTX sampled peak is 20,018-20,590 MiB of 22,528 MiB (about 1.9 GiB headroom);
  CMP2 drops to 6,035-7,531 MiB, so the tight card is now the RTX.
- The earlier `-ot` MTP pin remains rejected: it produced 16 splits per draft
  step and -16.7% decode. The tail move is the correct way to put MTP on the
  RTX.

## Adopted configuration

```
--device CUDA0,CUDA2,CUDA1
--split-mode layer --tensor-split 1,1,2.5
-ngl all --fit off --kv-offload --flash-attn on
--ctx-size 262144 --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0
--batch-size 1024 --ubatch-size 448 --threads 4
--spec-type draft-mtp --spec-draft-n-max 3
```

Prefill-first alternative (if long-prompt TTFT matters more than decode):
`--device CUDA0,CUDA1,CUDA2 --tensor-split 1,3,1 --spec-draft-n-max 1`
(prefill-4k 545.9, repo-28k prefill 474.5, decode-500 61.28).

## Artifacts

All runs are under `benchmarks/results/20260916-18*` and `20260916-19*`:

- RTX-tail base (1,1,3, mtp1): `180050` (smoke), decode `1803xx`,
  prefill `18*`, repo-nocache `18*`.
- ubatch sweep on the RTX tail: `18*` (256/320/384; 448 from the base).
- MTP depth: `rtx-tail-mtp2` `18*`, `rtx-tail-mtp3` `18*`,
  `rtx-tail-mtp4` `18*`.
- ngram: `rtx-tail-ngram` `18*` (echo); MTP echo control `rtx-tail-mtp3` `18*`.
- Split sweep: `1,1,2.5` `184500-184753`, `1,1,2.25` `185014-185315`,
  `1,1,2` `185444-185744`.
- Profiles: `benchmarks/profiles/...-rtx-tail*.json`,
  `benchmarks/prompts/ngram-echo.json`.

## Reproduce

```bash
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-rtx-tail-mtp3-split2p5.json \
  --variant native-262k --cases decode-500 --repetitions 1

python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-rtx-tail-mtp3.json \
  --variant native-262k --cases prefill-4k --repetitions 1
```
