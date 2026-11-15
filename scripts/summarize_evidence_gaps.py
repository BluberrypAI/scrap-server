"""Compare historical missing-evidence rows with a newly recorded model review.

Old reviews did not persist a cause. Never infer a historical model rationale.
Only store public capability identifiers and outcome categories in the report.
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def key(material, detail, form, capability):
    return material, detail, form, capability


def summarize(baseline, current, catalog):
    capabilities = {row["key"]: row for row in catalog["capabilities"]}
    facilities = {row["key"]: row for row in catalog["facilities"]}
    lookup = {}
    for batch in current["results"]:
        for capability, review in (
            (batch.get("response", {}).get("reviews") or {}).get("results", {}).items()
        ):
            lookup[
                key(
                    batch["material"],
                    batch.get("material_detail"),
                    batch["form"],
                    capability,
                )
            ] = review
    rows = []
    for old in baseline["rows"]:
        capability = capabilities[old["capability_key"]]
        site = facilities[capability["facility"]]
        review = lookup.get(
            key(
                old["diagnosis_material"],
                old.get("material_detail"),
                old["form"],
                old["capability_key"],
            )
        )
        rows.append(
            {
                **old,
                "facility_key": site["key"],
                "facility_name": site["label"],
                "historical_cause": "not_recorded",
                "current_status": review["status"] if review else "not_retested",
                "current_evidence_gaps": review.get("evidence_gaps", [])
                if review
                else [],
                "source_ids": capability["source_ids"],
            }
        )
    return {
        "scope": "252 historical review occurrences, not 252 facilities; current causes are NEW re-review results, not reconstructed historical model rationale",
        "baseline_occurrences": len(rows),
        "baseline_distinct_capabilities": len({r["capability_key"] for r in rows}),
        "baseline_distinct_facilities": len({r["facility_key"] for r in rows}),
        "current_status_counts": dict(Counter(r["current_status"] for r in rows)),
        "primary_gap_counts": dict(
            Counter(
                (r["current_evidence_gaps"] or ["unspecified"])[0]
                for r in rows
                if r["current_status"] == "needs_evidence"
            )
        ),
        "all_gap_counts_multiple_allowed": dict(
            Counter(
                gap
                for r in rows
                if r["current_status"] == "needs_evidence"
                for gap in set(r["current_evidence_gaps"] or ["unspecified"])
            )
        ),
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    report = summarize(
        read(args.baseline),
        read(args.current),
        read(root / "backend/app/domains/treatment/resources/planning-reference.json"),
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False)
    )
