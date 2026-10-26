"""Stand-in for the Groq API so load tests don't spend quota. Streams an OpenAI-style chat completion.

    python loadtest/fake_groq.py            # listens on :9000
    GROQ_BASE_URL=http://localhost:9000 uvicorn app.main:app

TOKENS and SECONDS set how long one streamed answer takes (defaults mimic a ~300 token answer over ~4 s).
"""
import asyncio
import json
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

TOKENS = int(os.getenv("FAKE_TOKENS", "300"))
SECONDS = float(os.getenv("FAKE_SECONDS", "4"))

app = FastAPI()


def chunk(content=None, finish=None):
    delta = {"content": content} if content is not None else {}
    return "data: " + json.dumps({
        "id": "fake", "object": "chat.completion.chunk", "created": 0, "model": "fake",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }) + "\n\n"


@app.post("/openai/v1/chat/completions")
async def completions():
    async def stream():
        yield chunk("")
        for i in range(TOKENS):
            await asyncio.sleep(SECONDS / TOKENS)
            yield chunk(f"word{i} ")
        yield chunk(finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="warning")
