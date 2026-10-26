"""Offline index builder. Run from the repo root:

    python scripts/build_index.py

Fetches every URL in app/links/links_result_deduped.json, cleans the HTML,
chunks it, embeds the chunks with fastembed and writes the read-only index
the app loads at startup:

    data/chunks.jsonl      one {url, title, text} per chunk (row i <-> embeddings[i])
    data/embeddings.npy    float32, L2-normalised, shape (n_chunks, 384)
    data/params.json       [{name, description}] from parameters.html
    data/build_report.json counts, failed URLs, model name

Raw pages are cached in data/cache/ (git-ignored) so reruns don't refetch.
"""
import argparse
import hashlib
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from bs4 import BeautifulSoup
from fastembed import TextEmbedding
from langchain_text_splitters import RecursiveCharacterTextSplitter

LINKS_PATH = Path("app/links/links_result_deduped.json")
DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "cache"
PARAMETERS_URL = "https://ardupilot.org/copter/docs/parameters.html"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
MAX_CHUNKS_PER_PAGE = 40  # median page is ~4 chunks; this only trims generated outliers
EXCLUDED = re.compile(r"/(parameters-Copter-[^/]+|binary-features)\.html$")  # per-version param dumps, giant table
BATCH = 256
WORKERS = 8
TIMEOUT = 30
RETRIES = 2

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)


def fetch(url):
    """Return (html, error). Cached on disk by URL hash."""
    cache_file = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8"), None
    error = None
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            if "text/html" not in resp.headers.get("content-type", ""):
                return None, f"not html ({resp.headers.get('content-type')})"
            resp.encoding = "utf-8"  # auto-detection produces mojibake on this site
            cache_file.write_text(resp.text, encoding="utf-8")
            return resp.text, None
        except requests.RequestException as e:
            error = f"{type(e).__name__}: {e}"
            time.sleep(1 + attempt)
    return None, error


def clean(html):
    """Return (title, text) of the article body, or (None, None) if there is none."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("div[role=main]")
    if body is None:
        return None, None
    for tag in body.select("script, style, nav, .headerlink"):
        tag.decompose()
    h1 = body.find("h1")
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "")
    text = re.sub(r"\n{3,}", "\n\n", body.get_text("\n", strip=True))
    return title, text


def parse_params(html):
    """parameters.html has one <h3> per parameter, formatted 'NAME: description'."""
    soup = BeautifulSoup(html, "html.parser")
    params = []
    for h3 in soup.find_all("h3"):
        for a in h3.select(".headerlink"):
            a.decompose()
        name, _, description = h3.get_text(strip=True).partition(":")
        if name:
            params.append({"name": name.strip(), "description": description.strip()})
    return params


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data", help="output directory (the raw-page cache stays in data/cache)")
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    urls = json.loads(LINKS_PATH.read_text())

    with ThreadPoolExecutor(WORKERS) as pool:
        fetched = list(pool.map(fetch, urls))

    failed, no_body, excluded, capped, chunks = [], [], [], [], []
    for url, (html, error) in zip(urls, fetched):
        if error:
            failed.append({"url": url, "error": error})
            continue
        if url == PARAMETERS_URL:
            continue  # handled separately below: parameter names, not 6MB of chunks
        if EXCLUDED.search(url):
            excluded.append(url)
            continue
        title, text = clean(html)
        if not text:
            no_body.append(url)
            continue
        pieces = splitter.split_text(text)
        if len(pieces) > MAX_CHUNKS_PER_PAGE:
            capped.append({"url": url, "chunks": len(pieces)})
            pieces = pieces[:MAX_CHUNKS_PER_PAGE]
        for piece in pieces:
            chunks.append({"url": url, "title": title, "text": piece})

    params_html, params_error = fetch(PARAMETERS_URL)
    params = parse_params(params_html) if params_html else []
    if params_error:
        failed.append({"url": PARAMETERS_URL, "error": params_error})

    print(f"embedding {len(chunks)} chunks with {EMBEDDING_MODEL}")
    model = TextEmbedding(EMBEDDING_MODEL)
    texts = [f"{c['title']}\n{c['text']}" for c in chunks]  # title prepended to what is embedded; stored text stays bare
    batches = []
    for start in range(0, len(texts), BATCH):
        batches.append(np.array(list(model.passage_embed(texts[start:start + BATCH], batch_size=BATCH)), dtype=np.float32))
        print(f"  embedded {min(start + BATCH, len(texts))}/{len(texts)}", flush=True)
    vectors = np.concatenate(batches)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    np.save(out_dir / "embeddings.npy", vectors)
    with open(out_dir / "chunks.jsonl", "w") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (out_dir / "params.json").write_text(json.dumps(params, ensure_ascii=False))

    per_page = Counter(c["url"] for c in chunks)
    report = {
        "model": EMBEDDING_MODEL,
        "title_prepended": True,
        "urls_in_list": len(urls),
        "pages_indexed": len(per_page),
        "chunks": len(chunks),
        "params": len(params),
        "failed": failed,
        "no_article_body": no_body,
        "excluded": excluded,
        "capped": capped,
        "largest_pages": per_page.most_common(10),
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ("failed", "no_article_body", "excluded", "capped")}, indent=2))
    print(f"failed: {len(failed)}, no article body: {len(no_body)}, excluded: {len(excluded)}, capped: {len(capped)} (see build_report.json in the output dir)")


if __name__ == "__main__":
    main()
