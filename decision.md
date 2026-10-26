# Decisions

Each entry: what was decided, the alternatives, and why. Newest at the bottom.

## D1 — Frontend: React/Vite SPA
- Alternatives: plain HTML/JS, keep Streamlit.
- Why: user choice. Sessions must live in the user's browser storage, which Streamlit (server-side) can't do properly.

## D2 — Embeddings: fastembed (ONNX, local)
- Alternatives: hosted embedding API.
- Why: torch + sentence-transformers is too heavy for the <500MB Railway free tier; fastembed is already a dependency and needs no extra API key.

## D3 — Docs indexing: pre-scrape + pre-embed offline, ship the index
- Alternatives: keep on-demand scraping, hybrid.
- Why: no scraping at request time, predictable latency and RAM.

## D4 — Vector store: read-only file index loaded at startup
- Alternatives: Postgres + pgvector, hosted vector DB.
- Why: docs are static, so no DB server or write contention is needed; smallest footprint.

## D5 — Backend is stateless; client sends last N turns
- Alternatives: keep a server DB as backup.
- Why: sessions are stored in the user's browser; removes SQLite and all server-side session state.

## D6 — Abuse control: per-IP rate limit + message size/history caps, no accounts
- Alternatives: anonymous client ID, real auth.
- Why: no user store (conflicts with D5).

## D7 — Evals: own lightweight pytest harness
- Alternatives: Ragas/DeepEval, retrieval-only.
- Why: avoids heavy dependencies; dev/CI only.

## D8 — Guardrails: all four selected
- Input (length, injection, off-topic), output (parameter + URL validation), grounding (refuse on weak retrieval), safety disclaimer for flight-critical topics.

