# DP2A на трёх-GPU профиле Qwen3.6-35B-A3B: результат A/B (df03399)

[English](cmp50hx-dp2a-df03399-result.md) | **Русский**

## Статус

Завершено 15.09.2026. DP2A принят для испытанного трёх-GPU профиля
Qwen3.6-35B-A3B Q4_K_P. Этот документ закрывает
`cmp50hx-dp2a-ab-handoff.md`; он не меняет решение от 11.08.2026 для одной CMP
(DeepSeek/Seed) и не трогает два старых упакованных рантайма в
`tools/llama-cpp/`.

> **Обновление 16.09.2026: в проде заменён на DP2A + `--fmad=false`**
> (`docs/benchmarks/cmp50hx-dp2a-no-fmad-df03399-result.md`, +15.0% decode к
> DP2A). DP2A-рантайм остаётся упакованным как промежуточный шаг отката.

## Вопрос

Улучшает ли замена DP4A на обход DP2A из PR #25834 в llama.cpp реальную
пропускную способность decode активного прод-профиля Qwen3.6-35B-A3B Q4_K_P
с layer split, не меняя вывод, VRAM и стабильность?

Ответ: да. Медианный raw decode вырос на 12.0–14.1% в зависимости от кейса,
HTTP-пропускная способность — на 6.1–12.9%, prompt eval не изменился,
выборочный пик VRAM идентичен, и каждый парный completion совпал байт-в-байт.

## Провенанс

- Upstream-коммит llama.cpp: `df03399b885831b2a1603b3abb0d8c156808e363`
  (исходный worktree `research/qwen38-27b-autonomous-20260910/llama.cpp-upstream`).
- Закреплённый патч PR #25834 (upstream `86d86ed`): SHA-256
  `641ba95eb0649c04759e6cdfbcaef4b99146b99efce569d9d4dd0d7019a450b2`.
  На `df03399` он чисто не ложится; адаптирован только дрейф контекста.
- Портированный патч: `tools/llama-cpp/qwen36-df03399-dp2a/patches/25834-df03399-port.patch`,
  SHA-256 `dd73bdea36f9823c507918a997dbd279c1dff7a8d36cf0408d4151f4f2bf81d0`
  (4 файла, 22 вставки: опция CMake, определение компиляции CUDA,
  путь DP2A+PRMT в `ggml_cuda_dp4a`, строка в build.md).
- Рантаймы (прод-флаги `GGML_CUDA=ON`, `GGML_CUDA_NCCL=ON`, `Release`,
  `sm_75`, `CMAKE_BUILD_RPATH_USE_ORIGIN=ON`; DP2A добавляет
  `GGML_CUDA_DISABLE_DP4A=ON`):
  - `tools/llama-cpp/qwen36-df03399-baseline/` (manifest, хэши, README);
  - `tools/llama-cpp/qwen36-df03399-dp2a/` (manifest, хэши, README).
- Обе сборки сообщают `version: 0.4.0-dev (build 1, commit df03399)`; NVCC
  12.4.131, CMake 4.2.3. `libggml-cuda.so.0.23.0` различается между
  вариантами — значит опция реально скомпилирована. `ldd` и
  `RUNPATH=$ORIGIN` разрешают библиотеки из собственного `bin/`; `not found`
  нет.
- Защита сборки: последовательные `systemd-run --user` юниты с
  `MemoryMax=16G`, `MemorySwapMax=0`, `--parallel 12`; пики по 3.9 ГиБ, swap 0.
- DeepSeek-R1-0528-Qwen3-8B Q4_K_M перекачан для воспроизведения контроля на
  одной CMP; SHA-256
  `a86349a4180c4e6bb43f874c29c404fa2be3f90b15509bd6d86f697dba724ec1`,
  размер 5,027,785,216 Б (совпадает с находками 2026-07).

## Метод

- Профили (внутри пары отличаются только имя, бинарь, build variant и порт):
  - `benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-{baseline,dp2a}.json`:
    точный живой прод-argv модели (три GPU, `--device
    CUDA0,CUDA1,CUDA2`, `--split-mode layer`, `--tensor-split 1,2.25,1`,
    `-ngl all`, `--fit off`, q8_0 K/V, Flash Attention, контекст 262,144, один
    слот, нативный MTP `--spec-draft-n-max 1`, prompt cache, reasoning on).
  - `benchmarks/profiles/llama-cpp-deepseek-r1-qwen3-8b-q4-cmp50hx-df03399-{baseline,dp2a}.json`:
    одна изолированная CMP, 32K, q8_0 K/V, Flash Attention, без MTP,
    reasoning off.
