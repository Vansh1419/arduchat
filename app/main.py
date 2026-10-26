import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import groq
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import index
from app.chat import ChatRequest, answer_events, build_messages, refusal_events, retrieval_query, start_stream
from app.guardrails import client_ip, is_injection, rate_limited, token_budget_wait, trim_history, weak_retrieval


@asynccontextmanager
async def lifespan(app: FastAPI):
    index.load()
    yield


app = FastAPI(title="ArduChat API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "chunks": len(index.chunks)}


def event_stream(events) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def busy(retry_after: int) -> HTTPException:
    detail = "The assistant has reached its usage limit." if retry_after > 300 else "The assistant is busy right now."
    return HTTPException(503, detail, headers={"Retry-After": str(retry_after)})


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    retry_after = rate_limited(client_ip(request))
    if retry_after:
        raise HTTPException(429, "Too many requests, please slow down.", headers={"Retry-After": str(retry_after)})

    req.history = trim_history(req.history)
    if is_injection(req.message, req.history):
        return event_stream(refusal_events("blocked"))

    found = await asyncio.to_thread(index.search, retrieval_query(req))
    if weak_retrieval(found):
        return event_stream(refusal_events("not_found"))

    messages = build_messages(req, found)
    retry_after = token_budget_wait(messages)
    if retry_after:
        raise busy(retry_after)

    try:
        stream = await start_stream(messages)
    except groq.RateLimitError as e:  # Groq's own limit (shared key, other users); it says how long to wait
        raise busy(int(float(e.response.headers.get("retry-after", 30))) + 1)
    except groq.APIError:
        raise HTTPException(502, "The language model is unavailable.")
    return event_stream(answer_events(stream, req, found))


# Built React app (cd web && npm run build). Mounted last so it never shadows the API routes.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
