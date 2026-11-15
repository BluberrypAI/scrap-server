"""Explicit live Azure review of every reachable capability (synthetic request inputs)."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx


async def run(args):
    audit = json.loads(await asyncio.to_thread(Path(args.catalog).read_text, encoding="utf8"))
    missing = {c["key"] for c in audit["capabilities"] if c["reachable"]}
    picked = []
    while missing:
        row = max(audit["queries"], key=lambda q: len(missing & set(q["capabilities"])))
        picked.append(row)
        missing -= set(row["capabilities"])
    results = []
    semaphore = asyncio.Semaphore(2)
    write_lock = asyncio.Lock()
    async with httpx.AsyncClient(base_url=args.base, timeout=300) as client:
        (
            await client.post("/api/v1/auth/dev-login", json={"email": "audit-model@example.com"})
        ).raise_for_status()

        async def review(row):
            async with semaphore:
                payload = {k: v for k, v in row["request"].items() if k != "origin"}
                response = await client.post("/api/treatment/intake-reviews", json=payload)
                response.raise_for_status()
                value = response.json()
                expected = set(row["capabilities"])
                actual = set(value["results"])
                assert actual == expected, (expected - actual, actual - expected)
                assert all(not r["dispatch_approved"] for r in value["results"].values())
                async with write_lock:
                    results.append({"request": payload, **value})
                    await asyncio.to_thread(
                        Path(args.output).write_text,
                        json.dumps({"requests": results}, ensure_ascii=False, indent=2),
                        encoding="utf8",
                    )
                print(
                    payload["material"],
                    payload["input_form"],
                    len(actual),
                    dict(Counter(r["status"] for r in value["results"].values())),
                    flush=True,
                )

        await asyncio.gather(*(review(r) for r in picked))
    combined = {k: v for r in results for k, v in r["results"].items()}
    print(
        "UNIQUE", len(combined), dict(Counter(r["status"] for r in combined.values())), flush=True
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--catalog", required=True)
    p.add_argument("--output", required=True)
    asyncio.run(run(p.parse_args()))
