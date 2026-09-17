# Two Go design sessions with a chaotic user at 360K (17.09.2026)

**English** | [Русский](cmp50hx-design-sessions-go-2apps.ru.md)

## Status

Completed 2026-09-17. Two full design sessions on the adopted RTX-tail 360k
configuration (ctx 368,640). The server was stopped during the sessions and
restarted afterwards.

## Setup

- Profile: `benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json`
  (RTX tail `1,1,2.5`, ub448, MTP `n-max=3`, no-fmad runtime).
- Driver: `benchmarks/scripts/run_design_session.py`; telemetry 0.5 s
  (`host_telemetry.py`); per-message telemetry is aggregated over each call's
  time window.
- Two applications, both Go server + `html/template`:
  1. **URL shortener with analytics** - scripts:
     `benchmarks/prompts/design-session-shortener-360k.json`;
  2. **Personal expense tracker with budgets** - scripts:
     `benchmarks/prompts/design-session-expenses-360k.json`.
- Persona: an impatient, not very technical user who asks off-topic and
  illogical questions (hosting cost before schema, Telegram bot, SMS parsing,
  Turkey/lira, offline in the metro), contradicts earlier decisions (file
  instead of a DB, "anyone can delete"), criticizes the complexity, and asks
  for impossible or unsafe things. Tools available to the model, executed by
  the harness: `run_sqlite` (real in-memory SQLite), `write_file`/`read_file`
  (sandbox), `calc`.

## Summary

| Metric | Shortener | Expenses |
| --- | ---: | ---: |
| API calls | 19 | 27 |
| Tool calls | run_sqlite x6, write_file x5 | run_sqlite x7, write_file x11, calc x1 |
| Tool errors (recovered) | 1 | 3 |
| Max context fill | 2.19% (8,084 tokens) | 5.06% (18,653 tokens) |
| Total generated | 7,033 tokens | 17,043 tokens |
| Prefill median / max | 65 / 315 tok/s | 66 / 228 tok/s |
| Generation median / range | 84.6 / 66-114 tok/s | 97.9 / 77-112 tok/s |
| Produced artifacts | main.go, go.mod, index.html, result.html, design.md | main.go, index.html, login.html, design.md |

Both `main.go` files parse cleanly (`gofmt -e`); they are valid Go scaffolds,
not merely pseudo-code.

## Per-message tables

### Shortener

