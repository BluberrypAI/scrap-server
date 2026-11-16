"""Compare explicit material/form/code coverage; origins are synthetic test points."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domains.treatment.material_scope import FORM_CODES  # noqa: E402
from app.domains.treatment.process import next_step  # noqa: E402
from app.domains.treatment.reference import PlanningReference, read_bundle  # noqa: E402
from app.domains.treatment.schemas import NextStepRequest  # noqa: E402

ORIGINS = {
    "seoul": (37.5665, 126.978),
    "hwaseong": (37.1996, 126.8312),
    "paju": (37.7599, 126.78),
    "anseong": (37.0079, 127.2797),
    "namyangju": (37.636, 127.2165),
}


def region(value):
    return next((key for key in ("서울", "경기", "인천") if value.startswith(key)), "기타")


def report(reference):
    rows = []
    facilities = {f.key: f for f in reference.facilities}
    linked = {c.facility for c in reference.capabilities}
    for (material, form), codes in sorted(FORM_CODES.items()):
        for code in codes:
            origins = {}
            for name, (lat, lon) in ORIGINS.items():
                result = next_step(
                    NextStepRequest(
                        material=material,
                        input_form=form,
                        waste_code=code,
                        origin={"latitude": lat, "longitude": lon},
                    ),
                    reference,
                )
                sites = {f.facility_key: f for o in result.options for f in o.facilities}
                ranked = sorted(
                    (f for f in sites.values() if f.distance_rank), key=lambda f: f.distance_rank
                )
                origins[name] = [
                    {"facility_key": f.facility_key, "distance_km": f.straight_line_distance_km}
                    for f in ranked
                ]
                if name == "seoul":
                    sites_at_start = sites
                else:
                    assert sites.keys() == sites_at_start.keys(), (
                        "Location dropped a review candidate"
                    )
            rows.append(
                {
                    "material": material,
                    "form": form,
                    "code": code,
                    "status": result.status,
                    "national_sites": len(sites),
                    "capital_sites": sum(region(f.region) != "기타" for f in sites.values()),
                    "capital_sites_with_coordinates": sum(
                        region(f.region) != "기타" and f.location is not None
                        for f in sites.values()
                    ),
                    "regions": dict(Counter(region(f.region) for f in sites.values())),
                    "sites": sorted(sites),
                    "top5_by_straight_line": origins,
                }
            )
    return {
        "scope": "공개 공정 조사 후보 수. 현행 허가·물량 수락·도로 운송시간 검증 수치가 아님.",
        "synthetic_origin_points": ORIGINS,
        "counts": {
            "facilities": len(facilities),
            "linked_facilities": len(linked),
            "capabilities": len(reference.capabilities),
            "capability_basis": dict(Counter(c.basis for c in reference.capabilities)),
            "linked_site_regions": dict(Counter(region(facilities[k].region) for k in linked)),
            "code_form_combinations": len(rows),
            "status_counts": dict(Counter(r["status"] for r in rows)),
        },
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = {
        "after": report(PlanningReference.model_validate(read_bundle("planning-reference.json")))
    }
    if args.before:
        data["before"] = report(
            PlanningReference.model_validate_json(Path(args.before).read_text(encoding="utf-8"))
        )
    Path(args.output).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v["counts"] for k, v in data.items()}, ensure_ascii=False, indent=2))
