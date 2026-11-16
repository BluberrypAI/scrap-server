"""Screen EVERY registry row for research; never promote rows into capabilities.

uv run python scripts/plastic_registry_screen.py registry.json --out docs/registry-screen
Only public business fields are exported; telephone/contact fields are omitted.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

PLASTIC = re.compile(
    r"(?<!\d)51\s*-\s*03(?:\s*-\s*\d{2})?(?!\d)|폐합성수지|플라스틱|폐비닐|스티로폼"
)


def screen(records):
    rows = []
    for index, record in enumerate(records, 1):
        waste = str(record.get("TRET_WAS_INF") or "")
        if not PLASTIC.search(waste):
            continue
        business = str(record.get("BUS_NM") or "")
        role = (
            "recycling"
            if "재활용" in business
            else "transport_only"
            if "운반" in business
            else "disposal"
            if "처분" in business
            else "unknown"
        )
        equipment = str(record.get("FLCT_EQU_NM") or "")
        name = str(record.get("FLCT_NM") or "").strip()
        address = str(
            record.get("LCTN_ROAD_NM_ADDR") or record.get("LCTN_LOTNO_ADDR") or ""
        ).strip()
        # An exact name/address cluster is a research group, NOT legal-entity resolution.
        # Missing identities must not collapse into a single invented site.
        identity = [name, address] if name and address else [name, address, index]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
        rows.append(
            {
                "source_row": index,
                "site_cluster": key,
                "name": name,
                "address": address,
                "business": business,
                "role": role,
                "waste_text": waste,
                "equipment_text": equipment,
                "as_of": str(record.get("CRTR_YMD") or ""),
                "priority": "1_equipment_review"
                if role == "recycling" and equipment
                else "2_process_source_needed"
                if role == "recycling"
                else "3_not_recycler",
                "capability_status": "unverified_directory_record",
                "material": "unknown",
                "input_form": "unknown",
                "acceptance": "unknown",
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.registry.read_bytes()
    records = json.loads(raw.decode("utf-8-sig"))
    rows = screen(records)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, selected in [
        ("all-plastic-rows", rows),
        ("recycler-research-queue", [r for r in rows if r["role"] == "recycling"]),
    ]:
        with (args.out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ["source_row"])
            writer.writeheader()
            writer.writerows(
                sorted(selected, key=lambda r: (r["priority"], r["site_cluster"], r["source_row"]))
            )
    summary = {
        "source_url": "https://www.data.go.kr/data/15114147/standard.do",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "registry_rows": len(records),
        "plastic_rows": len(rows),
        "exact_name_address_clusters": len({r["site_cluster"] for r in rows}),
        "business_roles": dict(Counter(r["role"] for r in rows)),
        "recycler_clusters": len({r["site_cluster"] for r in rows if r["role"] == "recycling"}),
        "priorities": dict(Counter(r["priority"] for r in rows)),
        "policy": (
            "Every selected row is unverified. Codes/equipment do not establish resin, "
            "intake form, current permits or acceptance. No automatic capability import."
        ),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