| # | шаг | контекст, % | prompt | пересчит. | prefill t/s | генерация t/s | acc | время, с | CPU % | CPU °C | RAM ГиБ | CMP0 °C/мем | RTX °C/мем | CMP2 °C/мем |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 1 | 1.1 | 0.20 | 726 | 726 | 199.3 | 66.1 | 2.56 | 6.5 | 14 | 44 | 7.8 | 45/8221 | 47/21940 | 46/7527 |
| 2 | 2.1 | 0.25 | 929 | 47 | 65.1 | 76.8 | 2.56 | 5.7 | 13 | 45 | 8.0 | 45/8221 | 48/21940 | 45/7527 |
| 3 | 3.1 | 0.36 | 1325 | 53 | 54.4 | 76.9 | 2.56 | 6.1 | 14 | 45 | 8.4 | 45/8221 | 50/21940 | 45/7527 |
| 4 | 4.1 | 0.47 | 1726 | 56 | 54.9 | 84.6 | 2.88 | 5.3 | 15 | 45 | 8.4 | 45/8221 | 50/21940 | 45/7527 |
| 5 | 5.1 | 0.56 | 2073 | 351 | 185.4 | 76.3 | 2.73 | 5.4 | 16 | 45 | 8.9 | 45/8221 | 50/21940 | 45/7527 |
| 6 | 5.2 | 0.63 | 2326 | 257 | 167.2 | 97.6 | 3.59 | 3.2 | 13 | 45 | 9.5 | 46/8221 | 50/21940 | 45/7527 |
| 7 | 5.3 | 0.67 | 2459 | 36 | 54.0 | 84.0 | 2.79 | 3.9 | 10 | 45 | 9.6 | 45/8221 | 51/21942 | 46/7527 |
| 8 | 6.1 | 0.74 | 2723 | 52 | 54.2 | 75.8 | 2.54 | 4.2 | 11 | 45 | 9.6 | 45/8221 | 51/21942 | 46/7527 |
| 9 | 6.2 | 0.80 | 2937 | 26 | 41.3 | 108.6 | 3.67 | 2.4 | 13 | 44 | 9.6 | 45/8221 | 51/21942 | 45/7527 |
| 10 | 6.3 | 0.84 | 3085 | 38 | 54.2 | 91.2 | 3.05 | 5.4 | 13 | 45 | 9.6 | 46/8221 | 52/21942 | 46/7527 |
| 11 | 7.1 | 0.95 | 3493 | 45 | 64.9 | 83.7 | 2.81 | 5.0 | 13 | 45 | 9.5 | 45/8221 | 53/21942 | 46/7527 |
| 12 | 7.2 | 1.04 | 3820 | 38 | 54.7 | 84.3 | 3.11 | 7.0 | 13 | 45 | 9.6 | 46/8221 | 53/21942 | 46/7527 |
| 13 | 8.1 | 1.18 | 4345 | 61 | 81.1 | 113.7 | 4.00 | 2.8 | 14 | 45 | 9.6 | 45/8221 | 53/21942 | 46/7527 |
| 14 | 8.2 | 1.23 | 4534 | 45 | 62.1 | 94.6 | 3.27 | 10.3 | 16 | 45 | 9.6 | 46/8221 | 55/21942 | 46/7527 |
| 15 | 8.3 | 1.47 | 5419 | 889 | 314.7 | 105.5 | 3.68 | 6.3 | 15 | 45 | 10.2 | 47/8221 | 54/21942 | 47/7527 |
| 16 | 8.4 | 1.56 | 5742 | 51 | 66.5 | 104.1 | 3.62 | 6.5 | 17 | 46 | 10.2 | 46/8221 | 55/21942 | 46/7527 |
| 17 | 8.5 | 1.71 | 6300 | 51 | 67.2 | 102.4 | 3.60 | 17.0 | 18 | 46 | 10.2 | 46/8221 | 56/21942 | 47/7527 |
| 18 | 8.6 | 2.15 | 7919 | 51 | 65.7 | 73.5 | 2.72 | 3.4 | 18 | 47 | 10.6 | 46/8221 | 56/21942 | 47/7527 |
| 19 | 8.7 | 2.19 | 8084 | 48 | 62.8 | 85.6 | 3.00 | 7.6 | 19 | 47 | 10.6 | 47/8221 | 57/21942 | 47/7527 |

### Expenses

