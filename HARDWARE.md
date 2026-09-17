# Hardware and software of the reference test rig

**English** | [Русский](HARDWARE.ru.md)

## Host

| Component | Value |
| --- | --- |
| CPU | Intel Xeon E5-2670 v3 @ 2.30 GHz, 12 cores / 24 threads, 30 MiB L3, single socket |
| RAM | 30 GiB (32,165,012 KiB reported by `/proc/meminfo`) |
| Disk | TOSHIBA TR200 223 GB SATA SSD; root LV 98 GB (about 25 GB free during the tests) |
| OS | Ubuntu 26.04 LTS, kernel 7.0.0-31-generic |
| NVIDIA driver | 595.71.05 (CUDA runtime 13.2 capable) |
| Build toolkit | CUDA 12.4 (nvcc V12.4.131), GCC 15.2.0, CMake 4.2.3 |
| NCCL | 2.22.3 (`/usr/lib/x86_64-linux-gnu/libnccl.so.2`) |
| Python | 3.14 (harness), no numpy required |

## GPUs

CUDA device order below is the **PCI bus order** used everywhere in this case
(`CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA_VISIBLE_DEVICES=0,1,2`).

| Index | Model | PCI bus | UUID | VRAM | Compute | Power limit | Role in the adopted profile |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| CUDA0 | NVIDIA CMP 50HX | `00000000:03:00.0` | `GPU-201703f9-1d0f-8a3d-9fa8-3688691d6d2a` | 10,240 MiB | sm_75 | 225 W | first layer stage |
| CUDA1 | NVIDIA GeForce RTX 2080 Ti | `00000000:04:00.0` | `GPU-6a6576bd-9d4b-c9e1-7a90-a03484daf586` | 22,528 MiB | sm_75 | 260 W (max 320 W) | middle... **tail stage** |
| CUDA2 | NVIDIA CMP 50HX | `00000000:08:00.0` | `GPU-362c8abe-08a4-fd4d-b14b-218b26b65d80` | 10,240 MiB | sm_75 | 225 W | middle layer stage |

Other CMP 50HX cards may have different UUIDs; check yours with `nvidia-smi -L`.

### Topology

- All GPU pairs report `PHB` (PCIe host bridge); **no NVLink**.
- Single NUMA node (CPU 0-23).
- `nvidia-smi` reports idle links as Gen1 x1 (power-saving); maximum is Gen2 x16
  for the CMP cards and Gen3 x16 for the RTX. Layer-split decode transfers only
  small activations, so PCIe is not the decode bottleneck.

### Relevant CMP 50HX hardware behaviour (external + local evidence)

- DP4A latency ≈ 33.08 cycles vs DP2A ≈ 2.25 cycles (micro-benchmark,
  `arabel1a/gpu-micro-bench`), while the card reports sm_75.
- FP32 FMA throughput is throttled: about 0.43 TFLOPS with FMA vs about
  6.88 TFLOPS when mul+add are split (`nvcc --fmad=false`), measured externally
  (Habr, WebSlave) and confirmed by our A/B tests.
- The same workarounds hurt other architectures: RTX 3060/CMP 90HX FP32 drops
  about 2x with `--fmad=false`; CMP 100/170 need different tricks. This case is
  specific to CMP 40HX/50HX-class Turing.

## Why exactly three GPUs

- The 24.3 GB Q4_K_P model does not fit on one 10 GiB CMP and does not need the
  RTX's capacity alone: the RTX has ~22 GiB, the model plus 262k Q8 KV does not
  fit into it either.
- Three stages give enough total VRAM (42.5 GiB) and put the large, fast RTX on
  the most expensive stage (the tail with the output head and MTP).
- `row` split is not supported on the CMP CUDA backend; `layer` split with a
  device-ordered `--tensor-split` is the working mode.

## Minimum requirements to reuse this case

- Two CMP 50HX (or CMP 40HX) 10 GiB cards and one large Turing GPU with ~22 GiB
  (RTX 2080 Ti / Titan RTX). All must be sm_75 for the DP2A and `-fmad=false`
  wins.
- ≥ 42 GiB total VRAM for the 262k profile; 360k fits but leaves ~0.6 GiB on
  the RTX.
- 30 GiB system RAM (the prompt cache uses up to 8 GiB; the 360k two-session
  test pushed 4 GiB of swap).
- ~40 GB free disk: 24.3 GB model + 0.9 GB projector + ~10 GB build tree.
- CUDA 12.4 toolkit for building (the bundled runtime was built with it);
  newer toolkits should work but were not tested.
- Motherboard with three usable PCIe slots (even x4/x8 links work for layer
  split).

## What changes on other hardware

| Hardware difference | Expected effect |
| --- | --- |
| CMP 40HX instead of 50HX | Same DP4A/FMA throttling class; expect similar direction, different numbers. |
| Only one large GPU + one CMP | Use `CUDA0,CUDA1` order with a smaller split; 262k may not fit. |
| Ampere CMP (90HX/170HX/100) | Do **not** use `-fmad=false`; DP4A patch is not applicable to CMP100/170 (different throttling). |
| Modern GPU with ≥48 GB VRAM | Prefer a single-GPU setup; this case's tricks are unnecessary. |
| No NCCL installed | Build without `-DGGML_CUDA_NCCL=ON`; measured effect on this rig was ~0.3%. |
