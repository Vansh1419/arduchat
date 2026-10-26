"""Concurrent chat load against a running ArduChat server.

    python loadtest/run.py --url http://localhost:8000 --users 20 --requests 3 [--pid 1234]

Each virtual user has its own X-Real-IP (so the per-IP rate limiter, tested elsewhere, doesn't interfere)
and sends in-scope questions from evals/golden.json one after another. --pid samples that process's RSS.
"""
import argparse
import asyncio
import json
import statistics
import subprocess
import time
from pathlib import Path

import httpx

GOLDEN = json.loads((Path(__file__).parent.parent / "evals" / "golden.json").read_text())["cases"]
QUESTIONS = [c["question"] for c in GOLDEN if c["category"] == "in_scope"]


def rss_mb(pid: int) -> float:
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)])) / 1024


async def one_request(client, user, n, results):
    question = QUESTIONS[(user * 7 + n) % len(QUESTIONS)]
    start = time.perf_counter()
    first = None
    status = None
    ended = False
    try:
        async with client.stream("POST", "/chat", json={"message": question, "history": []}, headers={"x-real-ip": f"10.9.{user // 250}.{user % 250}"}) as res:
            status = res.status_code
            async for line in res.aiter_lines():
                if first is None and line == "event: token":
                    first = time.perf_counter() - start
                if line == "event: done":
                    ended = True
    except Exception as e:
        status = type(e).__name__
    results.append({"status": status, "ok": status == 200 and ended, "ttft": first, "total": time.perf_counter() - start})


async def user_loop(client, user, requests, results):
    for n in range(requests):
        await one_request(client, user, n, results)


async def sample_rss(pid, peak, stop):
    while not stop.is_set():
        peak[0] = max(peak[0], rss_mb(pid))
        await asyncio.sleep(0.25)


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))] if values else float("nan")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--requests", type=int, default=3)
    ap.add_argument("--pid", type=int)
    args = ap.parse_args()

    results, peak, stop = [], [0.0], asyncio.Event()
    async with httpx.AsyncClient(base_url=args.url, timeout=120) as client:
        sampler = asyncio.create_task(sample_rss(args.pid, peak, stop)) if args.pid else None
        start = time.perf_counter()
        await asyncio.gather(*(user_loop(client, u, args.requests, results) for u in range(args.users)))
        wall = time.perf_counter() - start
        stop.set()
        if sampler:
            await sampler

    ok = [r for r in results if r["ok"]]
    ttft = [r["ttft"] for r in ok if r["ttft"] is not None]
    total = [r["total"] for r in ok]
    codes = {}
    for r in results:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    print(f"users={args.users} requests/user={args.requests} total={len(results)} ok={len(ok)} statuses={codes} wall={wall:.1f}s throughput={len(ok) / wall:.1f} req/s")
    if ok:
        print(f"time to first token: median {statistics.median(ttft):.2f}s  p95 {pct(ttft, .95):.2f}s  max {max(ttft):.2f}s")
        print(f"total per request:   median {statistics.median(total):.2f}s  p95 {pct(total, .95):.2f}s  max {max(total):.2f}s")
    if args.pid:
        print(f"peak RSS during run: {peak[0]:.0f} MB")


asyncio.run(main())
