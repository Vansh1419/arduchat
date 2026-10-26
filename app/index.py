"""Read-only docs index built by scripts/build_index.py, loaded once at startup."""
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

from app.config import DATA_DIR, EMBEDDING_MODEL, TOP_K

PARAM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
TOKEN = re.compile(r"[a-z0-9_]+")
STOPWORDS = {"the", "a", "an", "of", "to", "in", "is", "are", "do", "does", "how", "what", "i", "my", "and", "or", "for", "on", "it", "its", "with", "can", "which"}
POOL = 50  # candidates taken from each ranking before fusion
RRF_K = 60
BM25_K1, BM25_B = 1.5, 0.75

embedder: TextEmbedding
embeddings: np.ndarray
chunks: list[dict]
param_names: set[str]
postings: dict[str, list[tuple[int, int]]]  # term -> [(chunk, term frequency)]
chunk_lengths: list[int]
average_length: float


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


def load():
    global embedder, embeddings, chunks, param_names, postings, chunk_lengths, average_length
    data = Path(DATA_DIR)
    embeddings = np.load(data / "embeddings.npy")
    chunks = [json.loads(line) for line in (data / "chunks.jsonl").read_text().splitlines()]
    param_names = {p["name"] for p in json.loads((data / "params.json").read_text())}
    embedder = TextEmbedding(EMBEDDING_MODEL)

    postings = {}
    chunk_lengths = []
    for i, c in enumerate(chunks):
        terms = tokens(c["title"] + " " + c["text"])
        chunk_lengths.append(len(terms))
        for term, freq in Counter(terms).items():
            postings.setdefault(term, []).append((i, freq))
    average_length = sum(chunk_lengths) / len(chunk_lengths)


def bm25_scores(query: str) -> dict[int, float]:
    scores: dict[int, float] = {}
    for term in set(tokens(query)):
        hits = postings.get(term, [])
        idf = math.log(1 + (len(chunks) - len(hits) + 0.5) / (len(hits) + 0.5))
        for i, freq in hits:
            norm = freq + BM25_K1 * (1 - BM25_B + BM25_B * chunk_lengths[i] / average_length)
            scores[i] = scores.get(i, 0.0) + idf * freq * (BM25_K1 + 1) / norm
    return scores


def search(query: str) -> list[dict]:
    """Top-k chunks, best first. Dense (embedding) and keyword (BM25) rankings are fused with
    reciprocal rank fusion; each chunk carries its dense cosine `score`, which the grounding check uses."""
    vector = next(iter(embedder.query_embed(query)))
    vector = vector / np.linalg.norm(vector)
    dense = embeddings @ vector

    dense_ranking = np.argsort(dense)[::-1][:POOL]
    keyword = bm25_scores(query)
    keyword_ranking = sorted(keyword, key=keyword.get, reverse=True)[:POOL]

    fused: dict[int, float] = {}
    for ranking in (dense_ranking, keyword_ranking):
        for rank, i in enumerate(ranking):
            fused[int(i)] = fused.get(int(i), 0.0) + 1 / (RRF_K + rank + 1)
    top = sorted(fused, key=fused.get, reverse=True)[:TOP_K]
    return [{**chunks[i], "score": float(dense[i])} for i in top]


def params_in(*texts: str) -> list[str]:
    """Real ArduPilot parameter names mentioned in the given texts."""
    found = set()
    for text in texts:
        found.update(PARAM_PATTERN.findall(text))
    return sorted(found & param_names)
