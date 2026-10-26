import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "30"))
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "2"))

# gpt-oss models accept low|medium|high (low cuts a chat from ~3.4k to ~1.9k tokens); empty = model default.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")
# Groq's free tier allows 8,000 tokens/minute per model, shared by every user of the app.
# Hidden reasoning counts toward this; typical answers use ~500 with reasoning_effort=low.
GROQ_MAX_COMPLETION_TOKENS = int(os.getenv("GROQ_MAX_COMPLETION_TOKENS", "1000"))
GROQ_TOKENS_PER_MINUTE = int(os.getenv("GROQ_TOKENS_PER_MINUTE", "8000"))
# ...and 200,000 tokens/day. Raise both (env vars) after upgrading the Groq plan.
GROQ_TOKENS_PER_DAY = int(os.getenv("GROQ_TOKENS_PER_DAY", "200000"))

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # must match scripts/build_index.py
DATA_DIR = os.getenv("DATA_DIR", "data")

# Header the platform proxy uses to pass the real client IP (Railway: x-real-ip; Render: true-client-ip).
CLIENT_IP_HEADER = os.getenv("CLIENT_IP_HEADER", "x-real-ip").lower()

# 3 chunks save ~450 tokens/chat vs 5, at the cost of hit@k 1.00 -> 0.95 (geofence, dshot lose their page). User's call.
TOP_K = 3
HISTORY_TURNS_IN_QUERY = 2  # previous user messages folded into the retrieval query
