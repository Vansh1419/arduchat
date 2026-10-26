# ArduChat — ArduPilot Copter documentation assistant

ArduChat answers questions about **ArduPilot Copter** using the official docs at <https://ardupilot.org/copter/docs/>. Every answer is grounded in retrieved documentation excerpts and comes with source links.

- **Backend:** FastAPI, one process, stateless (`app/`)
- **Frontend:** React + TypeScript + Tailwind SPA (`web/`), served by the same FastAPI process
- **Retrieval:** a read-only index shipped in the repo (`data/`): dense search (fastembed `BAAI/bge-small-en-v1.5`) fused with BM25 by reciprocal rank fusion
- **LLM:** Groq, default `openai/gpt-oss-20b` (set `GROQ_MODEL` to change)
- **Chat history:** kept in the user's browser (localStorage); the server stores nothing
- **Deploy:** one Docker image on Railway (`Dockerfile`, `railway.json`)

## How a request flows

```
Browser (React SPA, sessions in localStorage)
   │  POST /chat {message, history[last ≤10 turns]}    ◄── answer streamed back as SSE
   ▼
FastAPI
   1. per-IP rate limit (10/min, 100/day)
   2. trim history to 8,000 chars; reject prompt-injection patterns
   3. retrieve: embed previous user turns + message → dense top-50 + BM25 top-50 → RRF → top 3 chunks
   4. grounding check: best dense score < 0.65 → "not found in the docs" (no LLM call)
   5. app-wide Groq token budget (per minute / per day) → 503 + Retry-After when exhausted
   6. Groq streaming call (reasoning hidden, reasoning_effort=low, max 1,000 completion tokens)
   7. output checks: prompt-leak check, unknown parameter names / links replaced,
      "answer cut short" note, safety disclaimer for flight-critical topics
```

Docs are never scraped at request time. The index is built offline and loaded into memory at startup (about 400 MB RSS, almost all of it the embedding model).

### SSE events

| Event | Data | Meaning |
|---|---|---|
| `sources` | `[{url, title}]` | pages the answer is based on |
| `token` | string | next piece of the answer |
| `replace` | string | the validated answer; swap it in for everything streamed so far |
| `disclaimer` | string | safety warning, shown separately from the answer |
| `refused` | `blocked` or `not_found` | request refused (followed by a `token` with the refusal text) |
| `error` | string | the stream failed after it had started |
| `done` | null | end of stream |

HTTP errors: `422` invalid body, `429` per-IP limit, `503` Groq/app-wide token limit (both carry `Retry-After`), `502` model unavailable.

## Project layout

```
app/
  main.py        FastAPI app: /health, POST /chat, serves web/dist
  chat.py        request schema, system prompt, Groq call, SSE events
  index.py       loads data/, dense + BM25 hybrid search, parameter lookup
  guardrails.py  rate limit, token budget, injection check, grounding, output validation, disclaimer
  config.py      environment-driven settings
  links/         links_result_deduped.json — the URL list the index builder reads
data/            the shipped index: chunks.jsonl, embeddings.npy, params.json, build_report.json
                 (data/cache/ holds raw HTML for rebuilds and is git-ignored)
scripts/build_index.py   offline index builder
web/             React app (src/App.tsx, Chat.tsx, Sidebar.tsx, api.ts, storage.ts)
evals/           pytest evaluation harness (golden.json = 55 questions)
loadtest/        fake_groq.py + run.py concurrent load test
Dockerfile, .dockerignore, railway.json
```

## Run it locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 24 (only to build the UI).

```bash
cp .env.example .env            # put your GROQ_API_KEY in it
uv sync                         # runtime dependencies
(cd web && npm ci && npm run build)
uv run uvicorn app.main:app --port 8000
# open http://localhost:8000
```

For UI development run `npm run dev` in `web/`; Vite proxies `/chat` and `/health` to port 8000.

## Configuration

Only `GROQ_API_KEY` is required.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Groq credentials |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | chat model |
| `GROQ_REASONING_EFFORT` | `low` | `low`/`medium`/`high` for gpt-oss models; set empty for other models |
| `GROQ_MAX_COMPLETION_TOKENS` | `1000` | cap per answer |
| `GROQ_TOKENS_PER_MINUTE` | `8000` | app-wide budget (Groq free tier) |
| `GROQ_TOKENS_PER_DAY` | `200000` | app-wide budget (Groq free tier) |
| `GROQ_TIMEOUT`, `GROQ_MAX_RETRIES` | `30`, `2` | Groq client |
| `GROQ_BASE_URL` | Groq | point at `loadtest/fake_groq.py` for load tests |
| `DATA_DIR` | `data` | which index to load |
| `PORT` | `8000` | set by Railway |

