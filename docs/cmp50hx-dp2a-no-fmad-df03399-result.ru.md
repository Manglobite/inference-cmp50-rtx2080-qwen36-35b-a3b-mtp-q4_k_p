# DP2A + `--fmad=false` на Qwen3.6-35B-A3B: результат A/B (df03399)

[English](cmp50hx-dp2a-no-fmad-df03399-result.md) | **Русский**

## Статус

Завершено 16.09.2026. Принято и активировано в проде для испытанного
трёх-GPU профиля Qwen3.6-35B-A3B Q4_K_P. Этот документ закрывает пункт
`--fmad=false` из `cmp50hx-next-session-handoff.md` и заменяет
`cmp50hx-dp2a-df03399-result.md` в роли прод-дефолта.

> **Продолжение в тот же день:** поверх этого рантайма затем приняты
> `--tensor-split 1,3,1` и `--ubatch-size 448` для критичного контекста
> 262,144 (prefill +26%, decode -1.1%). См.
> `docs/benchmarks/cmp50hx-split-ubatch-mtp-df03399-result.md`.

## Вопрос

Улучшает ли флаг nvcc `-fmad=false`, добавленный к уже принятому DP2A-рантайму,
decode на смешанном трёх-GPU профиле без изменения вывода, VRAM и
стабильности, и насколько велик эффект именно от двух карт CMP 50HX?

Ответы:

- Да: медиана decode-500 выросла на 15.0% к DP2A и на 30.1% к baseline.
- Контроль только на CMP показывает +29.6% к DP2A (+119.5% к baseline), то
  есть две стадии CMP выигрывают гораздо больше; стадия RTX 2080 Ti размывает
  суммарный выигрыш, потому что тоже исполняет раздельные FMA.
- Вывод остался байт-идентичным в каждом парном прогоне, выборочный пик VRAM
  не изменился. Два рантайм-кноба (`GGML_CUDA_GRAPH_OPT=1`,
  `GGML_CUDA_P2P=1`) нейтральны, а `--ubatch-size 512` не влезает в VRAM.

## Провенанс

- Исходный коммит: `df03399b885831b2a1603b3abb0d8c156808e363`.
- Патч: тот же портированный патч PR #25834, что и у DP2A-рантайма, SHA-256
  `dd73bdea36f9823c507918a997dbd279c1dff7a8d36cf0408d4151f4f2bf81d0`.
- Рантайм: `tools/llama-cpp/qwen36-df03399-dp2a-no-fmad/` (manifest, хэши,
  README). Опции сборки идентичны `qwen36-df03399-dp2a` плюс
  `-DCMAKE_CUDA_FLAGS=-fmad=false`.
- Проверка флага: `ggml/src/ggml-cuda/.../flags.make` начинается с
  `-fmad=false`; локальный зонд nvcc показал, что `-fmad=false` подавляет
  генерацию FFMA (FFMA=0, генерируются FMUL/FADD) даже когда `-use_fast_math`
  стоит позже в командной строке — а в этой сборке это так. Упакованный
  `libggml-cuda.so` отличается и от baseline, и от DP2A-сборки.
- Защита сборки: последовательный `systemd-run --user` юнит с
  `MemoryMax=16G`, `MemorySwapMax=0`, `--parallel 12`; завершился за 7м32с,
  пик 3.8 ГиБ, swap 0. NVCC 12.4.131, CMake 4.2.3.

## Метод

- Профили: три парных профиля Qwen3.6 отличаются только именем, бинарём и
  build variant (`...-3gpu-df03399-baseline`, `...-dp2a`,
  `...-dp2a-no-fmad`), все `native-262k`: контекст 262,144, один слот,
  q8_0 K/V, Flash Attention, нативный MTP `n-max=1`, `--tensor-split 1,2.25,1`.
- Пара DeepSeek-R1-Qwen3-8B Q4_K_M на одной CMP плюс её no-fmad-собрат
  (`latency-32k-q8kv`, 32K, одна изолированная CMP) изолирует стадию CMP.
- Test 1: чередующиеся циклы `baseline -> DP2A -> no-fmad`, пять циклов для
  `decode-500`, три для `prefill-4k` и `repo-28k`, три для контроля DeepSeek.
- Test 2: A/B только по окружению на no-fmad-рантайме, три цикла на кноб,
  `decode-500`.
- Test 3: свип `--ubatch-size` только на `prefill-4k`, по два повтора на
  значение.
