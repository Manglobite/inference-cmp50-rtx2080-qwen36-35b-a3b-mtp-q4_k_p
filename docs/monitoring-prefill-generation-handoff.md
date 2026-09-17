# Мониторинг prefill и генерации llama-server: передача для агента на другом хосте

Назначение: на другом хосте нужно повторить такую же схему измерения скорости
префила и генерации (и сопутствующей телеметрии). Документ описывает, откуда
берутся цифры, какими скриптами это собирается, по каким формулам считается и
какие правила нельзя нарушать, чтобы замеры были сопоставимы.

## 1. Что измеряем

| Метрика | Что это | Источник |
| --- | --- | --- |
| raw prefill tok/s | скорость prompt eval по реально посчитанным токенам (без prompt-кэша) | строка `prompt eval time` в `server.log` |
| raw generation tok/s | скорость декодирования (eval) | строка `eval time` в `server.log` |
| effective prefill tok/s | пользовательская скорость префила: полный промпт / всё время prompt eval | API usage + `prompt eval time` |
| HTTP tok/s | сквозная генерация (включая префил и сеть) | замер вокруг HTTP-запроса |
| cache hit | доля промпта, взятого из кэша | `1 - evaluated_tokens / prompt_tokens` |
| MTP acceptance | доля принятых драфт-токенов и средняя длина | строки `draft acceptance` или `/metrics` |
| context fill | заполнение контекста после каждого сообщения | `prompt_tokens / context_tokens` |
| телеметрия GPU | температура/загрузка/память/мощность каждой карты | `nvidia-smi`, CSV каждые 0.5 с |
| телеметрия хоста | CPU нагрузка/температура, RAM, swap | `/proc/stat`, thermal zones, `/proc/meminfo` |
| ошибки | CUDA/OOM/segfault | `server.log`, журнал ядра |

## 2. Откуда берутся raw-тайминги

llama-server пишет в stdout (его мы перенаправляем в `server.log`) строки вида:

```text
0.467 I slot print_timing: id  0 | task 19 | prompt eval time =    467.08 ms /     4 tokens (  116.77 ms per token,     8.56 tokens per second)
0.222 I slot print_timing: id  0 | task 19 |        eval time =   2547.49 ms /   128 tokens (   19.90 ms per token,    56.98 tokens per second)
0.301 I slot print_timing: id  0 | task 19 |       total time =   3014.57 ms /   132 tokens
0.310 I slot print_timing: id  0 | task 19 |    draft acceptance = 0.86517 (  231 accepted /  267 generated), mean len = 1.87
```

Ключевые детали:
- `prompt eval time` содержит **число реально посчитанных токенов** — по нему
  вычисляется попадание в prompt-кэш; полный размер промпта берётся из ответа
  API (`usage.prompt_tokens`).
- `eval time` — это raw generation, наша основная метрика decode.
- В ревизии `df03399` строки `n_decoded ... tg = ...` **не логируются**, поэтому
  не ищите `tg` — используйте `eval time`.
- Строки идут по каждой задаче (`task N`); прогревочный запрос — первая задача,
  её нужно отбрасывать при сопоставлении с кейсами.
- Регулярка парсинга (в `run.py` и `run_context_ladder.py`):
  `id\s+(\d+)\s+\|\s+task\s+(\d+)\s+\|\s+(prompt eval time|eval time|total time|n_decoded|draft acceptance)\s*=\s*(.*)`,
  затем из `values` вытаскиваются `ms`, `tokens`, `tokens_per_second`.

## 3. MTP acceptance через /metrics

Когда логов недостаточно (или нужен acceptance по конкретному запросу), сервер
с флагом `--metrics` отдаёт Prometheus-метрики:

```text
llamacpp:spec_decode_num_draft_tokens_total
llamacpp:spec_decode_num_accepted_tokens_total
llamacpp:spec_decode_num_drafts_total
```

Замер «до/после» запроса даёт:

```text
acceptance        = Δaccepted / Δdraft_tokens
mean accepted/step = Δaccepted / Δdrafts
```

Пример из наших тестов: структурный текст (числа, код) — acceptance 99.6%,
2.99 принятых токена на шаг, 88–95 tok/s; креативная проза — 47.6%, 1.42,
63–65 tok/s. Поэтому сравнивать прогоны можно только на однотипном тексте.

## 4. Скрипты сбора (что копировать на другой хост)

Все лежат в `benchmarks/scripts/` этого кейса:

| Скрипт | Назначение |
| --- | --- |
| `run.py` | основной harness: стартует сервер по профилю, делает warm-up, прогоняет кейсы, парсит лог, пишет `result.json` с `raw_server_timing`, запускает GPU-телеметрию |
| `host_telemetry.py` | пишет `host-telemetry.csv` каждые 0.5 с: CPU %, CPU °C, RAM/swap ГиБ, по каждой GPU temp/util/mem/power |
| `run_context_ladder.py` | лесенка запросов в одной/двух сессиях: prefill, generation, cache hit, context fill по каждому сообщению |
| `run_design_session.py` | многоходовой диалог с инструментами; логирует `context_fill_pct` и временные окна (`started_epoch`/`ended_epoch`) для оконной телеметрии, пишет `messages.csv` |
| `build_context_ladder.py` | собирает промпты нужного размера и проверяет их токены через `/tokenize` |
| `collect_env.py` | провенанс: путь и SHA-256 бинаря, версия, конфиг GPU |

