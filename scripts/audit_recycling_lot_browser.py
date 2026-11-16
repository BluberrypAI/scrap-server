"""Synthetic localhost UI -> persisted lot -> real Azure candidate review.

Uses a confirmed case from audit_diagnosis_routes.py. Creates a local test lot;
does not send offers, issue QR tokens, or substitute model responses.
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
        raise ValueError("Only localhost synthetic testing is supported")
    cases = json.loads(Path(args.input).read_text(encoding="utf-8"))["cases"]
    case = next(c for c in cases if c["material"] == args.material)
    form = case["forms"][0]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            channel="msedge",
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        login = await context.request.post(
            f"{args.base}/api/v1/auth/dev-login", data={"email": "dev@example.com"}
        )
        assert login.ok, "Local dev login unavailable"
        page = await context.new_page()
        await page.goto(f"{args.base}/#/wastes/case-{case['case_id']}")
        await expect(page.locator(".wf-panel")).to_be_visible()
        solid = page.locator('.wf-panel input[type="checkbox"]')
        if await solid.count() and not await solid.is_checked():
            await solid.check()
        if form.get("material_detail"):
            await page.locator(
                f'input[name="material-detail"][value="{form["material_detail"]}"]'
            ).check()
        await page.locator(f'input[name="input-form"][value="{form["form"]}"]').check()
        await expect(page.get_by_test_id("recycling-types")).to_be_visible()
        await page.get_by_label("중량(kg)", exact=True).fill("100")
        await page.get_by_label("현재 상태 설명", exact=True).fill(
            "합성 시험 물량입니다. 철스크랩 100kg, 고체이며 액체는 없습니다. "
            "유분 및 이물 함량은 측정하지 않았습니다. 실제 업체 인수를 요청하지 않습니다."
        )
        async with page.expect_response(
            lambda r: r.url.endswith("/workflow/lots") and r.request.method == "POST",
            timeout=30000,
        ) as created:
            await page.get_by_role("button", name="처리 건 등록", exact=True).click()
        created_response = await created.value
        assert created_response.ok, await created_response.text()
        lot = await created_response.json()
        rvalue = lot["data"]["recycling"]
        assert rvalue["status"] == "table_listed"
        assert rvalue["waste_code"] == case["expected_code"]
        assert lot["data"]["initial"]["recycling_types"] == rvalue["types"]
        print("UI created lot; recycling types and source persisted", flush=True)

        await page.reload()
        rbox = page.get_by_test_id("recycling-types")
        await expect(rbox).to_be_visible(timeout=20000)
        await rbox.locator("summary").click()
        await expect(rbox.locator("a")).to_have_attribute(
            "href", rvalue["source"]["url"]
        )
        async with page.expect_response(
            lambda r: r.url.endswith(f"/workflow/lots/{lot['id']}/candidates"),
            timeout=600000,
        ) as reviewed:
            await page.get_by_role("button", name="업체 검토 시작", exact=True).click()
        response = await reviewed.value
        assert response.ok, await response.text()
        lot = await response.json()
        review = lot["review"]
        expected = {
            f["capability_key"]
            for o in review["next_step"]["options"]
            for f in o["facilities"]
        }
        assert set(review["results"]) == expected
        assert review["recycling_checksum"]
        assert lot["data"]["recycling"] == rvalue
        assert all(r["dispatch_approved"] is False for r in review["results"].values())
        await expect(page.locator(".wf-review")).to_have_count(
            len(expected), timeout=20000
        )
        statuses = dict(Counter(r["status"] for r in review["results"].values()))
        lot_statuses = dict(
            Counter(
                (r.get("lot_review") or {}).get("status")
                for r in review["results"].values()
            )
        )
        saved = await context.request.get(
            f"{args.base}/api/v1/workflow/lots/{lot['id']}"
        )
        assert saved.ok
        stored = await saved.json()
        assert stored["review"]["recycling_checksum"] == review["recycling_checksum"]
        assert stored["data"]["recycling"] == rvalue
        await page.reload()
        await expect(page.locator(".wf-review")).to_have_count(
            len(expected), timeout=20000
        )
        await page.get_by_test_id("recycling-types").scroll_into_view_if_needed()
        await page.get_by_test_id("recycling-types").locator("summary").click()
        await page.screenshot(path=str(output.with_suffix(".png")), full_page=True)
        summary = {
            "case_id": case["case_id"],
            "lot_id": lot["id"],
            "material": args.material,
            "waste_code": case["expected_code"],
            "r_types": rvalue["types"],
            "source": rvalue["source"]["url"],
            "all_candidates_reviewed": len(expected),
            "statuses": statuses,
            "lot_statuses": lot_statuses,
            "recycling_persisted_after_reload": True,
            "review_persisted_after_reload": True,
            "dispatch_not_approved": True,
            "response": lot,
        }
        output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in summary.items() if k != "response"},
                ensure_ascii=False,
            )
        )
        await browser.close()
        assert (
            "model_unavailable" not in statuses
            and "model_unavailable" not in lot_statuses
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5178")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--material", default="ferrous_scrap", choices=["ferrous_scrap"]
    )
    asyncio.run(run(parser.parse_args()))