- Те же правила привязки, телеметрии, артефактов и восстановления, что и в
  предыдущем A/B. Прод-сервер остановлен через hub, `idleAfterSeconds`
  выставлен в 0, частоты GPU сброшены на окно тестов, затем всё восстановлено.

## Результаты

Raw `eval` — это decode-токены/с сервера llama.cpp; HTTP — сквозная
пропускная способность генерации.

### Qwen3.6-35B-A3B Q4_K_P, три GPU (целевой профиль, n=5)

| Метрика | Baseline | DP2A | DP2A+no-fmad | no-fmad к DP2A |
| --- | ---: | ---: | ---: | ---: |
| decode-500 raw eval tok/s | 47.78 | 54.04 | **62.17** | **+15.04%** |
| decode-500 HTTP tok/s | 44.487 | 49.873 | 56.762 | +13.81% |
| к baseline | - | +13.10% | **+30.12%** | - |

Raw eval по прогонам (tok/s): baseline 46.17/47.78/47.93/47.92/47.40; DP2A
53.87/54.53/54.17/54.03/54.04; no-fmad 62.17/62.33/61.59/61.96/62.23.

### Qwen3.6-35B-A3B Q4_K_P, prefill-4k (n=3)

| Метрика | Baseline | DP2A | DP2A+no-fmad | no-fmad к DP2A |
| --- | ---: | ---: | ---: | ---: |
| raw prefill tok/s | 372.690 | 373.290 | **431.780** | **+15.67%** |
| raw decode tok/s | 52.080 | 59.360 | 65.260 | +9.94% |
| HTTP tok/s | 11.647 | 11.987 | 13.623 | +13.65% |

Prefill тоже ускоряется: чувствительная к FMA работа FP32 в prefill
выигрывает от разделения mul+add на картах CMP.

### Qwen3.6-35B-A3B Q4_K_P, repo-28k (n=3)

| Метрика | Baseline | DP2A | DP2A+no-fmad | no-fmad к DP2A |
| --- | ---: | ---: | ---: | ---: |
| raw decode tok/s | 43.900 | 49.130 | **52.770** | **+7.41%** |
| HTTP tok/s | 21.427 | 23.651 | 24.421 | +3.26% |
| к baseline | - | +11.91% | +20.21% | - |

Промпт repo-28k в этом профиле отдаётся из prompt-кэша (prompt eval ~4
токена), поэтому это точка только по decode; контроль prefill — `prefill-4k`
выше.

### DeepSeek-R1-Qwen3-8B Q4_K_M, одна изолированная CMP (n=3)

| Метрика | Baseline | DP2A | DP2A+no-fmad | no-fmad к DP2A |
| --- | ---: | ---: | ---: | ---: |
| decode-500 raw eval tok/s | 27.91 | 47.27 | **61.27** | **+29.62%** |
| decode-500 HTTP tok/s | 27.114 | 44.962 | 58.289 | +29.65% |
| к baseline | - | +69.37% | **+119.53%** | - |

Это подтверждает внешние отчёты по CMP 50HX и изолирует источник выигрыша:
стадия CMP с DP2A+no-fmad почти в 2.2 раза быстрее baseline.

### Test 2: env-кнобы на no-fmad-рантайме (n=3, decode-500)

| Кноб | медиана raw eval | к контролю |
| --- | ---: | ---: |
| контроль (no-fmad) | 61.96 | - |
| `GGML_CUDA_GRAPH_OPT=1` | 61.05 | -1.47% |
| `GGML_CUDA_P2P=1` | 61.64 | -0.52% |

Оба нейтральны в пределах шума. Не приняты.

### Test 3: свип `--ubatch-size`, raw prefill tok/s на prefill-4k

| ubatch | raw prefill tok/s | примечание |
| ---: | ---: | --- |
| 56 | 238.98 | n=2 |
| 64 | 258.61 | n=2 |
| 128 | 270.36 | n=2 |
| 256 | **432.56** | n=4, прод-значение |
| 512 | - | CUDA OOM на CMP во время prefill |

Больший ubatch явно лучше на этом смешанном стенде; прод-дефолт 256 — лучший
из испытанных и максимальный, что влезает в 10-гиговые CMP. Падение `ub512`
сохранено в
`benchmarks/results/20260916-083304-llama.cpp-qwen36-df03399-dp2a-no-fmad-ub512/`.

## Корректность, VRAM и стабильность

