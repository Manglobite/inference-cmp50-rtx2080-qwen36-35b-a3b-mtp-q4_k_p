# Qwen3.6-35B-A3B на 2×CMP 50HX + RTX 2080 Ti: оптимизированный рецепт llama.cpp

**Русский** | [English](README.en.md)

Открытый кейс для смешанной трёх-GPU конфигурации на Turing. Внутри: рабочий
рантайм, патч, все скрипты запуска и бенчмарков, измеренные результаты и
готовый промт для агента. Цель — чтобы владельцы похожего железа не проходили
тот же долгий путь, а начинали с проверенной конфигурации.

## Коротко

- Железо: **2× NVIDIA CMP 50HX 10 ГиБ + 1× RTX 2080 Ti 22 ГиБ** (все sm_75),
  30 ГиБ RAM, Xeon E5-2670 v3.
- Модель: **Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP Q4_K_P** (24.3 ГБ GGUF,
  встроенная MTP-голова), Q8_0 K/V, Flash Attention, контекст 262 144
  (368 640 тоже работает).
- Две проблемы CMP: DP4A исполняется ~33 цикла (против 2.25 у DP2A), а FP32
  FMA зарезан (~0.43 против 6.88 TFLOPS при раздельных mul+add).
- Решения: порт PR #25834 на `df03399` (`GGML_CUDA_DISABLE_DP4A=ON`) +
  флаг nvcc `-fmad=false`.
- Лучшая конфигурация: **RTX — хвостовая стадия** (`--device CUDA0,CUDA2,CUDA1`,
  `--tensor-split 1,1,2.5`) и **MTP `--spec-draft-n-max 3`**; ubatch 448.

Измерения на целевом профиле (decode-500 / prefill-4k, raw-тайминги сервера):

| Вариант | decode-500 | prefill-4k | repo-28k prefill | repo-28k decode |
| --- | ---: | ---: | ---: | ---: |
| baseline DP4A | 47.8 t/s | 372.7 t/s | 372.4 t/s | ~53 t/s |
| + DP2A | 54.0 t/s | 373.3 t/s | - | - |
| + `-fmad=false` | 62.2 t/s | 431.8 t/s | - | - |
| **RTX-хвост + MTP n-max=3 (принято)** | **95.5 t/s** | **465.8 t/s** | **405.4 t/s** | **82.3 t/s** |

Контроль только на CMP (DeepSeek-R1-Qwen3-8B Q4_K_M, одна CMP 50HX):
27.9 → 47.3 → 61.3 t/s для baseline → DP2A → DP2A+no-fmad, то есть **+119%**.

Кейс проверен end-to-end из своей папки 17.09.2026:
`benchmarks/scripts/run.py` с принятым профилем показал **91.4 t/s** raw eval
(эталон 95.5, −4%), а `scripts/launch-server.sh` поднял сервер, ответил на
smoke-запрос (`2 + 2 = 4`) и корректно остановился.

## Быстрый старт (готовый рантайм)

```bash
# 1. получите рантайм: скачивание ассета релиза в llama.cpp/runtime/
bash scripts/fetch-runtime.sh
#    (либо собрать локально: bash scripts/build-df03399.sh no-fmad /tmp/llama-nofmad)

# 2. положите файлы модели в ./models (см. RUNBOOK.ru.md и AGENT_PROMPT.md)
#    Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-Q4_K_P.gguf
#    mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-MTP-f16.gguf

# 3. запустите принятый трёх-GPU профиль (RTX-хвост, MTP 3, контекст 262144)
bash scripts/launch-server.sh

# 4. health + smoke
curl -s http://127.0.0.1:8085/health
```

Рантайм распространяется ассетом GitHub-релиза (~53 МБ в сжатом виде, патч
DP2A + `-fmad=false`), поэтому для запуска компиляция не нужна; скрипт
проверяет SHA-256. Артефакты сборки и снимок исходников в Git не хранятся —
пересоберите их через `scripts/build-df03399.sh`, если нужно.

## Структура репозитория

