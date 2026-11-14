"""Cross-check public factory products with the entire recycler queue, without promotion.

Accepts the original KICOX ZIP/CSV and the screened registry CSV. No HTTP, credentials,
geocoding, fuzzy entity merging, database writes, or automatic capability creation.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

FIELDS = {"순번", "회사명", "생산품", "공장주소"}
RESINS = {
    "pp": r"(?<![A-Za-z])PP(?![A-Za-z])|폴리프로필렌|폴리프로필린",
    "pe": r"(?<![A-Za-z])(?:PE|HDPE|LDPE|LLDPE)(?![A-Za-z])|폴리에틸렌(?!글리콜|테레프탈레이트)",
    "ps": r"(?<![A-Za-z])(?:PS|HIPS|GPPS)(?![A-Za-z])|폴리스티렌",
    "pet": r"(?<![A-Za-z])PET(?![A-Za-z])|폴리에틸렌테레프탈레이트",
    "abs": r"(?<![A-Za-z])ABS(?![A-Za-z])",
    "pvc": r"(?<![A-Za-z])PVC(?![A-Za-z])|폴리염화비닐",
}


def resins(text):
    return [key for key, pattern in RESINS.items() if re.search(pattern, text, re.IGNORECASE)]


def name_key(value):
    return re.sub(r"주식회사|\(주\)|㈜|\(유\)|\s", "", value).casefold()


def address_key(value):
    # Strip only building notes after the road-address core. Never drop house numbers,
    # infer lot/road equivalence, or remove a new administrative district by guesswork.
    core = re.split(r"\s외\s|\(|,", value)[0]
    return re.sub(r"\s", "", core).replace("전북특별자치도", "전라북도")


def read_factory(path):
    raw = path.read_bytes()
    payload = raw
    member = None
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            candidates = [
                n for n in archive.namelist() if n.endswith(".csv") and "등록공장현황자료_" in n
            ]
            if len(candidates) != 1:
                raise ValueError("Expected one factory CSV in the official archive")
            member = candidates[0]
            payload = archive.read(member)  # No extraction to disk / no zip path traversal.
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("cp949")
    reader = csv.DictReader(io.StringIO(text))
    if not FIELDS <= set(reader.fieldnames or []):
        raise ValueError("Not the official factory dataset; required columns missing")
    rows = [{key: row.get(key, "") for key in sorted(FIELDS)} for row in reader]
    return rows, hashlib.sha256(raw).hexdigest(), member


def crosscheck(factory, queue):
    index = defaultdict(list)
    for row in factory:
        if name_key(row["회사명"]):
            index[name_key(row["회사명"])].append(row)
    groups = defaultdict(list)
    for row in queue:
        if row["role"] == "recycling":
            groups[row["site_cluster"]].append(row)
    results = []
    for cluster, rows in sorted(groups.items()):
        representative = rows[0]
        candidates = index.get(name_key(representative["name"]), [])
        address = address_key(representative["address"])
        exact = [r for r in candidates if address and address_key(r["공장주소"]) == address]
        selected = exact or candidates
        status = (
            "exact_name_address"
            if exact
            else "name_only_address_unresolved"
            if candidates
            else "not_found"
        )
        products = [r["생산품"] for r in exact]
        materials = sorted({m for p in products for m in resins(p)})
        results.append(
            {
                "site_cluster": cluster,
                "registry_source_rows": [int(r["source_row"]) for r in rows],
                "name": representative["name"],
                "address": representative["address"],
                "match_status": status,
                "factory_records": selected,
                "product_resin_mentions": materials,
                "capability_status": "research_only_not_promoted",
                "intake_form": "unknown",
                "current_permit": "unknown",
                "acceptance": "unknown",
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("factory", type=Path)
    parser.add_argument("queue", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    factory, digest, member = read_factory(args.factory)
    with args.queue.open(encoding="utf-8-sig", newline="") as handle:
        queue = list(csv.DictReader(handle))
    rows = crosscheck(factory, queue)
    summary = {
        "source_url": "https://www.data.go.kr/data/15105482/fileData.do",
        "source_sha256": digest,
        "archive_member": member,
        "factory_rows": len(factory),
        "recycler_clusters": len(rows),
        "matches": dict(Counter(r["match_status"] for r in rows)),
        "exact_sites_with_resin_mentions": sum(bool(r["product_resin_mentions"]) for r in rows),
        "promoted_automatically": 0,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    for name, value in [("factory-crosscheck.json", {"summary": summary, "rows": rows})]:
        (args.out / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
