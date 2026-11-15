"""Live browser-proxy HTTP audit: button interview -> confirm -> every allowed form.

Uses synthetic local account/cases; never substitutes a handoff or classification.
Run from backend: uv run python ../scripts/audit_diagnosis_routes.py --output PATH
"""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx

MATERIALS = {
    "pp": ("plastic", "51-03-01"),
    "pe": ("plastic", "51-03-01"),
    "pet": ("plastic", "51-03-01"),
    "ps": ("plastic", "51-03-01"),
    "abs": ("plastic", "51-03-01"),
    "phenol_resin": ("plastic", "51-03-01"),
    "other_resin": ("plastic", "51-03-01"),
    "pvc": ("plastic", "51-03-03"),
    "pu_foam": ("plastic", "51-03-04"),
    "eps": ("plastic", "51-03-06"),
    "plastic_packaging": ("plastic", "51-03-07"),
    "fishing_net": ("plastic", "51-03-08"),
    "aqua_buoy": ("plastic", "51-03-05"),
    "rubber": ("plastic", "51-03-02"),
    "ferrous_scrap": ("metal", "51-29-01"),
    "nonferrous_scrap": ("metal", "51-29-02"),
    "metal_can": ("metal", "51-29-03"),
    "metal_container": ("metal", "51-29-04"),
}
ANSWERS = {
    "physical_state": "solid",
    "contamination_screen": "none_all",
    "scope_screen": "none_all",
    "public_facility": "none",
    "waste_facility": False,
    "daily_avg_kg": {"lo": 300.0, "lo_inc": True, "hi": None, "hi_inc": False},
    "resin_stream": "ordinary_resin",
    "emission_facility": True,
}
# Residual solvent is a safety/hold scenario, not a premise for a resin code.
RESIDUE_MATERIALS = (
    "pp",
    "pe",
    "pet",
    "ps",
    "abs",
    "phenol_resin",
    "other_resin",
    "pvc",
    "pu_foam",
    "eps",
    "rubber",
)


