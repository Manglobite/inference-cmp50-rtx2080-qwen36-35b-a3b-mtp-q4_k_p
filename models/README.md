# Model files

**English** | [Русский](README.ru.md)

This directory must contain the two GGUF files used by the launchers:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf` | 24,322,493,952 | `d4c1bc574fee76d0667e63cecec1a644eb0c3a13adbdc254af5b9b84a28de993` |
| `mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf` | 899,283,072 | `c8e702344a81f8c226a914aa980ed6e1f604bce9374f1fed8e65c896908af414` |

Download (the projector is optional for text-only use; override `MMPROJ=` then):

```bash
base=https://huggingface.co/morikomorizz/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP/resolve/main
curl -L -C - -o Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf \
  "$base/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf"
curl -L -C - -o mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf \
  "$base/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf"
sha256sum *.gguf
```

Model weights are ignored by Git on purpose (see `.gitignore`); verify the
hashes before serving and check the model card for its license.
