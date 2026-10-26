# Stage 1: build the React app
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: runtime (one uvicorn worker; the embedding model and index live in this process)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/app/.fastembed \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the embedding model into the image so startup needs no network access
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY app ./app
COPY data/chunks.jsonl data/embeddings.npy data/params.json ./data/
COPY --from=web /web/dist ./web/dist

RUN useradd --system --no-create-home app && chown -R app /app
USER app

EXPOSE 8000
# Railway sets $PORT; GROQ_API_KEY (and optionally GROQ_MODEL) come from its environment variables
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