Требования к раскладке: скрипты вычисляют корень как `parents[2]` от своего
файла, поэтому их место — `<root>/benchmarks/scripts/`, а рабочие каталоги —
`<root>/benchmarks/{profiles,prompts,results}`. Профили ссылаются на бинарь и
модель путями от корня; если структура другая — поправьте `ROOT` в скрипте или
сделайте симлинки. GPU-телеметрия в `run.py` — это отдельный процесс
`nvidia-smi --loop-ms=500`, поэтому `host_telemetry.py` можно не запускать,
если достаточно только GPU.

## 5. Формулы

```text
raw_prefill_tps   = prompt_eval.tokens / (prompt_eval.ms / 1000)
raw_gen_tps       = eval.tokens        / (eval.ms / 1000)
effective_prefill = usage.prompt_tokens / (prompt_eval.ms / 1000)
cache_hit         = 1 - prompt_eval.tokens / usage.prompt_tokens
http_tps          = usage.completion_tokens / wall_seconds
context_fill_pct  = 100 * usage.prompt_tokens / context_tokens
```

`raw_prefill_tps` завышается, когда промпт частично закэширован (в знаменателе
только новые токены) — для пользовательской картины всегда приводите
`effective_prefill`.

## 6. Протокол измерений (обязательные правила)

1. Привязка: `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA_VISIBLE_DEVICES`,
   `--device`; сохранять `gpu-binding.json`. Проверять, что нужные карты
   свободны, а лишние простаивают (телеметрия это подтверждает).
2. Байт-идентичность выводов при `temperature 0` до сравнения скоростей. Если
   ускорение меняет вывод — это другой эксперимент.
3. Один сервер на прогон; чередование A/B/A/B; 3–5 точек на вариант; всё
   остальное (модель, контекст, KV, batch/ubatch, FA, MTP, промпт) неизменно.
4. Менять одну ось за раз (патч / fmad / split / ubatch / MTP) — не смешивать.
5. `--parallel 1` означает очередь: если во время замера летит чужой запрос,
   цифры падают (у нас первый запрос показал 25.8 t/s вместо 95.1). Замерять
   только на простое.
6. Idle-локи частот: если вашим сервером управляет control plane, он может
   держать GPU на 300 МГц после простоя. На время
   тестов выключайте idle-лок (`idleAfterSeconds=0`) и сбрасывайте частоты.
7. Не путать типы текста: MTP даёт разный acceptance на прозе и на
   структурированном тексте — сравнивайте одинаковые промпты.
8. Сохранять неудачные прогоны: они фиксируют границы OOM и стабильности.

## 7. Минимальный профиль для запуска

```json
{
  "engine": "llama.cpp",
  "name": "llama-local-<model>",
  "model_path": "models/model.gguf",
  "served_model_name": "model",
  "binary": "llama.cpp/runtime/bin/llama-server",
  "build_variant": "local",
  "gpu": {"pci_bus_id": "00000000:03:00.0", "cuda_visible_devices": "0", "llama_device": "CUDA0"},
  "base_args": ["-ngl", "all", "--split-mode", "none", "--fit", "off",
                "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
                "--threads", "4", "--metrics"],
  "profiles": {"native-32k": {"context_tokens": 32768, "parallel_sequences": 1, "port": 18101}}
}
```

`context_tokens`, `parallel_sequences` и `port` harness передаёт сам; всё
остальное кладите в `base_args`. Для многосессионного теста поставьте
`parallel_sequences: 2` и помните, что контекст делится между слотами.

## 8. Порядок действий на новом хосте

```bash
# 1. скопировать harness
mkdir -p <root>/benchmarks/{scripts,profiles,prompts,results}
cp -r <case>/benchmarks/scripts/* <root>/benchmarks/scripts/

# 2. подготовить профиль под свой бинарь/модель (см. пример выше)

# 3. smoke-прогон и проверка полей
python3 benchmarks/scripts/run.py --profile benchmarks/profiles/<profile>.json \
  --variant <variant> --cases decode-500 --repetitions 1
python3 - <<'EOF'
import json,glob
d=sorted(glob.glob('benchmarks/results/*/result.json'))[-1]
r=json.load(open(d)); t=r['results'][0]['raw_server_timing']
print('eval', t['eval']['tokens_per_second'], 'prompt', t['prompt_eval']['tokens_per_second'])
EOF

# 4. лесенка по контексту (hello -> 10k -> 75k -> повтор)
python3 benchmarks/scripts/build_context_ladder.py --base-url http://127.0.0.1:<port> \
  --targets 10000,75000 --out benchmarks/prompts/context-ladder.json
python3 benchmarks/scripts/run_context_ladder.py --profile <profile> --variant <variant> \
  --steps <case>/benchmarks/prompts/context-ladder-steps-test1.json \
  --prompts benchmarks/prompts/context-ladder.json --label test1
```

Ожидаемая проверка работоспособности схемы: в `result.json` присутствуют
`raw_server_timing.prompt_eval/eval`, в `host-telemetry.csv` — колонки
`cpu_pct/cpu_temp_c/ram_used_gib/swap_used_gib` и `gpuN_*`, а повторный запрос
с тем же промптом даёт `prompt eval` в единицы токенов (кэш ~100%).

## 9. Частые ловушки

| Симптом | Причина | Что делать |
| --- | --- | --- |
| `tokens_per_second` для prompt eval аномально высокий | промпт взят из кэша | смотреть effective_prefill и evaluated_tokens |
| Нет acceptance-строк | работал MTP, но лог не в той ревизии | брать `/metrics` (Δ по запросу) |
| Скорость ниже ожидаемой в первом запросе | idle-лок частот или очередь при `--parallel 1` | выключить idle-лок, дождаться простоя |
| Огромный `server.log` | `-lv 5` для диагностики планировщика | включать только на коротком кейсе |
| Разные медианы на одинаковом конфиге | разный текст промпта/вывода | фиксировать промпты и тип генерации |
