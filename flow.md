# Flows

## Current (before refactor)
```
Streamlit ─► POST /chat ─► LLM keywords ─► link vector search (Chroma, in-memory)
          ─► scrape new pages ─► chunk ─► main_docs Chroma ─► LLM answer
          ─► SQLite stores messages
Globals: retrieved_links, already_fetched_links (shared across users)
```

## Target (planned)
```
Offline (dev machine):
  link list ─► fetch pages ─► clean HTML ─► chunk ─► fastembed ─► index file
  parameters.html ─► parameter names JSON

Runtime (one Railway service):
  React SPA (localStorage/IndexedDB sessions)
     │  POST /chat {message, history[last N]}   (SSE stream back)
     ▼
  FastAPI
     ├─ input guardrails (length, injection, off-topic) + per-IP rate limit
     ├─ embed query (fastembed) ─► search read-only index
     ├─ grounding check (weak retrieval ─► "not found in docs")
     ├─ Groq LLM
     └─ output guardrails (param names, URLs, safety disclaimer) ─► answer + sources
```
