# Runbook (руководство по запуску)

[English](RUNBOOK.md) | **Русский**

## 1. Скачивание модели

Положите оба файла в `models/`. Для текста достаточно GGUF; проектор нужен для
зрения и указан в лаунчере, поэтому либо скачайте его, либо перекройте
`MMPROJ=` на существующий файл.

```bash
mkdir -p models
base=https://huggingface.co/morikomorizz/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP/resolve/main

curl -L -C - -o models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf \
  "$base/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf"
curl -L -C - -o models/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf \
  "$base/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf"
```

Контрольные суммы (проверяйте до запуска; карточка модели может меняться —
тогда сверяйте свои цифры заново):

| Файл | Байт | SHA-256 |
| --- | ---: | --- |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf` | 24 322 493 952 | `d4c1bc574fee76d0667e63cecec1a644eb0c3a13adbdc254af5b9b84a28de993` |
| `mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf` | 899 283 072 | `c8e702344a81f8c226a914aa980ed6e1f604bce9374f1fed8e65c896908af414` |

```bash
sha256sum models/*.gguf
```

Альтернатива: `huggingface-cli download morikomorizz/Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP --local-dir models`.

## 2. Запуск принятого профиля (рантайм из релиза, без сборки)

Рантайм в Git не хранится; сначала скачайте ассет релиза (скрипт сверит
SHA-256 и распакует в `llama.cpp/runtime/`), либо соберите локально:

```bash
bash scripts/fetch-runtime.sh
# либо: bash scripts/build-df03399.sh no-fmad /tmp/llama-nofmad
#       cp -a /tmp/llama-nofmad/bin llama.cpp/runtime/
```

Затем запустите сервер:

```bash
bash scripts/launch-server.sh
```

По умолчанию: `--device CUDA0,CUDA2,CUDA1` (RTX — хвост),
`--tensor-split 1,1,2.5`, ctx 262144, ubatch 448, MTP `n-max=3`, Q8_0 K/V,
Flash Attention, `--cache-ram 8192`, порт 8085, host 127.0.0.1.

Переопределения (примеры):

```bash
CTX_SIZE=368640 PORT=8085 bash scripts/launch-server.sh   # контекст 360k
API_KEY=secret bash scripts/launch-server.sh              # требовать API-ключ
UBATCH_SIZE=320 bash scripts/launch-server.sh             # если мало VRAM
```

Smoke-проверка в другом терминале:

```bash
curl -s http://127.0.0.1:8085/health
curl -s -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-35B-A3B-uncensored-MTP-Q4_K_P","messages":[{"role":"user","content":"2+2="}],"max_tokens":32,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}' \
  http://127.0.0.1:8085/v1/chat/completions
```

Ожидается: HTTP 200 и детерминированный ответ (в наших прогонах `2 + 2 = 4`).

## 3. Сравнение с baseline (A/B)

Готовый рантайм — это принятая сборка DP2A + `-fmad=false`. Чтобы
воспроизвести сравнение, соберите два других режима тем же скриптом:

```bash
bash scripts/build-df03399.sh baseline /tmp/llama-baseline
bash scripts/build-df03399.sh dp2a     /tmp/llama-dp2a
# при желании сохраните их в дереве кейса
mkdir -p llama.cpp/runtime-baseline llama.cpp/runtime-dp2a
cp -a /tmp/llama-baseline/bin llama.cpp/runtime-baseline/
cp -a /tmp/llama-dp2a/bin     llama.cpp/runtime-dp2a/
```

Затем чередуйте прогоны harness'ом (из корня кейса):

```bash
# принятый рантайм (RTX-хвост, MTP 3)
python3 benchmarks/scripts/run.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad-rtx-tail-mtp3-split2p5.json \
  --variant native-262k --cases decode-500 --repetitions 1

# baseline (нужен tools/llama-cpp/qwen36-df03399-baseline/bin -> ваша сборка)
python3 benchmarks/scripts/run.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-baseline.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

Профили ссылаются на `tools/llama-cpp/<build_variant>/bin`; в кейсе лежит
симлинк принятого варианта на готовый рантайм. Для baseline и DP2A замените
симлинк `bin` в соответствующем каталоге `tools/llama-cpp/qwen36-df03399-*`
на свою сборку. Результаты пишутся в `benchmarks/results/`.

Ожидаемые медианы (262k, decode-500, raw eval сервера): baseline ~47.8,
DP2A ~54.0, no-fmad ~62.2, принятый RTX-хвост + MTP 3 ~95.5 tok/s. Считайте
±10% нормальным разбросом железа/тулчейна.

## 4. Контекстная лесенка и агентные сессии

```bash
# лесенка в одной сессии на 360k: hello -> 10k -> 75k -> повтор
python3 benchmarks/scripts/build_context_ladder.py --base-url http://127.0.0.1:8085 --targets 10000,75000 --out prompts/context-ladder.json
python3 benchmarks/scripts/run_context_ladder.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native --steps prompts/context-ladder-steps-test1.json \
  --prompts prompts/context-ladder.json --label test1-360k

# агентная дизайн-сессия с эмуляцией инструментов
python3 benchmarks/scripts/run_design_session.py \
  --profile profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native --script prompts/design-session-360k.json --label design
```

В каждом каталоге прогона лежат `result.json`/`metrics.json`, `server.log`,
`host-telemetry.csv` (CPU нагрузка/температура, RAM, swap и по каждой GPU
температура/загрузка/память/мощность каждые 0.5 с), `gpu-binding.json` и
копии входных файлов.

## 5. Откат

- Принятый → baseline: `bash scripts/launch-server-baseline.sh` (нужна
  baseline-сборка) либо запуск принятого лаунчера с
  `SPEC_N_MAX=1 DEVICES=CUDA0,CUDA1,CUDA2 TENSOR_SPLIT=1,3,1 UBATCH_SIZE=448`.
- Если на живом хосте всем управляет `inference-hub`, останавливайте/запускайте
  сервер через его API (`/api/backends/<pid>/stop`,
  `/api/profiles/<script>/start`) и помните про `idleAfterSeconds`: hub
  блокирует частоты CMP на 300 МГц после простоя, что искажает бенчмарки до
  следующего пробуждения.

## 6. Диагностика

| Симптом | Вероятная причина | Решение |
| --- | --- | --- |
| CUDA OOM на CMP во время prefill | ubatch слишком велик для 10 ГиБ | уменьшить `UBATCH_SIZE` (448 → 320 → 256) или взять `TENSOR_SPLIT=1,3,1` |
| CUDA OOM на RTX при 360k | KV + буферы не влезают в ~22 ГиБ | уменьшить `CTX_SIZE`, ubatch или перенести часть слоёв на CMP (`1,1,2.25`/`1,1,2`) |
| Резко упал decode с включённым MTP | MTP-тензоры оказались не на хвостовом устройстве | не использовать `-ot` на `blk.40.*` отдельно; держать RTX последним в порядке устройств |
| Prompt cache не срабатывает | другой текст промпта или кэш выключен | повторяйте идентичные префиксы, держите `--cache-prompt --cache-ram 8192` |
| Swap заполняется, хост тормозит | 360k + два слота + 8 ГиБ prompt cache | уменьшить `CACHE_RAM_MIB`, использовать один слот |
| `llama-server` падает на старте | нет модели/неверный размер, занят порт, запущен другой сервер | проверить `models/`, освободить порт, остановить чужой процесс |
| Сборку убило по OOM | голый `--parallel` на 30 ГиБ хосте | использовать `scripts/build-df03399.sh` (systemd-guard), не запускать голый `--parallel` |

## 7. Практика измерений этого кейса

1. Строгая привязка: `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA_VISIBLE_DEVICES=0,1,2`,
   и сохранять `gpu-binding.json` с телеметрией в каждом прогоне.
2. Одно изменение на сравнение; чередовать A/B; всё остальное неизменно.
3. Требовать байт-идентичные completion при temperature 0, прежде чем верить
   разнице в скорости.
4. Основная метрика — raw-тайминги сервера (`prompt eval`, `eval`), HTTP-
   пропускная способность — подтверждающая и пользовательская.
5. Сохранять неудачные прогоны: они документируют границы по OOM и стабильности.