The two token budgets are in-process and per instance. After upgrading the Groq plan, raise both.

## Capacity

The limit is the Groq quota, not the server. The free tier allows 8,000 tokens/minute, 200,000 tokens/day and 1,000 requests/day per model, shared by every user. At about 1,900 tokens per chat that is roughly **100 chats per day** for the whole app. When the quota is used up the UI shows how long to wait. For real traffic, move to a paid Groq plan and raise the two budget variables.

## Rebuilding the index

Only needed when the docs change. Needs the build group:

```bash
uv sync --group build
python scripts/build_index.py            # fetch (cached) → clean → chunk → embed → data/
```

The builder skips `parameters-Copter-*` version dumps and `binary-features.html`, caps each page at 40 chunks, prepends each page title to the text it embeds, and writes failed URLs and capped pages to `data/build_report.json`. Current index: 839 pages, 4,226 chunks, 5,699 parameter names. Commit the new `data/` files. `--out DIR` builds a comparison index; point `DATA_DIR` at it to evaluate it.

## Guardrails

- **Input:** message ≤ 2,000 chars, ≤ 10 history turns, history trimmed to 8,000 chars; regex check for injection attempts (ignore-instructions, system-prompt requests, role-play, fake `<system>` tags). This is not a complete defence.
- **Grounding:** weak retrieval (best cosine score < 0.65) is refused without calling the LLM.
- **Prompt:** documentation is wrapped in `<docs>` and declared untrusted; the model is told to use only the listed links and parameter names.
- **Output:** prompt-leak detection; parameter-like tokens and links not present in the retrieved context are replaced; truncated answers get a note.
- **Safety disclaimer** for arming, failsafe/RTL, PID/tuning, motor/ESC/propeller tests and crash-related topics (keyword heuristic in `app/guardrails.py`).
- **Abuse control:** per-IP rate limit using `X-Real-IP` with socket fallback. No accounts.

## Tests and evals

```bash
uv sync --group dev --group build
uv run pytest evals                          # fast tier, no Groq calls: label check, retrieval, guardrails, validator, limiters
uv run pytest evals -m slow -s               # real answers + LLM judge (openai/gpt-oss-120b); spends Groq quota
EVAL_SUBSET=1 uv run pytest evals -m slow -s # 15 cases, ~45k tokens instead of ~100k
```

Measured on the golden set: hit@k 0.95+, answerable rate 1.00, 6 of 7 off-topic questions refused by the grounding gate (the rest declined by the model). Floors in the tests come from measured baselines. Run the slow tier at most once or twice a day on the free quota.

## Load test

```bash
python loadtest/fake_groq.py &                                              # fake streaming Groq on :9000
GROQ_BASE_URL=http://localhost:9000 GROQ_TOKENS_PER_MINUTE=100000000 GROQ_TOKENS_PER_DAY=100000000 \
  uv run uvicorn app.main:app --port 8000 &
python loadtest/run.py --url http://localhost:8000 --users 50 --requests 2 --pid <uvicorn pid>
```

Raise the budgets for this run, otherwise the app-wide budget rejects most requests by design. Result on macOS with one worker: 10×3, 50×2 and 100×1 concurrent users all succeeded, time-to-first-token p95 under 0.3 s, peak RSS about 396 MB with no growth.

## Deploy (Railway)

1. Connect the repo; Railway builds the `Dockerfile` (stage 1 builds the React app, stage 2 runs one uvicorn worker as a non-root user with the embedding model baked in).
2. Set `GROQ_API_KEY` (and optionally `GROQ_MODEL`) in the service variables. `railway.json` sets the `/health` healthcheck.
3. After the first deploy, confirm that a client-supplied `X-Real-IP` header does not override the real client address: send requests with a fake header and check that the rate limit still applies per real client. If it is overridable, change `client_ip` in `app/guardrails.py`.

Keep this to **one worker and one instance**: the rate limiter and token budgets live in process memory.

## Known limitations

- Copter docs only, English only; questions about older firmware parameters are not answerable (version dumps are excluded from the index).
- The parameter allow-list is lexical: only parameters that appear in the retrieved chunks or the question can be mentioned, so vague questions may get no parameter names.
- The injection check is pattern based; obfuscated attempts are only caught if they leak the prompt or fail grounding.
- Rate limiter and token budgets reset on restart and are not shared between instances.
- Container memory and the in-container load test are not yet measured (macOS numbers above).
- Chat history lives only in the browser; clearing site data deletes it (the UI has JSON export/import).

Design decisions and their reasons are in `decision.md`; the build log is in `steps.md`.