- Harness `benchmarks/scripts/run.py` со строгой привязкой
  (`CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA_VISIBLE_DEVICES`, `--device`), один
  сервер на запуск, warm-up запрос, `--repetitions 1`, чередование пар
  `baseline -> DP2A`. Каждый прогон сохранил `gpu-binding.json`,
  `gpu-telemetry.csv`, `environment.json`, `build-variant.json`, `server.log`
  и `result.json` с raw-таймингами llama.cpp.
- Привязка CMP: CMP на `00000000:03:00.0` и `00000000:08:00.0`, RTX на
  `00000000:04:00.0`. Во время контроля на DeepSeek RTX оставалась на 1 МиБ.
- Перед окном отключён idle-лок частот control plane
  (`idleAfterSeconds=0`) и сброшены частоты; после — восстановлено. Живой
  Qwen3.6-сервер остановлен через API control plane и поднят снова после измерений;
  простой около 20 минут.

## Результаты

Raw `eval` — это decode-токены/с сервера llama.cpp; HTTP — сквозная
пропускная способность генерации. В этой ревизии не логируются
`n_decoded`/`tg`, поэтому raw-метрика decode — это `eval`. Медианы пяти
(Qwen) или трёх (DeepSeek) парных прогонов.

### Qwen3.6-35B-A3B Q4_K_P, три GPU (целевой профиль)

| Кейс | Метрика | Baseline | DP2A | Дельта |
| --- | --- | ---: | ---: | ---: |
| decode-500 | raw eval tok/s | 47.79 | 54.44 | **+13.92%** |
| decode-500 | HTTP tok/s | 44.508 | 50.234 | +12.86% |
| prefill-4k | raw prefill tok/s | 373.61 | 373.63 | +0.01% |
| prefill-4k | raw decode tok/s | 52.23 | 59.57 | +14.05% |
| prefill-4k | HTTP tok/s | 11.672 | 11.981 | +2.64% |
| repo-28k | raw decode tok/s | 44.08 | 49.37 | +12.00% |
| repo-28k | HTTP tok/s | 22.406 | 23.760 | +6.05% |

Raw eval по прогонам (tok/s), baseline и DP2A в каждой паре:

- decode-500: 42.87/47.97/47.79/47.90/47.72 против
  53.93/54.76/54.43/54.44/54.78.
- prefill-4k: 51.73/52.23/52.49/52.37/51.61 против
  59.57/58.95/59.71/58.15/59.81.
- repo-28k: 43.88/44.26/43.98/44.08/44.32 против
  49.50/49.36/49.77/49.28/49.37.

Первый baseline-замер decode-500 (42.87) — холодный выброс первого запуска;
медиана устойчива, остальные baseline-точки 47.7–48.0.

### DeepSeek-R1-Qwen3-8B Q4_K_M, одна изолированная CMP (контроль порта)

| Метрика | Baseline | DP2A | Дельта |
| --- | ---: | ---: | ---: |
| decode-500 raw eval tok/s | 27.95 | 47.38 | **+69.52%** |
| decode-500 HTTP tok/s | 27.157 | 44.997 | +65.69% |

Это воспроизводит ранее принятое поведение DP2A на одной CMP на новом коммите
(результат на `86d86ed` был около +79%) и доказывает, что порт сохранил
задуманный обход.

## Корректность, VRAM и стабильность

- Все 18 измеренных пар (3 DeepSeek, 5 Qwen decode, 5 Qwen prefill, 5 Qwen
  repo) вернули байт-идентичные completion с равными счётчиками
  prompt/completion токенов и одинаковыми finish reason.
- Обе детерминированные smoke-пары на 128 токенов (DeepSeek и Qwen) также
  совпали; DeepSeek raw eval 27.94 -> 48.20 tok/s в smoke.
- Выборочный пик VRAM не изменился: у Qwen `6787 / 16246 / 8685 MiB`
  (CUDA0/CUDA1/CUDA2) в обоих вариантах; у DeepSeek на CMP `7261 MiB` в обоих.