```text
qwen36-35b-a3b/
├── README.md / README.en.md   <- этот файл (RU, по умолчанию) и английская версия
├── HARDWARE.md / .ru.md       <- точная конфигурация и минимумы
├── CHRONOLOGY.md / .ru.md     <- что пробовали, почему и к чему пришли
├── WHAT_INFLUENCES_WHAT.md / .ru.md  <- матрица «параметр → эффект»
├── RUNBOOK.md / .ru.md        <- запуск, бенчмарки, откат, диагностика
├── AGENT_PROMPT.md            <- задание для агента (только английский)
├── LICENSE-NOTICE.md / .ru.md <- лицензии llama.cpp, патча и модели
├── llama.cpp/
│   ├── runtime/               <- готовый llama-server + библиотеки (ассет релиза, не в Git)
│   └── src/                   <- исходники df03399 с патчем (артефакт сборки, не в Git)
├── patches/                   <- портированный патч PR #25834 (df03399)
├── scripts/                   <- лаунчеры, сборка, harness бенчмарков
├── profiles/                  <- JSON-профили всех экспериментов
├── prompts/                   <- промты лесенок и дизайн-сессий
├── docs/                      <- полные отчёты и диалоги
└── results-summary/           <- таблицы по сообщениям дизайн-сессий
```

Соглашение о языках: у каждого человекочитаемого документа есть две версии со
строкой-переключателем сверху; основной README — русский (`README.md`),
английский — `README.en.md`. Остальные документы: русская `*.ru.md` и
английская `*.md`. `AGENT_PROMPT.md` намеренно только на английском — он
написан для агента.

## Что внутри и где читать подробнее

| Тема | Документ |
| --- | --- |
| Железо и версии ПО | [HARDWARE.ru.md](HARDWARE.ru.md) |
| Полная хронология и причины | [CHRONOLOGY.ru.md](CHRONOLOGY.ru.md) |
| Что влияет на prefill/decode/VRAM | [WHAT_INFLUENCES_WHAT.ru.md](WHAT_INFLUENCES_WHAT.ru.md) |
| Запуск / пересборка / откат / диагностика | [RUNBOOK.ru.md](RUNBOOK.ru.md) |
| Задание для агента: собрать и проверить автоматически | [AGENT_PROMPT.md](AGENT_PROMPT.md) (EN) |
| DP2A A/B на трёх-GPU профиле | [docs/cmp50hx-dp2a-df03399-result.ru.md](docs/cmp50hx-dp2a-df03399-result.ru.md) |
| DP2A + `-fmad=false` A/B | [docs/cmp50hx-dp2a-no-fmad-df03399-result.ru.md](docs/cmp50hx-dp2a-no-fmad-df03399-result.ru.md) |
| Split / ubatch / размещение MTP | [docs/cmp50hx-split-ubatch-mtp-df03399-result.ru.md](docs/cmp50hx-split-ubatch-mtp-df03399-result.ru.md) |
| RTX-хвост + глубина MTP (итог) | [docs/cmp50hx-rtx-tail-mtp-df03399-result.ru.md](docs/cmp50hx-rtx-tail-mtp-df03399-result.ru.md) |
| Контекстные лесенки 262K/360K | [docs/cmp50hx-context-ladder-262k-360k.ru.md](docs/cmp50hx-context-ladder-262k-360k.ru.md) |
| Дизайн-сессии (агентный режим, 360K) | [docs/cmp50hx-design-session-360k.ru.md](docs/cmp50hx-design-session-360k.ru.md), [docs/cmp50hx-design-sessions-go-2apps.ru.md](docs/cmp50hx-design-sessions-go-2apps.ru.md) |

## Ограничения и предупреждения

- Патч — **экспериментальный и не влитый** PR (#25834). Он меняет только
  целочисленный dot product в CUDA; арифметический результат не меняется
  (во всех парных тестах completion совпадали байт-в-байт).
- `-fmad=false` — флаг NVCC на весь бинарь. RTX 2080 Ti тоже sm_75, поэтому
  его FP32 FMA тоже разделяется; на трёх GPU суммарный эффект сильно
  положительный, но на RTX-only или Ampere CMP этот флаг может навредить.
- Контекст 368 640 больше нативных 262 144 у модели. Он работает (KV влезает,
  скорость не меняется), но качество за пределами обученного окна не измерялось.
- Файлы модели (24.3 ГБ) не включены; инструкции по скачиванию и SHA-256 —
  в `RUNBOOK.ru.md`.
- В принятой конфигурации самая тесная карта — RTX: 20.0–21.9 ГиБ из 22.5
  в зависимости от контекста.

## Лицензия

llama.cpp распространяется по MIT; портированный патч — модификация PR #25834
(MIT). У весов модели своя лицензия — проверьте карточку модели перед
распространением. Подробности в `LICENSE-NOTICE.ru.md`.