## D9 — Embedding model: BAAI/bge-small-en-v1.5
- Alternatives: all-MiniLM-L6-v2 (ONNX), build both.
- Why: user choice; better retrieval quality. Query side must use the same model (with fastembed `query_embed`, which adds bge's query prefix).

## D10 — Index lives in the repo under `data/`; the user commits it
- Alternatives: git-ignored and built at deploy, external storage.
- Why: no crawling on Railway's build; simplest deploy. `data/cache/` (raw HTML) is git-ignored.

## D11 — Crawl source: reuse `app/links/links_result_deduped.json`
- Alternative: re-crawl. Builder reports dead/non-doc URLs in `data/build_report.json` instead of silently dropping them.

## D12 — Builder is a plain script: `scripts/build_index.py`

## D13 — Index file format (my call, implementation detail — say if you disagree)
- `chunks.jsonl` + `embeddings.npy` (float32, L2-normalised, so cosine = dot product) + `params.json`. Search at runtime is one numpy matrix multiply; no vector DB library needed.

## D14 — `parameters.html` is NOT chunked into the doc index (my call — say if you disagree)
- It is 6MB and would swamp the index with thousands of param chunks. Only `{name, description}` pairs go into `params.json` for the parameter allow-list. Revisit with evals: if questions about parameter ranges/values retrieve badly, we may add the descriptions as retrievable chunks.

## D15 — LLM client: `groq` SDK directly (async), no LangChain at runtime
- Alternative: LangChain. Why: one retrieve → prompt → stream call needs no framework; smaller image and RAM.

## D16 — Model is an env var `GROQ_MODEL`, default `qwen/qwen3-32b`
- Lets us compare models in the evals without code changes.

## D17 — Follow-up retrieval: embed the previous user turns + current message
- Alternatives: LLM rewrite (extra call), current message only. No LLM keyword step any more.

## D18 — Client IP for rate limiting: first hop of `X-Forwarded-For` (Phase 3)

## D19 — Parameter allow-list is lexical, not a second vector search (my call — say if you disagree)
- Allowed params for a request = names in `params.json` that appear in the retrieved chunks or in the user's question. Deterministic, no extra embeddings/RAM, and it is the same check Phase 3 uses to validate the answer.
- Trade-off: a vague question ("params related to motor movement") only surfaces params that the retrieved chunks mention. Alternative is precomputing param embeddings in the builder.

## D20 — Old runtime code is removed from the working tree (`app/api`, `app/db`, `app/core`, Streamlit frontend kept until Phase 4)
- Everything is still in git history; nothing is committed by me.

## D21 — Index exclusions and cap (after first build produced 86k chunks)
- First build found 86,117 chunks / 73.9M chars: ~72 per-version `parameters-Copter-*.html` dumps and `binary-features.html` (3.5M chars) dominate (top 50 pages = 75% of text; median page 3.4k chars).
- Decided (user): exclude `parameters-Copter-*` pages and `binary-features.html`; cap every page at 40 chunks, capped pages logged in `build_report.json`.
- Current-version parameters still come from `parameters.html` → `params.json`.
- Consequence: questions about parameters of older firmware versions are not answerable.

## D22 — Output validation: stream first, then a final `replace` event if anything was invalid
- Alternatives: buffer whole answer, warning only. Users briefly see unvalidated text; the UI swaps in the corrected text.

## D23 — Off-topic / weak retrieval: score threshold only, no LLM classifier
- Provisional threshold 0.65 on the best chunk's cosine score (off-topic sample ~0.59, on-topic 0.70–0.83). To be tuned in Phase 5 evals. Known risk: short queries ("geofence", best 0.66–0.70) sit near the line.

## D24 — Prompt injection: regex pattern check on user turns + prompt hardening
- Docs wrapped in `<docs>` delimiters and declared untrusted. Not a complete defence.

## D25 — Rate limit: 10 requests/minute and 100/day per IP, in-process (resets on restart; per instance)

## D26 — Client IP: `X-Real-IP`, fall back to socket IP (REVISES D18)
- D18 (first hop of X-Forwarded-For) was spoofable by design. Railway docs only document `X-Real-IP`, and do not say whether a client-sent value is overwritten. TODO after first deploy: send a fake `X-Real-IP` and confirm the app sees Railway's value; if not, switch.

## D27 — Safety disclaimer topics (user): arming/pre-arm, failsafe/RTL, PID/tuning/autotune, motor/ESC/propeller tests, "anything that might lead to a crash"
- Keyword heuristic (my interpretation of the last item: crash, flyaway, flip, takeoff, disable/bypass/override safety). It cannot understand intent; it is tunable in `app/guardrails.py`. Sent as a separate `disclaimer` event, not mixed into the answer text.

## D28 — Parameter validation rule (my call — say if you disagree)
- A parameter-looking token (UPPER_CASE with an underscore) in the answer is valid only if it appears in the retrieved chunks, the question, or the history. A real parameter the model recalled from memory but that wasn't retrieved is therefore also replaced. Matches the "use no others" prompt rule. Links are valid only if they are among the retrieved source URLs.

## D29 — History is trimmed server-side to the newest turns fitting 8,000 characters (my call)
- The 10 turns × 4,000 chars the schema allowed could send ~10k tokens per request to the free Groq quota.

## D30 — Default model is `openai/gpt-oss-20b` (REVISES D16's default)
- `qwen/qwen3-32b` returned 404 model_not_found on the user's Groq key. Available text models: gpt-oss-20b/120b, gpt-oss-safeguard-20b, qwen/qwen3.8-27b. User chose gpt-oss-20b. Still overridable with `GROQ_MODEL`.

## D31 — Frontend location/stack (user): new `web/` folder, TypeScript + Tailwind, Streamlit kept until the user says remove
## D32 — Browser storage (user): localStorage, one key per session (`arduchat:session:<id>`)
## D33 — UI features (user): sessions (new/switch/rename/delete) and export/import JSON. NOT included (not selected): stop-generating button, dark theme.
## D34 — Markdown rendering (my call): `react-markdown` + `remark-gfm` (answers contain tables) + `rehype-sanitize`; links open in a new tab with `rel="noopener noreferrer"`; only http(s) source URLs are rendered as links (imported JSON is untrusted).
## D35 — Import merges by id and skips chats that already exist (my call), so an import can never overwrite local chats.
## D36 — Client history rules (my call): refused/error messages are not sent back as history; each turn is cut to 4,000 chars and at most 10 turns, matching server limits (otherwise a long previous answer would make the server return 422).
## D37 — The SPA calls relative `/chat` (same origin, served by FastAPI from `web/dist`); Vite dev server proxies `/chat` and `/health` to :8000. No CORS, no configurable API URL. If the SPA is hosted separately later, both must be added.

## D38 — Evals (user): ~50-case golden set drafted by Claude, reviewed by the user; judge = `openai/gpt-oss-120b`; local pytest in two tiers; measure first, then compare index variants
- Fast tier (`pytest evals`, no Groq): label check, retrieval metrics, guardrails, validator, rate limiter. Slow tier (`pytest evals -m slow -s`): real answers via `/chat` + LLM judge.
## D39 — Eval design calls (mine)
- Labels are checked against the indexed text (`test_golden_labels.py`) so the golden set can't drift from the docs. This caught one wrong label (I wrote `ARMING_CHECK`; the docs say `ARMING_SKIPCHK`).
- Slow tier goes through the real `/chat` endpoint with a unique `X-Real-IP` per case, so the production path is tested and the per-IP limiter doesn't interfere.
- Metrics: hit@5 (chunks the model sees), page-level MRR, answerable/refused rates at the threshold, keyword coverage, source match, validator-fired rate, judge faithfulness/relevance (1-5). Floors in the tests are set from measured baselines, not guessed.
- `injection_hard` cases (obfuscated attempts the regexes can't catch) are checked for prompt leakage in the answer, not for blocking.
- `scripts/build_index.py` gained `--out DIR` and `--prepend-title` to build comparison indexes; `DATA_DIR` selects the index at eval/run time.

## D40 — Prompt-leak fix (user): deterministic output check
- `leaks_prompt()` in `app/guardrails.py` looks for fixed fragments of SYSTEM_PROMPT in the finished answer; if found the server sends `refused: blocked` + `replace` with the blocked refusal. Fragments must be kept in sync with `SYSTEM_PROMPT` in `app/chat.py`.
## D41 — Retrieval fix (user): hybrid search, dense + BM25 fused with reciprocal rank fusion
- `app/index.py`: BM25 (k1=1.5, b=0.75, tiny stopword list, title+text) over the same 4,226 chunks, no new dependency; pool 50 per ranking, RRF k=60, top 5. Each chunk keeps its dense cosine `score`; the grounding check now uses the BEST dense score among the returned chunks (a keyword-only hit can't lower or raise it by itself).
- Measured effect: geofence went from not found to rank 4; hit@5 0.97 → 1.00; page MRR 0.97 → 0.91 (several pages dropped 1st → 2nd, dshot 1st → 5th). Accepted trade-off.
## D42 — Index (user): title-prepended index is now `data/`; the old bare index was overwritten (reproducible: cache kept in `data/cache`). `scripts/build_index.py` always prepends the title to the embedded text (stored chunk text stays bare); the `--prepend-title` flag was removed. `--out DIR` remains.
## D43 — Grounding threshold (user): keep 0.65

## D44 — Cleanup (user, all four groups approved)
- Deleted: `app/api`, `app/db`, `app/core`, `frontend/` (Streamlit), `pocs/` and `agent/` (incl. the crawler notebook, the only record of how the link list was made; it is in git history), root `links_result_deduped.json`, `requirements.txt`. Kept: `app/links/links_result_deduped.json` (read by the index builder).
## D45 — Packaging (user): `pyproject.toml` + `uv.lock` only. Runtime deps: fastapi, uvicorn, groq, fastembed, numpy, python-dotenv. Groups: `build` (beautifulsoup4, requests, langchain-text-splitters), `dev` (pytest, httpx). Run `uv sync --group build --group dev` for scripts/evals. Venv shrank to 185 MB (torch, transformers, streamlit, scikit-learn etc. gone).
## D46 — Deploy (user): multi-stage `Dockerfile` (Node builds `web/`, python:3.12-slim runs ONE uvicorn worker, non-root, model baked into the image, `data/cache` excluded) + `railway.json` (healthcheck `/health`) — railway.json is my addition. `HF_TOKEN` is no longer needed.
## D47 — Load test (user): `loadtest/fake_groq.py` (fake streaming Groq via `GROQ_BASE_URL`) + `loadtest/run.py` (asyncio/httpx), plus a 5-request real-Groq smoke test. For the fake-Groq run set `GROQ_TOKENS_PER_MINUTE` very high, otherwise the app-wide budget (D49) rejects most requests by design.
## D48 — `reasoning_effort="low"` on the Groq call (user; env `GROQ_REASONING_EFFORT`, empty = model default)
- Measured on the geofence question: default ~3,430 tokens/chat (2,048 completion, mostly hidden reasoning), low ~1,900, medium ~2,400. Only gpt-oss models accept this parameter; set `GROQ_REASONING_EFFORT=` (empty) if switching to another model.
## D49 — App-wide token budget (user): `token_budget_wait()` reserves an estimated cost (chars/4 + 600) against `GROQ_TOKENS_PER_MINUTE` (default 8000, Groq free tier, per model, shared by all users); when exceeded the endpoint answers 503 + `Retry-After` immediately and the UI shows "Try again in Ns". Per-process (single worker/instance only). No queue.

## D50 — Corrected capacity facts and responses (user)
- Groq free tier = 8,000 tokens/min AND 200,000 tokens/day AND 1,000 requests/day, per model, shared by every user. ~100 chats/day at ~1,900 tokens each. The upgrade to the paid Dev tier is the real fix for many users (user may do this; then raise `GROQ_TOKENS_PER_MINUTE` / `GROQ_TOKENS_PER_DAY`).
- Done: Groq's own `retry-after` is passed through (503 + Retry-After, UI shows "about N minutes/hours"); app-wide daily budget `GROQ_TOKENS_PER_DAY` (default 200000) next to the per-minute one.
## D51 — Fewer tokens per chat (user, after seeing the numbers): `TOP_K` 5 → 3 and `GROQ_MAX_COMPLETION_TOKENS` = 1000 (+ a visible "answer was cut short" note when it hits the cap)
- Cost of k=3 measured locally: hit@k 1.00 → 0.95; geofence (the case fixed by hybrid search) and dshot lose their right page again. Eval floor lowered to 0.94 on purpose. Saves ~450 prompt tokens/chat.
## D52 — Smaller slow-eval run (user): `EVAL_SUBSET=1 pytest evals -m slow -s` runs 15 cases; to be run once the daily quota has reset.

## Ground rules (from user)
1. Do not commit.
2. Do not assume; always ask.
3. No unnecessary abstraction.
4. Log steps in steps.md, decisions in decision.md, flows in flow.md.

## D53 — Split deployment (user): backend as a manually created Render Web Service (Docker, Starter+ for memory), frontend on Vercel (root `web`). Backend gets opt-in CORS (`CORS_ORIGINS`, exposes `Retry-After`), frontend reads `VITE_API_URL` at build time, and the Dockerfile is API-only. Client IP header is configurable (`CLIENT_IP_HEADER`); Render's `true-client-ip` is unverified.

## Open (not yet decided)
- LLM model (keep Groq qwen/qwen3-32b?)
- Railway plan limits (RAM/storage)
- Index in git vs built at deploy
- Frontend hosting (served by FastAPI vs separate)
- Language/scope (English, Copter-only)