async def run(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    previous = (
        {
            r["material"]: r
            for r in json.loads(
                await asyncio.to_thread(Path(args.resume).read_text, encoding="utf-8")
            )["cases"]
        }
        if args.resume
        else {}
    )
    semaphore = asyncio.Semaphore(2)
    write_lock = asyncio.Lock()

    async def one(material, group, expected):
        async with (
            semaphore,
            httpx.AsyncClient(base_url=args.base, timeout=240) as client,
        ):

            async def request(method, path, **kw):
                response = await client.request(method, "/api/v1" + path, **kw)
                response.raise_for_status()
                return response.json()

            await request("POST", "/auth/dev-login", json={"email": args.email})
            row = {"material": material, "expected_code": expected, "questions": []}
            try:
                if material in previous:
                    row.update(previous[material])
                    if row["status"] != "interview_incomplete":
                        raise ValueError("Resume accepts incomplete synthetic interviews only")
                    case_id = row["case_id"]
                    turn = {"ui": row["final_ui"]}
                    row.pop("unanswered_question", None)
                    row["expected_code"] = expected
                else:
                    created = await request(
                        "POST", "/diagnosis/cases", json={"memo": "분류 연결 합성 검증"}
                    )
                    case_id, turn = created["case"]["id"], created["turn"]
                row["case_id"] = case_id
                values = {**ANSWERS, "material_group": group, "material": material}
                if args.hazards_only:
                    values.update(
                        {
                            "contamination_screen": "expand",
                            "designated_residue": True,
                            "oil_presence": "none",
                            "pcb_possible": False,
                            "chemical_itself": False,
                            "toxic_chemical_discard": False,
                            "residue_kind": "organic_solvent",
                        }
                    )
                for _ in range(25):
                    question = turn["ui"].get("question")
                    if not question:
                        break
                    value = values.get(question["key"])
                    option = next(
                        (
                            o
                            for o in question.get("options", [])
                            if o["kind"] == value or value is not None and o["value"] == value
                        ),
                        None,
                    )
                    if not option:
                        row["unanswered_question"] = question
                        break
                    row["questions"].append({"key": question["key"], "answer": option})
                    turn = await request(
                        "POST",
                        f"/diagnosis/cases/{case_id}/messages",
                        json={
                            "quick_reply": {
                                "key": question["key"],
                                **{k: option[k] for k in ("kind", "value")},
                            }
                        },
                    )
                row["final_ui"] = turn["ui"]
                if not turn["ui"].get("can_confirm"):
                    row["status"] = "interview_incomplete"
                else:
                    code = turn["ui"]["result"].get("code")
                    if not args.hazards_only:
                        row["code_matches"] = code == expected
                    confirmed = await request(
                        "POST",
                        f"/diagnosis/cases/{case_id}/confirm",
                        json={"expected_code": code},
                    )
                    row["handoff"] = confirmed.get("handoff")
                    path = f"/diagnosis/cases/{case_id}/treatment/next-step"
                    row["initial_context"] = await request("POST", path, json={})
                    context = row["initial_context"]
                    if context.get("requires_solid_confirmation"):
                        context = await request("POST", path, json={"solid_confirmed": True})
                    row["context"] = context
                    row["forms"] = []
                    choices = [m["value"] for m in context.get("available_materials", [])] or [None]
                    for material_detail in choices:
                        selected = await request(
                            "POST",
                            path,
                            json={
                                "material_detail": material_detail,
                                "solid_confirmed": True,
                            },
                        )
                        for form in selected.get("available_forms", []):
                            result = await request(
                                "POST",
                                path,
                                json={
                                    "input_form": form["value"],
                                    "solid_confirmed": True,
                                    "material_detail": material_detail,
                                },
                            )
                            options = (result.get("next_step") or {}).get("options", [])
                            row["forms"].append(
                                {
                                    "form": form["value"],
                                    "material_detail": material_detail,
                                    "status": result["status"],
                                    "next_status": (result.get("next_step") or {}).get("status"),
                                    "facilities": sorted(
                                        {
                                            f["facility_key"]
                                            for o in options
                                            for f in o["facilities"]
                                        }
                                    ),
                                    "response": result,
                                }
                            )
                    row["status"] = context["status"]
                    if args.hazards_only:
                        row["safety_check_passed"] = (
                            context["status"] == "review_required" and not row["forms"]
                        )
                    reread = await request("GET", f"/diagnosis/cases/{case_id}")
                    assert reread.get("handoff") == row["handoff"], "Confirmed handoff changed"
            except (
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                AssertionError,
            ) as error:
                row["status"] = "error"
                row["error"] = str(error)
            async with write_lock:
                rows.append(row)
                await asyncio.to_thread(
                    output.write_text,
                    json.dumps(
                        {
                            "scope": "Synthetic interview through web proxy; not legal validation",
                            "base": args.base,
                            "cases": rows,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            print(
                material,
                row["status"],
                row.get("code_matches"),
                [(f["form"], len(f["facilities"])) for f in row.get("forms", [])],
                flush=True,
            )

    scenarios = (
        {m: ("plastic", None) for m in RESIDUE_MATERIALS} if args.hazards_only else MATERIALS
    )
    if args.materials:
        scenarios = {m: scenarios[m] for m in args.materials}
    await asyncio.gather(*(one(m, *data) for m, data in scenarios.items()))
    print("SUMMARY", dict(Counter(row["status"] for row in rows)), flush=True)
    return int(
        any(
            row["status"] in {"error", "interview_incomplete"}
            or row.get("code_matches") is False
            or row.get("safety_check_passed") is False
            for row in rows
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5178")
    parser.add_argument("--email", default="dev@example.com")
    parser.add_argument("--output", required=True)
    parser.add_argument("--hazards-only", action="store_true")
    parser.add_argument("--materials", nargs="+", choices=tuple(MATERIALS))
    parser.add_argument(
        "--resume", help="Resume incomplete synthetic cases without creating duplicates"
    )
    raise SystemExit(asyncio.run(run(parser.parse_args())))