- Ни один `server.log` не содержит CUDA error, illegal instruction, assertion,
  OOM, segfault или fallback. В журнале ядра нет событий OOM/Xid.
- Значение prompt-eval для `repo-28k` — не чистое сравнение prefill, потому
  что прод-профиль включает `--cache-prompt` и warm-up заполнил кэш;
  контроль prefill — это `prefill-4k` (3082 фактических токена промпта).

## Артефакты

- DeepSeek smoke: `20260915-215123-*baseline-latency-32k-q8kv`,
  `20260915-215208-*dp2a-latency-32k-q8kv`.
- Пары DeepSeek decode-500: `20260915-215245`, `215331`; `215408`, `215454`;
  `215532`, `215617`.
- Qwen smoke: `20260915-213057-*baseline-native-262k`,
  `20260915-213235-*dp2a-native-262k`.
- Пары Qwen decode-500: `20260915-213422`, `213604`; `213739`, `213914`;
  `214047`, `214223`; `214356`, `214531`; `214705`, `214840`.
- Пары Qwen prefill-4k: `20260915-215717`, `215947`; `220127`, `220302`;
  `220436`, `220611`; `220745`, `220919`; `221054`, `221228`.
- Пары Qwen repo-28k: `20260915-221402`, `221652`; `221941`, `222231`;
  `222520`, `222810`; `223059`, `223349`; `223639`, `223929`.
- Сохранённый неудачный прогон той же сессии:
  `20260915-213003-*baseline-latency-32k-q8kv` (в тот момент отсутствовал GGUF
  DeepSeek; оставлен, не удалён).

## Решение

- **Принять DP2A для трёх-GPU профиля Qwen3.6-35B-A3B Q4_K_P.** Он превышает
  порог 10% медианного decode без регрессий корректности, VRAM, prefill и
  стабильности.
- Активировано в проде 15.09.2026: hub-профиль
  `run-commands/actual/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native.sh`
  теперь по умолчанию использует `LLAMA_SERVER` =
  `tools/llama-cpp/qwen36-df03399-dp2a/bin/llama-server`. Сервис был
  остановлен и запущен через API hub; `/health` вернул 200 примерно через
  85 с, backend в hub показывает DP2A-бинарь как `healthy`, а живой
  инференс-smoke вернул `2 + 2 = 4` с `finish_reason=stop`.
- Откат: baseline-рантайм остаётся упакованным, а
  `run-commands/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native-baseline.sh`
  и переопределение `LLAMA_SERVER=<путь к baseline>` возвращают DP4A без
  пересборки.
- Активированный лаунчер следует версии скрипта, отредактированной до теста,
  где нет `--spec-draft-device CUDA1`; в бенчмарк-argv этот флаг был. Это
  различие только в размещении, и испытанное размещение было пессимистичным
  для DP2A-пути на RTX, поэтому принятый выигрыш должен как минимум
  сохраниться.
- Не обобщать результат на другие квантования и профили. Результат Q8 на одной
  CMP от 11.08.2026 остался ниже порога, а RTX 2080 Ti тоже исполняет
  DP2A-ядра, потому что опция compile-time и действует на весь бинарь;
  измеренный выигрыш трёх GPU — это сумма обеих CMP и стадии RTX. Для
  конфигураций только на CMP результат, таким образом, консервативен.

## Оговорки

- В испытанном benchmark-argv есть `--spec-draft-device CUDA1`, которого живой
  лаунчер больше не задаёт (скрипт отредактировали после старта живого
  сервера). Сравнение — это разница ядер; измеренный профиль размещал
  MTP-голову драфта на RTX, что является пессимистичным размещением для
  DP2A-пути на RTX.
- Это исследовательский результат на `df03399`, а не upstream-рекомендация.
  PR #25834 всё ещё не влит; локальный порт нужно перебазировать для любого
  более позднего коммита.
- У Qwen3.6 поле `content` часто пустое в коротких прогонах, потому что
  reasoning съедает бюджет; корректность подтверждается байт-равенством,
  счётчиками токенов и finish reason, плюс контроль на DeepSeek.

## Воспроизведение

```bash
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-baseline.json \
  --variant native-262k --cases decode-500 --repetitions 1

python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

Сборки: CMake configure из worktree `df03399` с флагами выше и
`cmake --build <dir> --target llama-server` внутри memory-guarded
`systemd-run` юнита.