| # | шаг | контекст, % | prompt | пересчит. | prefill t/s | генерация t/s | acc | время, с | CPU % | CPU °C | RAM ГиБ | CMP0 °C/мем | RTX °C/мем | CMP2 °C/мем |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 1 | 1.1 | 0.19 | 718 | 718 | 229.5 | 81.1 | 2.61 | 7.4 | 19 | 46 | 8.5 | 46/8221 | 51/21940 | 46/7527 |
| 2 | 2.1 | 0.30 | 1105 | 391 | 203.8 | 86.8 | 2.96 | 5.9 | 17 | 46 | 9.1 | 46/8221 | 52/21940 | 46/7527 |
| 3 | 2.2 | 0.40 | 1478 | 377 | 224.5 | 104.0 | 3.50 | 11.6 | 18 | 47 | 9.6 | 46/8221 | 53/21940 | 47/7527 |
| 4 | 2.3 | 0.68 | 2509 | 52 | 72.1 | 112.0 | 3.78 | 9.2 | 19 | 47 | 9.7 | 47/8221 | 55/21940 | 47/7527 |
| 5 | 2.4 | 0.93 | 3440 | 50 | 68.6 | 96.7 | 3.21 | 4.9 | 11 | 46 | 9.8 | 47/8221 | 54/21940 | 47/7527 |
| 6 | 3.1 | 1.04 | 3820 | 46 | 47.7 | 77.0 | 2.54 | 6.9 | 12 | 47 | 9.8 | 47/8221 | 55/21940 | 47/7527 |
| 7 | 4.1 | 1.16 | 4267 | 50 | 49.5 | 81.2 | 2.76 | 5.5 | 12 | 47 | 9.8 | 47/8221 | 56/21940 | 47/7527 |
| 8 | 4.2 | 1.25 | 4604 | 341 | 202.6 | 95.1 | 3.27 | 7.0 | 14 | 47 | 10.4 | 47/8221 | 56/21940 | 48/7527 |
| 9 | 4.3 | 1.38 | 5099 | 60 | 73.4 | 80.0 | 2.71 | 5.5 | 15 | 47 | 10.5 | 47/8221 | 56/21942 | 47/7527 |
| 10 | 5.1 | 1.48 | 5471 | 58 | 75.3 | 100.9 | 3.52 | 16.1 | 16 | 47 | 10.5 | 47/8221 | 58/21942 | 48/7527 |
| 11 | 5.2 | 1.89 | 6983 | 52 | 67.7 | 108.0 | 3.86 | 10.0 | 17 | 47 | 10.6 | 48/8221 | 58/21942 | 48/7527 |
| 12 | 5.3 | 2.15 | 7937 | 51 | 65.9 | 79.5 | 2.72 | 6.0 | 16 | 47 | 10.6 | 48/8221 | 58/21942 | 48/7527 |
| 13 | 6.1 | 2.26 | 8325 | 48 | 46.1 | 99.4 | 3.52 | 17.1 | 12 | 47 | 10.6 | 48/8221 | 59/21942 | 48/7527 |
| 14 | 6.2 | 2.68 | 9875 | 51 | 64.4 | 107.7 | 3.90 | 13.9 | 17 | 47 | 10.7 | 48/8221 | 60/21942 | 48/7527 |
| 15 | 6.3 | 3.05 | 11227 | 54 | 63.8 | 80.4 | 2.89 | 5.0 | 17 | 47 | 10.7 | 48/8221 | 59/21942 | 48/7527 |
| 16 | 7.1 | 3.12 | 11512 | 289 | 140.2 | 83.1 | 2.96 | 5.9 | 15 | 48 | 11.5 | 48/8221 | 59/21942 | 48/7527 |
| 17 | 7.2 | 3.20 | 11784 | 44 | 56.7 | 105.3 | 3.89 | 16.2 | 17 | 48 | 11.5 | 48/8221 | 60/21942 | 48/7527 |
| 18 | 7.3 | 3.62 | 13329 | 51 | 61.4 | 100.1 | 3.67 | 5.5 | 10 | 47 | 11.6 | 48/8221 | 60/21942 | 48/7527 |
| 19 | 7.4 | 3.72 | 13723 | 49 | 59.5 | 105.8 | 3.95 | 15.0 | 12 | 47 | 11.7 | 48/8221 | 60/21942 | 48/7527 |
| 20 | 7.5 | 4.11 | 15146 | 50 | 57.3 | 86.7 | 3.23 | 4.6 | 13 | 46 | 11.7 | 48/8221 | 60/21942 | 48/7527 |
| 21 | 8.1 | 4.18 | 15408 | 266 | 124.9 | 79.3 | 2.96 | 10.9 | 14 | 47 | 12.5 | 49/8221 | 60/21942 | 48/7527 |
| 22 | 8.2 | 4.35 | 16045 | 641 | 228.2 | 97.9 | 3.71 | 7.9 | 15 | 47 | 13.3 | 49/8221 | 60/21942 | 49/7527 |
| 23 | 8.3 | 4.46 | 16435 | 26 | 34.0 | 102.6 | 3.92 | 3.2 | 16 | 47 | 13.3 | 48/8221 | 59/21942 | 48/7527 |
| 24 | 8.4 | 4.49 | 16563 | 26 | 34.4 | 102.8 | 3.95 | 3.8 | 16 | 47 | 13.3 | 48/8221 | 59/21942 | 48/7527 |
| 25 | 8.5 | 4.54 | 16751 | 26 | 34.3 | 101.8 | 3.92 | 4.2 | 17 | 48 | 13.4 | 48/8221 | 59/21942 | 48/7527 |
| 26 | 8.6 | 4.62 | 17049 | 94 | 80.3 | 103.9 | 3.97 | 17.6 | 16 | 48 | 13.4 | 48/8221 | 60/21942 | 49/7527 |
| 27 | 8.7 | 5.06 | 18653 | 49 | 55.3 | 84.1 | 3.19 | 7.0 | 13 | 47 | 13.5 | 48/8221 | 60/21942 | 48/7527 |

## Run-level telemetry maxima

| Run | CPU | RAM | Swap | CMP0 | RTX | CMP2 |
| --- | --- | ---: | ---: | --- | --- | --- |
| Shortener | 19% / 47 C | 10.6 GiB | 2.04 GiB | 47 C, 100%, 8,221 MiB, 140 W | 57 C, 100%, 21,942 MiB, 203 W | 47 C, 100%, 7,527 MiB, 124 W |
| Expenses | 20% / 48 C | 13.5 GiB | 1.78 GiB | 49 C, 100%, 8,221 MiB, 140 W | 60 C, 100%, 21,942 MiB, 212 W | 49 C, 100%, 7,527 MiB, 128 W |

