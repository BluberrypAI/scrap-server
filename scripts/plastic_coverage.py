"""Read-only coverage report: uv run python ../scripts/plastic_coverage.py from backend."""

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domains.treatment.material_scope import FORM_CODES, PLASTICS  # noqa: E402
from app.domains.treatment.process import next_step  # noqa: E402
from app.domains.treatment.reference import PlanningReference, read_bundle  # noqa: E402
from app.domains.treatment.schemas import NextStepRequest  # noqa: E402


def report():
    reference = PlanningReference.model_validate(read_bundle("planning-reference.json"))
    rows = []
    for (material, form), codes in sorted(FORM_CODES.items()):
        if material not in PLASTICS:
            continue
        for code in codes:
            result = next_step(
                NextStepRequest(waste_code=code, material=material, input_form=form), reference
            )
            sites = {}
            for option in result.options:
                for f in option.facilities:
                    site = sites.setdefault(
                        f.facility_key,
                        {
                            "facility_key": f.facility_key,
                            "label": f.label,
                            "basis": f.evidence_basis,
                            "has_coordinates": f.location is not None,
                            "transitions": [],
                            "public_input_form_example": False,
                        },
                    )
                    site["transitions"].append(option.transition_key)
                    site["public_input_form_example"] |= bool(
                        f.intake_review and f.intake_review.form_evidence == "site_example"
                    )
            rows.append(
                {
                    "material": material,
                    "form": form,
                    "code": code,
                    "status": result.status,
                    "sites": list(sites.values()),
                }
            )
    return {
        "checked_on": date.today().isoformat(),
        "scope": "Curated research candidates; not verified current permits or acceptance",
        "counts": {
            "facilities": len(reference.facilities),
            "capabilities": len(reference.capabilities),
            "capability_evidence": dict(Counter(c.basis for c in reference.capabilities)),
            "transitions": len(reference.transitions),
            "sources": len(reference.sources),
            "plastic_input_combinations": len(rows),
            "query_statuses": dict(Counter(r["status"] for r in rows)),
        },
        "rows": rows,
    }


if __name__ == "__main__":
    value = report()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
    print(json.dumps(value["counts"], ensure_ascii=False, indent=2))
