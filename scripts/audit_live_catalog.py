"""Read-only HTTP catalogue reachability audit. No AI approvals or permits inferred."""

import argparse
import json
import sys
from collections import Counter, deque
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def run(base):
    from app.domains.treatment.material_scope import FORM_CODES
    from app.domains.treatment.reference import read_bundle

    reference = read_bundle("planning-reference.json")
    pending = deque(
        {"material": material, "input_form": form, "waste_code": code}
        for (material, form), codes in FORM_CODES.items()
        for code in codes
    )
    seen, reached, transitions, results = set(), set(), set(), []
    with httpx.Client(base_url=base, timeout=30) as client:
        while pending:
            request = pending.popleft()
            state = request.get("observed_output", {}).get("state_key")
            key = (request["material"], request["waste_code"], request["input_form"], state)
            if key in seen:
                continue
            seen.add(key)
            request["origin"] = {"latitude": 37.16, "longitude": 126.9}
            response = client.post("/api/treatment/next-step", json=request)
            response.raise_for_status()
            result = response.json()
            facilities = [f for o in result["options"] for f in o["facilities"]]
            ranked = {
                f["facility_key"]: f["distance_rank"] for f in facilities if f["distance_rank"]
            }
            assert len(ranked) <= 5
            assert not result["dispatch_approved"]
            reached.update(f["capability_key"] for f in facilities)
            results.append(
                {
                    "request": request,
                    "status": result["status"],
                    "message": result["message"],
                    "site_count": len({f["facility_key"] for f in facilities}),
                    "capabilities": [f["capability_key"] for f in facilities],
                    "ranked": ranked,
                    "processes": [o["transition_key"] for o in result["options"]],
                    "unbound_processes": [
                        o["transition_key"] for o in result["options"] if not o["facilities"]
                    ],
                    "can_finish": result["can_finish"],
                }
            )
            for option in result["options"]:
                transitions.add(option["transition_key"])
                done = [*request.get("completed_transitions", []), option["transition_key"]]
                if len(done) > 8:
                    continue
                pending.append(
                    {
                        **request,
                        "completed_transitions": done,
                        "observed_output": {
                            "state_key": option["output_state"]["key"],
                            "mass_kg": 950,
                            "review_reference": "SYNTHETIC-REACHABILITY-NOT-REAL-OUTPUT",
                        },
                    }
                )
        unsupported = []
        for material, code in [
            ("copper", "51-29-02"),
            ("metal", "51-29-99"),
        ]:
            r = client.post(
                "/api/treatment/next-step",
                json={"material": material, "waste_code": code, "input_form": "scrap"},
            )
            unsupported.append({"material": material, "http": r.status_code, "result": r.json()})
    caps = [
        {
            "key": c["key"],
            "facility": c["facility"],
            "transition": c["transition"],
            "basis": c["basis"],
            "reachable": c["key"] in reached,
        }
        for c in reference["capabilities"]
    ]
    return {
        "scope": (
            "HTTP over actual Docker server/PostgreSQL. Observed outputs are synthetic "
            "traversal inputs, including processes without bound facilities, not real shipments."
        ),
        "counts": {
            "facilities": len(reference["facilities"]),
            "transitions": len(reference["transitions"]),
            "capabilities": len(caps),
            "reached_capabilities": len(reached),
            "reached_processes": len(transitions),
            "queries": len(results),
            "statuses": dict(Counter(r["status"] for r in results)),
        },
        "capabilities": caps,
        "unreached_processes": [
            t["key"] for t in reference["transitions"] if t["key"] not in transitions
        ],
        "queries": results,
        "unsupported_metals": unsupported,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run(args.base)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
