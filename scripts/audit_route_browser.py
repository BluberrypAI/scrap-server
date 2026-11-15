"""Click saved synthetic interviews through the real web UI (no mocked APIs).

Run locally with: uv run --with playwright --project backend python
scripts/audit_route_browser.py --input <audit_diagnosis_routes output> --output <file>
Uses the local-only dev login and installed Microsoft Edge. Never calls AI itself.
"""

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright, expect


async def run(args):
    if urlsplit(args.base).hostname != "localhost":
        raise ValueError("This synthetic dev-login audit only targets localhost")
    cases = json.loads(Path(args.input).read_text(encoding="utf-8"))["cases"]
    results = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="msedge",
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        response = await context.request.post(
            f"{args.base}/api/v1/auth/dev-login", data={"email": "dev@example.com"}
        )
        assert response.ok, "Dev login unavailable"
        page = await context.new_page()
        for case in cases:
            for form in case.get("forms") or [None]:
                row = {
                    "material": case["material"],
                    "detail": form.get("material_detail") if form else None,
                    "form": form["form"] if form else None,
                }
                try:
                    await page.goto("about:blank")
                    await page.goto(f"{args.base}/#/wastes/case-{case['case_id']}")
                    if not form:
                        await expect(page.locator(".wf-route-outcome")).to_be_visible()
                        assert await page.locator(".wf-facility").count() == 0
                        row.update(passed=True, outcome="explicit_hold")
                    else:
                        await expect(page.locator(".wf-panel")).to_be_visible()
                        # Some interviews omit state; the UI correctly asks for
                        # solid confirmation BEFORE exposing material/form choices.
                        solid = page.locator('.wf-panel input[type="checkbox"]')
                        if await solid.count() and not await solid.is_checked():
                            await solid.check()
                        if row["detail"]:
                            await page.locator(
                                f'input[name="material-detail"][value="{row["detail"]}"]'
                            ).check()
                            # Solid confirmation can appear only AFTER material
                            # detail is known (packaging/net/metal containers).
                            await expect(
                                page.locator(
                                    '.wf-panel input[type="checkbox"], input[name="input-form"]'
                                ).first
                            ).to_be_visible()
                            solid = page.locator('.wf-panel input[type="checkbox"]')
                            if await solid.count() and not await solid.is_checked():
                                await solid.check()
                        choice = page.locator(
                            f'input[name="input-form"][value="{row["form"]}"]'
                        )
                        await expect(choice).to_be_visible()
                        await choice.check()
                        await expect(choice).to_be_checked()
                        solid = page.locator('.wf-panel input[type="checkbox"]')
                        if await solid.count() and not await solid.is_checked():
                            await solid.check()
                        expected = sum(
                            len(option["facilities"])
                            for option in (form["response"].get("next_step") or {}).get(
                                "options", []
                            )
                        )
                        await expect(page.locator(".wf-facility")).to_have_count(
                            expected, timeout=20000
                        )
                        if not expected:
                            await expect(
                                page.locator(".wf-route-outcome")
                            ).to_be_visible()
                        await expect(page.locator("body")).to_contain_text(
                            case["expected_code"]
                        )
                        await expect(choice).to_be_checked()
                        rbox = page.get_by_test_id("recycling-types")
                        await expect(rbox).to_be_visible()
                        await rbox.locator("summary").click()
                        await expect(rbox).to_contain_text("R-10")
                        await expect(rbox.locator("a")).to_have_attribute(
                            "href", form["response"]["recycling"]["source"]["url"]
                        )
                        row.update(
                            passed=True, candidates=expected, recycling_visible=True
                        )
                except (AssertionError, PlaywrightError) as error:
                    # No cookies or input documents are serialized.
                    row.update(
                        passed=False,
                        error_type=type(error).__name__,
                        error=str(error)[:1400],
                    )
                results.append(row)
                Path(args.output).write_text(
                    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(row, flush=True)
        await browser.close()
    return int(any(not row["passed"] for row in results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5178")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
