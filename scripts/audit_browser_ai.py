"""Click one saved synthetic interview's AI review button through the real web UI.

Uses an installed Edge and explicit localhost dev login. No mocked API or model.
The output contains counters only, without case IDs, tokens, or model text.
"""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect


async def run(args):
    if urlsplit(args.base).hostname != "localhost":
        raise ValueError("Synthetic dev login only targets localhost")
    cases = json.loads(Path(args.input).read_text(encoding="utf8"))["cases"]
    case = next(c for c in cases if c["material"] == args.material)
    form = next(f for f in case["forms"] if f["form"] == args.form)
    expected = {
        f["capability_key"]
        for option in form["response"]["next_step"]["options"]
        for f in option["facilities"]
    }
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="msedge",
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000}
            )
            login = await context.request.post(
                f"{args.base}/api/v1/auth/dev-login", data={"email": "dev@example.com"}
            )
            assert login.ok, "Dev login unavailable"
            page = await context.new_page()
            await page.goto(f"{args.base}/#/wastes/case-{case['case_id']}")
            await expect(page.locator(".wf-panel")).to_be_visible()
            solid = page.locator('.wf-panel input[type="checkbox"]')
            if await solid.count() and not await solid.is_checked():
                await solid.check()
            choice = page.locator(f'input[name="input-form"][value="{args.form}"]')
            await expect(choice).to_be_visible()
            await choice.check()
            await expect(page.locator(".wf-facility")).to_have_count(len(expected))
            rtypes = page.get_by_test_id("recycling-types")
            await expect(rtypes).to_be_visible()
            await rtypes.locator("summary").click()
            await expect(rtypes).to_contain_text("R-10")
            async with page.expect_response(
                lambda r: (
                    "/treatment/intake-reviews" in r.url and r.request.method == "POST"
                ),
                timeout=300000,
            ) as pending:
                await page.get_by_role("button", name="업체 공개 근거 AI 검토").click()
            response = await pending.value
            assert response.ok, "AI review HTTP request failed"
            data = await response.json()
            reviews = data["reviews"]["results"]
            assert set(reviews) == expected
            assert all(not r["dispatch_approved"] for r in reviews.values())
            assert data["route_input"]["recycling_types"] == data["recycling"]["types"]
            statuses = Counter(r["status"] for r in reviews.values())
            await expect(page.locator(".wf-review")).to_have_count(len(expected))
            for status, count in statuses.items():
                await expect(
                    page.locator(f'.wf-review[data-status="{status}"]')
                ).to_have_count(count)
            await expect(
                page.get_by_role("button", name="업체 근거 다시 검토")
            ).to_be_enabled()
            result = {
                "material": args.material,
                "form": args.form,
                "candidates": len(expected),
                "rendered_reviews": len(expected),
                "statuses": dict(statuses),
                "r_types_preserved": True,
                "dispatch_approved": False,
                "button_clicked": True,
                "passed": "model_unavailable" not in statuses,
            }
            Path(args.output).write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return int(not result["passed"])
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5178")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--material", default="pe")
    parser.add_argument("--form", default="film")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
