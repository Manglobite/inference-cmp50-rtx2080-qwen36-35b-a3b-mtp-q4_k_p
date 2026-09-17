# Licenses and notices

**English** | [Русский](LICENSE-NOTICE.ru.md)

## llama.cpp

This case bundles a llama.cpp source snapshot (`llama.cpp/src`) and a compiled
runtime (`llama.cpp/runtime/bin`). llama.cpp is distributed under the MIT
License; the full text is in `llama.cpp/src/LICENSE`. The source snapshot is
upstream commit `df03399b885831b2a1603b3abb0d8c156808e363` plus the patch
described below; it is a research copy, not an upstream release.

## DP2A patch (PR #25834)

The patch `patches/25834-df03399-port.patch` is a port of
<https://github.com/ggml-org/llama.cpp/pull/25834> (commit
`c499d2f41c36e6be13d25622d7c24d287a58a69a`, author sj0618) onto `df03399`.
The PR is open and unmerged; the patch is MIT-licensed as a derivative of
llama.cpp. It adds the `GGML_CUDA_DISABLE_DP4A` CMake option and replaces one
DP4A with two DP2A plus `prmt.b32` shuffles in `ggml_cuda_dp4a`.

## Scripts, profiles and documentation

The launchers, benchmark harness, profile JSONs, prompts and documents in this
case are provided as-is under the same MIT terms for reuse with the bundled
runtimes. No warranty; validate on your own hardware before production use.

## Model weights

The model and projector files are **not** included. They are published by
their authors (HauhauCS / the `morikomorizz` Hugging Face repository); see the
model card for its license and usage terms before downloading, using or
redistributing the weights. The checksums in `RUNBOOK.md` identify the exact
files used in the reference measurements.

## Third-party tools referenced but not bundled

- NCCL (NVIDIA, BSD-like license) - optional, used only in some builds.
- CUDA toolkit and the NVIDIA driver - governed by NVIDIA's EULA.
- Python standard library only for the harness; no Python packages required.