Generation rates stay 66-114 tok/s; new prompt chunks are prefilled at
34-315 tok/s depending on chunk size; incremental turns are served from the
prompt cache (26-94 evaluated tokens in later calls). Context fill never
exceeded 5.06%, so the chaotic dialogue did not stress the 360k window.

## Did the model get confused?

No. Across both sessions the model kept the task thread and behaved well
against the chaotic persona:

- Off-topic questions in illogical order were answered and then redirected:
  hosting cost and Telegram-bot comparison before any schema, SMS parsing,
  Turkey/lira and dark theme mid-design. Each answer ended with a return to
  the design ("Что выбираем?", "Потом вернёмся к таблицам").
- Contradictions were handled with pushback: "хранить в файле вместо БД" was
  answered with SQLite-as-a-file and persistence; "любой может удалять" was
  refused and replaced with password-protected deletion.
- Criticism ("слишком сложно для MVP", "неудобно заполнять формы") led to
  simplification and to a one-line parser (`500 кофе`, `1200 продукты вчера`).
- Impossible or unsafe asks were answered honestly: reading bank SMS directly
  is impossible from a Go server; offline mode explained as PWA caching; role
  splitting was implemented as a toy login and the model itself listed it as a
  risk.
- Tool errors were self-corrected: shortener 1 (query before CREATE), expenses
  3 (`near "2": syntax error`, then queries before CREATE for `expenses` and
  `categories`).

Minor drift observed:

1. In the expenses session, the off-topic scaling question caused the model to
   add a `users` table and restructure the schema without being asked.
2. In the shortener session the model offered "продлить без пароля, если ты на
   странице ссылки" - weak authorization, later not corrected.
3. Both sessions the model claims the code is ready. The code is real and
   parses, but not production-ready (see below), so "готово" is overstated.

## Design and code critique

Shortener:

- `main.go` defines `handleRedirect` but never registers it (the routes are
  `/`, `/delete/`, `/extend/`, `/stats/`, `/qrcode/`), so short links do not
  actually redirect - the central feature is dead code.
- `handleExtend` requires no password at all; deletion is password-protected
  only in the UI flow, with the password stored in plain text.
- Short-code collisions are not retried; `INSERT` failure returns HTTP 500.
- SQLite foreign keys are not enabled (`PRAGMA foreign_keys=ON` absent), so
  `stats.link_id` integrity is not enforced.
- `template.ParseGlob("templates/*.html")` expects a `templates/` directory
  while the artifacts (index.html, result.html) are written at the project
  root; the structure in `design.md` does not match the files produced.
- No rate limiting on link creation and no analytics aggregation (raw per-click
  rows only).

Expenses:

- Authentication is a toy: the login page sets a role cookie after typing
  `admin` or `wife`, with no password or session validation.
- The dashboard sums all expenses regardless of currency and compares the sum
  with a budget in a single currency, so mixed RUB/TRY periods show a wrong
  remainder (the model itself listed this as a risk).
- `expenses.category_id` has an FK but SQLite foreign keys are not enabled;
  the `JOIN` also hides expenses with a missing category.
- The catch-all category fallback maps unknown words to "Развлечения", which
  is misleading; "Без категории" would be safer.
- Budget management is read-only from the UI (only the most recent row is
  used); editing and per-month history are absent.

Verdict: the sessions are a good robustness result - the model absorbed a
chaotic user, asked clarifying questions, pushed back on bad ideas and still
produced coherent designs plus parseable Go scaffolds. The artifacts are
starting points, not finished services: the shortener has a broken redirect
path and both apps need real authentication, currency handling and SQLite
foreign-key pragmas before any deployment.

## Files

- Dialogues (readable Russian logs with per-message metric lines):
  `docs/benchmarks/dialogues/design-shortener-360k.md`,
  `docs/benchmarks/dialogues/design-expenses-360k.md`.
- Per-message tables:
  `docs/benchmarks/dialogues/design-shortener-per-message.md`,
  `docs/benchmarks/dialogues/design-expenses-per-message.md`.
- Raw runs:
  `benchmarks/results/20260917-004432-*design-shortener/`,
  `benchmarks/results/20260917-004834-*design-expenses/`
  (`dialogue.md`, `transcript.jsonl`, `metrics.json`, `messages.csv`,
  `host-telemetry.csv`, `artifacts/`, `server.log`).

## Reproduce

```bash
python3 benchmarks/scripts/run_design_session.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native \
  --script benchmarks/prompts/design-session-shortener-360k.json \
  --label design-shortener
```
