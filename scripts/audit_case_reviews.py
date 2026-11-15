"""Review all distinct capabilities reachable from actual confirmed interviews."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx


async def run(args):
    rows = json.loads(
        await asyncio.to_thread(Path(args.input).read_text, encoding="utf-8")
    )["cases"]
    choices = []
    for row in rows:
        for form in row.get("forms", []):
            capabilities = {
                f["capability_key"]
                for o in (form["response"].get("next_step") or {}).get("options", [])
                for f in o["facilities"]
            }
            if capabilities:
                choices.append(
                    (
                        row["case_id"],
                        row["material"],
                        form["form"],
                        capabilities,
                        form.get("material_detail"),
                    )
                )
    remaining = set().union(*(c[3] for c in choices))
    selected = []
    while remaining:
        choice = max(choices, key=lambda c: len(c[3] & remaining))
        selected.append(choice)
        remaining -= choice[3]
    if args.all_forms:
        selected = choices
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(args.concurrency)
    results = (
        json.loads(
            await asyncio.to_thread(Path(args.resume).read_text, encoding="utf-8")
        )["results"]
        if args.resume
        else []
    )
    write_lock = asyncio.Lock()
    refresh_lock = asyncio.Lock()
    completed = {
        (r["case_id"], r["form"], r.get("material_detail"))
        for r in results
        if r.get("keys_match") and "model_unavailable" not in r.get("statuses", {})
    }
    selected = [c for c in selected if (c[0], c[2], c[4]) not in completed]
    async with httpx.AsyncClient(base_url=args.base, timeout=300) as client:
        (
            await client.post(
                "/api/v1/auth/dev-login", json={"email": "dev@example.com"}
            )
        ).raise_for_status()

        async def review(choice):
            case_id, material, form, expected, material_detail = choice
            async with semaphore:
                row = {
                    "case_id": case_id,
                    "material": material,
                    "form": form,
                    "material_detail": material_detail,
                    "expected_keys": sorted(expected),
                }
                try:
                    path = f"/api/v1/diagnosis/cases/{case_id}/treatment/intake-reviews"
                    body = {
                        "input_form": form,
                        "solid_confirmed": True,
                        "material_detail": material_detail,
                    }
                    response = await client.post(
                        path,
                        json=body,
                    )
                    if response.status_code == 401:
                        # Long synthetic runs must refresh just as the web does.
                        # Retry an explicit auth rejection only, never a timeout.
                        async with refresh_lock:
                            refreshed = await client.post("/api/v1/auth/refresh")
                            refreshed.raise_for_status()
                        response = await client.post(path, json=body)
                    row["http_status"] = response.status_code
                    response.raise_for_status()
                    data = response.json()
                    actual = (data.get("reviews") or {}).get("results", {})
                    recycling = data.get("recycling") or {}
                    route_input = data.get("route_input") or {}
                    row["recycling_transferred"] = (
                        recycling.get("status") == "table_listed"
                        and recycling.get("case_id") == case_id
                        and route_input.get("recycling_types") == recycling.get("types")
                        and (route_input.get("recycling_basis") or {}).get("source_url")
                        == (recycling.get("source") or {}).get("url")
                    )
                    row.update(
                        response=data,
                        keys_match=set(actual) == expected,
                        statuses=dict(Counter(r["status"] for r in actual.values())),
                        dispatch_not_approved=all(
                            r["dispatch_approved"] is False for r in actual.values()
                        ),
                    )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                    row["error"] = str(error)
                async with write_lock:
                    results[:] = [
                        r
                        for r in results
                        if (r["case_id"], r["form"], r.get("material_detail"))
                        != (case_id, form, material_detail)
                    ]
                    results.append(row)
                    await asyncio.to_thread(
                        output.write_text,
                        json.dumps({"results": results}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                print(
                    material,
                    form,
                    row.get("keys_match"),
                    row.get("statuses", row.get("error")),
                    flush=True,
                )
                if args.delay:
                    await asyncio.sleep(args.delay)

        await asyncio.gather(*(review(c) for c in selected))
    return int(
        any(
            r.get("error")
            or not r.get("recycling_transferred")
            or not r.get("keys_match")
            or r.get("statuses", {}).get("model_unavailable", 0)
            for r in results
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help="Seconds between synthetic audit requests",
    )
    parser.add_argument("--base", default="http://localhost:5178")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--all-forms", action="store_true")
    parser.add_argument("--resume")
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 2:
        parser.error("--concurrency must be 1 or 2")
    raise SystemExit(asyncio.run(run(args)))
