# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ArduChat: a RAG chat assistant for the ArduPilot Copter docs (https://ardupilot.org/copter/docs/). A stateless FastAPI backend (`app/`) streams answers over SSE and also serves the built React SPA (`web/`). Chat history lives only in the browser (localStorage); the server stores nothing. See `README.md` for the full write-up, `decision.md` for the reasoning behind choices (D1…), and `steps.md` for the work log.

## Commands

Python 3.12+, `uv`, Node 24 (UI only). Copy `.env.example` to `.env` and set `GROQ_API_KEY`.

```bash
uv sync                                   # runtime deps
(cd web && npm ci && npm run build)       # build SPA into web/dist (served by FastAPI at /)
uv run uvicorn app.main:app --port 8000   # run app
(cd web && npm run dev)                   # UI dev; Vite proxies /chat and /health to :8000

uv sync --group dev --group build
uv run pytest evals                       # fast tier, no Groq calls
uv run pytest evals/test_retrieval.py -k geofence   # single test
uv run pytest evals -m slow -s            # real answers + LLM judge; spends Groq quota (run ≤1–2×/day)
EVAL_SUBSET=1 uv run pytest evals -m slow -s        # 15-case subset

uv sync --group build && python scripts/build_index.py   # rebuild index (only when docs change); --out DIR for a comparison index (use DATA_DIR=DIR to evaluate)
python loadtest/fake_groq.py &            # fake Groq on :9000; then run app with GROQ_BASE_URL=http://localhost:9000 and large GROQ_TOKENS_PER_MINUTE/DAY, then loadtest/run.py
```

## Architecture

Request path in `app/main.py` (`POST /chat`), order matters: per-IP rate limit → trim history → injection regex check → hybrid retrieve → grounding gate (best dense score < 0.65 refuses without calling the LLM) → app-wide Groq token budget (503 + Retry-After) → Groq stream → output validation.

- `app/index.py`: loads the shipped read-only index from `data/` (`chunks.jsonl`, `embeddings.npy` L2-normalised so cosine = dot product, `params.json` allow-list of parameter names). Dense (fastembed `BAAI/bge-small-en-v1.5`, use `query_embed`) + BM25, fused by RRF. No vector DB.
- `app/chat.py`: request schema, system prompt (docs wrapped in `<docs>` and declared untrusted), Groq call, SSE event generation. Events: `sources`, `token`, `replace`, `disclaimer`, `refused`, `error`, `done`.
- `app/guardrails.py`: rate limiter, token budgets, injection patterns, grounding, output validator (replaces parameter-like tokens and links not present in retrieved context; `replace` event swaps the streamed text), safety-disclaimer keywords, canned refusals.
- `app/config.py`: env-driven settings (`GROQ_MODEL` default `openai/gpt-oss-20b`, token budgets, `DATA_DIR`, etc.).
- `scripts/build_index.py`: offline builder (fetch with `data/cache/` → clean → chunk → embed). Reads `app/links/links_result_deduped.json`. Skips `parameters-Copter-*` and `binary-features.html`, caps 40 chunks/page, and does not chunk `parameters.html` (only name/description pairs go to `params.json`). Failures reported in `data/build_report.json`. `data/` is committed; `data/cache/` is git-ignored.
- `evals/`: lightweight pytest harness over `golden.json` (55 cases); slow tier is excluded by default via `pytest.ini`.

## Constraints to respect

- Run exactly **one uvicorn worker / one instance**: rate limiter and token budgets are in-process memory. No server-side sessions or DB.
- No LangChain/torch/Chroma at runtime (image must fit the small Railway tier); runtime deps are the `[project] dependencies` only, other tooling is in `build`/`dev` dependency groups.
- Client IP uses the `CLIENT_IP_HEADER` header (default `x-real-ip`; `true-client-ip` on Render) with socket fallback (`client_ip` in `guardrails.py`); spoofability on each platform is still to be verified.
- No CORS middleware: SPA and API share an origin.
- Deploy: `Dockerfile` (stage 1 builds the web app, stage 2 bakes the embedding model into the image) + `railway.json` / `render.yaml` / the README header for Hugging Face Spaces (`/health` healthcheck). Only `data/chunks.jsonl`, `embeddings.npy`, `params.json` are copied into the image.
- `README.md` is the current write-up and carries the Hugging Face Spaces YAML header (`sdk: docker`, `app_port: 8000`); keep that header when editing.