- Все 21 измеренная пара (3 smoke-пары плюс 5+3+3 Qwen и 3+3 DeepSeek
  performance-пары, плюс нейтральные env-прогоны) вернули байт-идентичные
  completion с равными счётчиками токенов и finish reason.
- Выборочный пик VRAM не изменился между вариантами: Qwen `6787 / 16246 / 8685 MiB`
  (CUDA0/CUDA1/CUDA2) и DeepSeek `7261 MiB` на CMP.
- Ни один server.log не содержит CUDA error, illegal instruction, assertion
  или segfault, кроме намеренного `ub512` OOM. Событий OOM/Xid ядра нет.

## Активация

- Hub-профиль
  `run-commands/actual/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native.sh`
  теперь по умолчанию использует
  `tools/llama-cpp/qwen36-df03399-dp2a-no-fmad/bin/llama-server`.
- Перезапуск через API hub: `/health` 200 примерно через 90 с, backend
  показывает no-fmad-бинарь как `healthy`, живой smoke вернул `2 + 2 = 4` с
  `finish_reason=stop`; `idleAfterSeconds=300` восстановлен.
- Откат: baseline DP4A-лаунчер
  `run-commands/cmp50hx-rtx2080ti-qwen36-35b-a3b-uncensored-q4-native-baseline.sh`,
  либо указать `LLAMA_SERVER` на DP2A-рантайм `qwen36-df03399-dp2a` как
  промежуточный шаг. Оба рантайма остаются упакованными.

## Оговорки

- `--fmad=false` — флаг на весь бинарь; RTX 2080 Ti тоже sm_75 и поэтому тоже
  исполняет раздельные FMA. Выигрыш смешанного профиля (+15.0%) сильно меньше
  выигрыша только CMP (+29.6%). Повиборное (per-device) поведение невозможно
  одной архитектурой и требовало бы отдельных вариантов ядер.
- Патч и флаг — локальные исследовательские артефакты, не upstream. PR #25834
  всё ещё не влит; любой более поздний коммит требует перебазирования и новой
  парной сборки.
- Q8_0 здесь не перепроверялся. Внешние отчёты говорят, что DP2A не помогает
  Q8_0, а `fmad` влияет на FP32, а не на dp4a, поэтому выигрыш Q8 не
  заявляется.
- `--ubatch-size 512` на этом железе нежизнеспособен; держать 256.
- Не обобщать на другие квантования, профили и Ampere CMP
  (`fmad=false` делает FP32 примерно вдвое медленнее на Ampere и CMP 90HX).

## Артефакты

Все каталоги прогонов лежат в `benchmarks/results/20260916-*`:

- Smoke (dp2a-smoke-128): `063650` baseline, `063859` DP2A, `064030` no-fmad
  (Qwen); `064209` baseline, `064302` DP2A, `064332` no-fmad (DeepSeek).
- Циклы Qwen decode-500: baseline `064420/064930/065412/065854/070337`, DP2A
  `064618/065105/065547/070029/070513`, no-fmad
  `064757/065239/065721/070204/070648`.
- Qwen prefill-4k: baseline `070843/071325/071808`, DP2A
  `071018/071500/071943`, no-fmad `071152/071635/072117`.
- Qwen repo-28k: baseline `072250/073113/073935`, DP2A
  `072541/073404/074227`, no-fmad `072832/073655/074516`.
- Контроль DeepSeek: baseline `074822/075033/075230`, DP2A
  `074920/075118/075316`, no-fmad `074958/075156/075353`.
- Test 2: контрольные no-fmad `075454/075940/080313/080623/080930/081237`,
  GRAPH_OPT `075802/080138/080448`, P2P `080756/081103/081411`.
- Test 3: ub128 `081802/082430`, ub256 `081627/082256/082943/083116`, ub56
  `081940/082608`, ub64 `082118/082746`.
- Неудачный прогон `ub512` сохранён в `083304-...-ub512`.

## Воспроизведение

```bash
python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a.json \
  --variant native-262k --cases decode-500 --repetitions 1

python3 benchmarks/scripts/run.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-no-fmad.json \
  --variant native-262k --cases decode-500 --repetitions 1
```

Сборка: configure worktree `df03399` с патчем DP2A и
`-DCMAKE_CUDA_FLAGS=-fmad=false` рядом с прод-флагами, затем
`cmake --build <dir> --target llama-server` внутри memory-guarded
`systemd-run` юнита.
