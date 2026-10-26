"""Retrieval quality of the docs index (no Groq). Run with -s to see the report."""
import json
import os
from pathlib import Path

import pytest

from app.chat import ChatRequest
from app.chat import retrieval_query
from app.config import TOP_K
from conftest import cases

# Floors measured on the baseline index (see steps.md); a drop below these is a regression.
MIN_HIT_AT_K = 0.94  # TOP_K=3 (user's choice): 37/39 = 0.949; geofence and dshot miss
MIN_MRR = 0.90
WINDOW = 50  # chunks examined when computing MRR


def page(url):
    return url.rsplit("/", 1)[-1]


def rank_of_expected(index, case):
    """1-based rank of the first expected page among pages ordered by best chunk, or None."""
    req = ChatRequest(message=case["question"], history=case.get("history", []))
    index.TOP_K = WINDOW
    try:
        found = index.search(retrieval_query(req))
    finally:
        index.TOP_K = TOP_K
    pages = list(dict.fromkeys(page(c["url"]) for c in found))
    ranks = [pages.index(u) + 1 for u in case["expected_urls"] if u in pages]
    in_top_chunks = any(page(c["url"]) in case["expected_urls"] for c in found[:TOP_K])
    return (min(ranks) if ranks else None), in_top_chunks, max(c["score"] for c in found)


def test_retrieval_metrics(index):
    rows = [(c, *rank_of_expected(index, c)) for c in cases("in_scope", "follow_up")]
    hit = sum(1 for _, _, in_top, _ in rows if in_top) / len(rows)
    mrr = sum(1 / r for _, r, _, _ in rows if r) / len(rows)

    print(f"\n[{os.getenv('DATA_DIR', 'data')}] cases={len(rows)}  hit@{TOP_K} chunks={hit:.2f}  MRR(pages)={mrr:.2f}")
    for c, r, in_top, score in rows:
        if not in_top:
            print(f"  MISS {c['id']:20} page-rank={r}  top-score={score:.3f}  q={c['question']!r}")

    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    name = f"retrieval-{Path(os.getenv('DATA_DIR', 'data')).name}.json"
    (out / name).write_text(json.dumps({
        "hit_at_k": hit, "mrr": mrr,
        "cases": [{"id": c["id"], "page_rank": r, "in_top_chunks": t, "top_score": s} for c, r, t, s in rows],
    }, indent=2))

    assert hit >= MIN_HIT_AT_K, f"hit@{TOP_K} {hit:.2f} < {MIN_HIT_AT_K}"
    assert mrr >= MIN_MRR, f"MRR {mrr:.2f} < {MIN_MRR}"
