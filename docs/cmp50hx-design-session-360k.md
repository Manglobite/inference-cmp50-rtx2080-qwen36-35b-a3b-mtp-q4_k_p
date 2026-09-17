# Design-session test at 360K: microblog service, agent-style tools (16-17.09.2026)

## Status

Completed 2026-09-17 (session started 2026-09-16 00:30 UTC). The adopted
RTX-tail configuration was used with context 368,640. The model acted as a
backend architect in a six-step Russian dialogue while the harness simulated an
agent environment with deterministic tools. Server stopped after the session;
the hub-managed server was restarted afterwards.

## Setup

- Profile: `benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json`
  (`--device CUDA0,CUDA2,CUDA1`, `--tensor-split 1,1,2.5`, ub448, MTP
  `n-max=3`, no-fmad runtime, ctx 368,640, q8 KV, FA, prompt cache).
- Driver: `benchmarks/scripts/run_design_session.py`; script:
  `benchmarks/prompts/design-session-360k.json` (system prompt plus six user
  turns); telemetry: `host_telemetry.py` at 0.5 s.
- Simulated environment tools, executed by the harness, not the model:
  - `run_sqlite(sql)` — real execution in a fresh in-memory SQLite per call,
    returning result rows/errors and the created table list;
  - `write_file` / `read_file` — sandboxed artifacts under the run directory;
  - `calc(expression)` — restricted AST arithmetic.
- The model was asked in Russian to design a short-message service without
  naming any product: entities, DB schema, storage and feed delivery, favorites
  and likes, moderation/privacy, then a final specification.

## Measured metrics

| Metric | Value |
| --- | --- |
| API calls | 19 (13 with tool calls) |
| Max prompt size reached | 12,141 tokens |
| Total generated | 9,378 tokens |
| Sum of API wall time | 138 s |
| Evaluated (non-cached) prompt tokens per call | 26-1,035 |
| Prefill rate for new chunks | median 82.0, max 332.5 tok/s |
| Generation rate | median 95.7, range 80.8-115.3 tok/s |
| MTP draft mean length | 2.80-4.00 |
| Tool calls | run_sqlite x6, write_file x4, calc x2, read_file x1 |
| Tool errors and recovery | 2 (query before CREATE; NOT NULL insert) - both fixed by the model in the next round |

The session is incremental: each turn appends a few hundred to ~1,000 new
tokens, so almost all prefill is served from the prompt cache (26-1,035
evaluated tokens per call) and per-call wall time is dominated by generation.
Measured prefill for genuinely new chunks (tool results, new system text)
ranges 38-332 tok/s depending on chunk size.

### System telemetry (maxima over 500 ms samples)

| Resource | Peak |
| --- | --- |
| CPU | 18% load, 46 C |
| RAM | 12.5 GiB used |
| Swap | 1.62 GiB |
| CMP0 | 47 C, 100% util, 8,221 MiB, 143 W |
| RTX 2080 Ti | 57 C, 100% util, 21,942 MiB, 277 W |
| CMP2 | 48 C, 100% util, 7,527 MiB, 123 W |

RTX headroom is again the tightest at ~0.6 GiB with the 360k KV reservation.

## Evaluation of the produced design

Artifacts: `schema.sql` (67 lines) and `design.md` (70 lines) in the run's
`artifacts/` directory; full dialogue in `dialogue.md` and
`transcript.jsonl`.

Strengths:

- Correct entity set: `users`, `posts`, `follows`, `likes`, `bookmarks`.
- Composite primary keys on `follows`, `likes`, `bookmarks` give natural
  idempotency for follow/like/bookmark operations, and the self-follow case is
  blocked by `CHECK (follower_id != following_id)`.
- Indexes cover both directions of `follows` and per-user/per-post lookups for
  reactions; `posts(created_at DESC)` supports time ordering.
- `posts.likes_count` / `bookmarks_count` plus a documented recount job show
  awareness of hot-row counter pressure.
- Feed model is the standard hybrid: fan-out on write with a pull path for
  celebrity accounts, plus Redis caching and invalidation on publish.
- Moderation/privacy are addressed: `status = 'APPROVED'` filter, `is_banned`,
  `is_private` with an `EXISTS` subscription check in the feed query, soft
  delete with `deleted_at`, retention/archival policy.
- The model used the tools sensibly: validated DDL in SQLite, saved the schema,
  computed storage estimates, wrote and re-read the final specification, and
  recovered from both tool errors without being told.

Gaps and risks (my assessment):

1. `user_feed` is described in `design.md` but is missing from `schema.sql`;
   the specification and DDL do not match.
2. Pagination: the text mentions cursor pagination but the shipped queries use
   `OFFSET`; a keyset index such as `(user_id, created_at DESC, post_id)` is
   absent, so deep pages will not scale.
3. Counter updates run as a separate `UPDATE` after the `INSERT` and are not
   shown inside a transaction, so concurrent likes can drift; the cron recount
   mitigates but does not prevent it.
4. A `blocks` table is missing although "блокировки" are mentioned; `is_banned`
   only covers global bans, not user-to-user blocks.
5. No `CHECK` constraint on `posts.status`, no edit timestamp/history, no media,
   hashtags or mentions (the model asked about them, the scripted user did not
   answer).
6. `ON DELETE CASCADE` from `posts`/`users` contradicts the soft-delete policy:
   hard-deleting a user would erase all content instead of anonymizing or
   retaining it.
7. The privacy filter (`OR EXISTS`) is evaluated per feed query and will not
   scale; visibility should be resolved at fan-out time or denormalized.
8. Storage estimate is directionally right (~3.5 TB total, ~1.5 TB for the
   feed table) but the feed row count formula is hand-waved
   (10^7 x 100 x 100) and index overhead is estimated at a flat x2.
9. API specification, partition/sharding keys and cache invalidation details
   are listed as "next steps", not delivered.

Verdict: a solid mid-level design and a successful end-to-end agent session.
It is usable as a starting point, but before implementation it needs the feed
table in the DDL, keyset pagination, a blocks table, atomic counter updates,
a consistent hard-vs-soft delete policy, and a scalable visibility model.

## Artifacts

`benchmarks/results/20260917-003005-llama.cpp-qwen36-df03399-dp2a-ladder-360k-p1-design-360k/`:

- `dialogue.md` (45 KB) - readable Russian dialogue with tool calls/results;
- `transcript.jsonl` (69 KB) - structured events (user/assistant/tool results);
- `artifacts/schema.sql`, `artifacts/design.md` - the produced design;
- `metrics.json`, `host-telemetry.csv`, `server.log`, `tools.json`,
  `script.json`, `command.json`, `build-variant.json`.

## Reproduce

```bash
python3 benchmarks/scripts/run_design_session.py \
  --profile benchmarks/profiles/llama-cpp-qwen36-35b-a3b-uncensored-q4-3gpu-df03399-dp2a-ladder-360k-p1.json \
  --variant native \
  --script benchmarks/prompts/design-session-360k.json \
  --label design-360k
```
