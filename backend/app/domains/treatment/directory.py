"""Search public facility listings separately from curated process evidence."""

import base64
import binascii
import csv
import io
import json
import math
import re
from collections import Counter
from datetime import date
from functools import lru_cache
from hashlib import sha256

from app.domains.treatment import reference as graph
from app.domains.treatment.errors import TreatmentError, cursor_error
from app.domains.treatment.reference import node_id, read_bundle
from app.domains.treatment.schemas import FacilitySearchResponse

OWNER = "scrap-server-national-facility-v1"
MAX_ROWS = 100000
MAX_BYTES = 50 * 1024 * 1024
SOURCES = {
    "national-json": "https://www.data.go.kr/data/15114147/standard.do",
    "gimhae-csv": "https://www.data.go.kr/data/15033433/fileData.do",
}
NATIONAL_COLUMNS = {
    "FLCT_NM",
    "LCTN_ROAD_NM_ADDR",
    "LCTN_LOTNO_ADDR",
    "LAT",
    "LOT",
    "BUS_NM",
    "SPE_TRET_AREA_NM",
    "TRET_WAS_INF",
    "BUS_AREA",
    "FLCT_EQU_NM",
    "PERMI_YMD",
    "TELNO",
    "MNG_INST_NM",
    "CRTR_YMD",
    "INSTT_CODE",
    "INSTT_NM",
}
GIMHAE_COLUMNS = {"연번", "업종", "업소명", "등록일자", "폐기물종류", "주소", "위도", "경도"}


def text(row, name):
    return (row.get(name) or "").strip()


def coordinates(lat, lon):
    try:
        point = float(lat), float(lon)
        if (
            all(math.isfinite(v) for v in point)
            and 32 <= point[0] <= 39.5
            and 124 <= point[1] <= 132
        ):
            return point
    except (TypeError, ValueError):
        pass
    return None


def normalize_record(row, index, format_name, source_sha):
    columns = NATIONAL_COLUMNS if format_name == "national-json" else GIMHAE_COLUMNS
    if (
        not isinstance(row, dict)
        or set(row) != columns
        or any(v is not None and not isinstance(v, str) for v in row.values())
        or len(graph.canonical(row).encode()) > 32768
    ):
        raise ValueError("Unsupported facility registry columns or values")
    if format_name == "national-json":
        name, business, waste = (text(row, k) for k in ("FLCT_NM", "BUS_NM", "TRET_WAS_INF"))
        address = text(row, "LCTN_ROAD_NM_ADDR") or text(row, "LCTN_LOTNO_ADDR")
        point = coordinates(row.get("LAT"), row.get("LOT"))
        as_of, permit_date = text(row, "CRTR_YMD"), text(row, "PERMI_YMD")
        equipment, authority = text(row, "FLCT_EQU_NM"), text(row, "MNG_INST_NM")
    else:
        name, business, waste = (text(row, k) for k in ("업소명", "업종", "폐기물종류"))
        address = text(row, "주소")
        point = coordinates(row.get("위도"), row.get("경도"))
        # This CSV has no per-row reference date. A registration date is not one.
        as_of, permit_date = "", text(row, "등록일자")
        equipment, authority = "", "경상남도 김해시"
    if not name or not business:
        raise ValueError("Facility registry name and business type are required")
    try:
        date.fromisoformat(as_of)
    except ValueError:
        parsed_date = None
    else:
        parsed_date = as_of
    return {
        "listing_id": graph.identity("facility-listing", [SOURCES[format_name], source_sha, index]),
        "source_url": SOURCES[format_name],
        "source_sha256": source_sha,
        "source_row": index,
        "record_sha256": graph.digest(row),
        "raw_record": row,
        "name": name,
        "business_type": business,
        "waste_text": waste,
        "address": address,
        "equipment_text": equipment,
        "authority": authority,
        "as_of_raw": as_of,
        "as_of": parsed_date,
        "permit_date_raw": permit_date,
        "coordinates": list(point) if point else None,
        "coordinate_quality": "parsed-korea-bbox-not-site-verified"
        if point
        else "unavailable-or-invalid",
        "is_recycling_registration": "재활용업" in business,
        "waste_codes": sorted(set(re.findall(r"(?<!\d)\d{2}-\d{2}-\d{2}(?!\d)", waste))),
        "current_acceptance": None,
        "current_available_capacity_kg": None,
        "current_permit_scope": None,
        "process_capability_verified": False,
        "model_transfer_allowed": False,
        "dispatch_approved": False,
    }


def load_snapshot(path, format_name, expected_sha256):
    if format_name not in SOURCES or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("Known registry format and expected SHA-256 are required")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Facility registry exceeds byte limit")
    content = path.read_bytes()
    if sha256(content).hexdigest() != expected_sha256:
        raise ValueError("Facility registry source checksum mismatch")
    if format_name == "national-json":
        rows = json.loads(content.decode("utf-8-sig"))
    else:
        rows = list(csv.DictReader(io.StringIO(content.decode("cp949"))))
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("Facility registry must be a nonempty, bounded record list")
    records = [
        normalize_record(row, i, format_name, expected_sha256) for i, row in enumerate(rows, 1)
    ]
    return records, {
        "owner": OWNER,
        "schema_version": 1,
        "format": format_name,
        "source_url": SOURCES[format_name],
        "source_sha256": expected_sha256,
        "records_sha256": graph.digest(records),
        "record_count": len(records),
        "model_transfer_allowed": False,
    }


ALGORITHM = "registry-facility-discovery-v2"
EQUIPMENT_HINTS = {
    "pet-prepare": ["압축", "선별"],
    "pet-bale-to-flake": ["선별", "분쇄", "세척"],
    "pet-wash": ["세척"],
    "pet-finish": ["건조", "금속분리", "금속 분리"],
    "pet-pelletise": ["압출", "펠렛", "펠릿"],
    "pp-prepare": ["파쇄", "분쇄", "선별"],
    "pe-prepare": ["파쇄", "분쇄", "선별"],
    "pp-clean": ["세척"],
    "pp-shredded-to-pellet": ["세척", "분쇄", "압출", "펠릿", "펠렛"],
    "pe-clean": ["세척"],
    "pp-pelletise": ["압출", "펠렛", "펠릿"],
    "pe-pelletise": ["압출", "펠렛", "펠릿"],
    "pp-compound": ["컴파운딩", "배합", "혼합"],
    "pe-compound": ["컴파운딩", "배합", "혼합"],
    "al-can-sheet": ["용해", "주조", "압연"],
    "al-can-to-ingot": ["용해", "주조"],
    "paper-board": ["초지", "제지", "펄프"],
}
MATERIAL_LABELS = {
    "pet": r"(?<![a-z])pet(?![a-z])|페트|폴리에틸렌\s*테레프탈레이트",
    "pp": r"(?<![a-z])pp(?![a-z])|폴리프로필렌|polypropylene",
    "pe": (
        r"(?<![a-z])(?:pe|hdpe|ldpe|lldpe)(?![a-z])|폴리에틸렌(?!\s*테레프탈레이트)"
        r"|polyethylene(?!\s+terephthalate)"
    ),
    "paper": r"폐지(?!방)|종이|(?<![가-힣])고지(?![가-힣])|골판지|(?<![a-z])paper(?![a-z])",
    "aluminium": r"알루미늄|알미늄|(?<![a-z])alumin(?:um|ium)(?![a-z])",
}
LIMITATIONS = [
    "공정, 현행 허가, 인수와 여유 용량은 시설에 확인해야 합니다.",
    "폐합성수지 명부 표기는 구체적인 재질과 인수 조건을 확인할 단서입니다.",
    "별표 4 코드는 검색 단서이며 명부 기준일과 현재 허가는 별도로 확인해야 합니다.",
    "명부 좌표의 직선거리는 참고값입니다.",
    "명부 후보는 공개 근거가 있는 공정 연결과 분리합니다.",
    "외부 모델에는 명부 본문을 전달하지 않습니다.",
]


def material_match(record, material, waste_code=None, *, codebook=None):
    if waste_code:
        return (
            "requested_code_not_material_validated" if waste_code in record["waste_codes"] else None
        )
    waste = record["waste_text"]
    if re.search(MATERIAL_LABELS[material], waste, re.IGNORECASE):
        return "material_label_only"
    if material in {"pet", "pp", "pe"} and re.search("합성수지|플라스틱|폐수지", waste):
        return "broad_category_only"
    if material == "aluminium" and re.search("폐금속|비철금속|금속스크랩", waste):
        return "broad_category_only"
    if record["waste_codes"]:
        book = codebook or load_codebook()
        rows = [book["records"].get(code) for code in record["waste_codes"]]
        hits = [r for r in rows if r and material in r["query_materials"]]
        if hits:
            return (
                "named_material_code_only"
                if any(r["match_kind"] == "named_material_code_only" for r in hits)
                else "code_category_only"
            )
        if any(row is None for row in rows):
            return "unmapped_codes_require_review"
    return None


def straight_line_km(origin, point):
    if point is None or origin is None:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, [*origin, *point])
    term = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return round(6371.0088 * 2 * math.asin(min(1.0, math.sqrt(max(0.0, term)))), 1)


def equipment_mentions(record, transition_key):
    return [
        term for term in EQUIPMENT_HINTS.get(transition_key, []) if term in record["equipment_text"]
    ]


def registry_matches(records, material, request, *, codebook=None):
    book = codebook or load_codebook()
    matches, counts = (
        [],
        {"non_recycling_registration": 0, "region_no_match": 0, "no_material_or_code_hit": 0},
    )
    origin = (
        (request.origin_latitude, request.origin_longitude)
        if request.origin_latitude is not None
        else None
    )
    for record in records:
        if request.transition_key and not record["is_recycling_registration"]:
            counts["non_recycling_registration"] += 1
            continue
        if request.region and graph.normalize_label(request.region) not in graph.normalize_label(
            record["address"]
        ):
            counts["region_no_match"] += 1
            continue
        match = material_match(record, material, request.waste_code, codebook=book)
        if match is None:
            counts["no_material_or_code_hit"] += 1
            continue
        distance = straight_line_km(origin, record["coordinates"])
        matches.append((record, match, distance))
    buckets = {
        "material_label_only": 0,
        "requested_code_not_material_validated": 0,
        "named_material_code_only": 0,
        "broad_category_only": 1,
        "code_category_only": 1,
        "unmapped_codes_require_review": 2,
    }
    matches.sort(
        key=lambda v: (
            not bool(equipment_mentions(v[0], request.transition_key)),
            buckets[v[1]],
            v[2] if v[2] is not None else math.inf,
            v[0]["listing_id"],
        )
    )
    return matches, counts


def encode_cursor(value):
    return base64.urlsafe_b64encode(graph.canonical(value).encode()).decode().rstrip("=")


def decode_cursor(value):
    try:
        row = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(row, dict)
            or set(row)
            != {"algorithm", "graph", "registry", "codes", "request", "namespace", "offset"}
            or row["algorithm"] != ALGORITHM
            or type(row["offset"]) is not int
            or row["offset"] < 0
            or not all(
                isinstance(row[k], str) and row[k]
                for k in ("graph", "registry", "codes", "request", "namespace")
            )
        ):
            raise ValueError()
        return row
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise cursor_error() from None


@lru_cache
def load_codebook():
    try:
        value = read_bundle("facility-code-labels.json")
        rows = value["records"]
        if (
            value["schema_version"] != 1
            or len(rows) != 313
            or len({r["code"] for r in rows}) != len(rows)
            or not re.fullmatch(r"[a-f0-9]{64}", value["source"]["pdf_sha256"])
            or any(
                not re.fullmatch(r"\d{2}-\d{2}-\d{2}", r["code"])
                or not isinstance(r["label_excerpt"], str)
                or not r["label_excerpt"]
                or type(r["page"]) is not int
                or not 1 <= r["page"] <= 14
                or r["section"] not in {"business_non_designated", "household", "designated"}
                or not isinstance(r["query_materials"], list)
                or not set(r["query_materials"]) <= {"pe", "pp", "pet", "paper", "aluminium"}
                or r["match_kind"] not in {None, "code_category_only", "named_material_code_only"}
                or bool(r["query_materials"]) != bool(r["match_kind"])
                for r in rows
            )
        ):
            raise ValueError()
        return {
            "records": {r["code"]: r for r in rows},
            "source": value["source"],
            "sha256": graph.digest(value),
        }
    except (OSError, ValueError, TypeError, KeyError):
        raise TreatmentError(
            "codebook-integrity", "폐기물 코드 분류표의 원본·버전 검사가 실패했습니다."
        ) from None


def code_interpretations(codes, material, book):
    items = []
    for code in codes:
        row = book["records"].get(code)
        items.append(
            {
                "code": code,
                "label_excerpt": row["label_excerpt"] if row else None,
                "page": row["page"] if row else None,
                "section": row["section"] if row else None,
                "query_scope": "search_hint_only"
                if row and material in row["query_materials"]
                else "no_configured_material_hint"
                if row
                else "unmapped_requires_review",
                "permit_validated": False,
                "historical_code_consistency_verified": False,
            }
        )
    return items


def assess_binding(transition, capability):
    basis = capability.basis if capability else "missing_facility"
    direct = basis == "published_site_process"
    return {
        "binding_basis": basis,
        "published_site_process": "source_support" if direct else "needs_verification",
        "specific_lot_specifications": "needs_verification",
        "current_permit_scope": "needs_verification",
        "current_acceptance": "needs_verification",
        "available_capacity": "needs_verification",
        "handoff_specifications": "needs_verification",
        "ready_for_dispatch": False,
        "source_ids": sorted(
            set(transition.source_ids + (capability.source_ids if capability else []))
        ),
        "next_action": (
            "공개 공정과 이번 로트의 규격을 대조하고 현행 허가·인수·용량을 확인"
            if direct
            else "해당 시설의 소재별 설비·공정 수행 근거를 먼저 확보하고 로트 조건을 대조"
        )
        if capability
        else "시설 후보와 공정 수행 근거를 확보",
    }


def reference_bindings(value, transition, audience):
    facilities = {f.key: f for f in value.facilities}
    sources = {s.key: s for s in value.sources}
    items = []
    for cap in sorted(value.capabilities, key=lambda c: c.key):
        if cap.transition != transition.key:
            continue
        facility = facilities[cap.facility]
        sids = sorted(set(cap.source_ids + transition.source_ids + facility.source_ids))
        blocked = [node_id("Evidence", s) for s in sids if not sources[s].model_transfer_allowed]
        packet = {
            "facility": facility.model_dump(mode="json"),
            "capability": cap.model_dump(mode="json"),
            "assessment": assess_binding(transition, cap),
            "evidence": [
                {"evidence_id": node_id("Evidence", s), **sources[s].model_dump(mode="json")}
                for s in sids
            ],
        }
        items.append(
            {
                "capability_id": node_id("FacilityCapability", cap.key),
                "research_packet": None if blocked and audience == "external_model" else packet,
                "external_model_allowed": not blocked,
                "withheld_evidence_ids": blocked,
                "dispatch_approved": False,
            }
        )
    return items


@lru_cache
def web_leads():
    return read_bundle("facility-web-leads.json")


def read_web_leads(material, region):
    group = {"pp": "pp-pe", "pe": "pp-pe", "pet": "pet", "aluminium": "al-can"}.get(material)
    return [
        {
            **row,
            "provider": batch["provider"],
            "review_status": "needs_review",
            "dispatch_approved": False,
        }
        for batch in web_leads()
        if batch["material"] == group
        for row in batch["leads"]
        if row["url"].startswith("https://")
        and (
            not region
            or graph.normalize_label(region) in graph.normalize_label(row["address"] or "")
        )
    ]


def project(value, registry, request, *, generation, fingerprint, namespace, backend):
    cursor = decode_cursor(request.cursor) if request.cursor else None
    binding = graph.digest(request.model_dump(exclude={"cursor", "page_size"}))
    transition = next(
        (t for t in (value.transitions if value else []) if t.key == request.transition_key), None
    )
    if request.transition_key and transition is None:
        raise TreatmentError("invalid-transition", "적재된 공정 전이 key를 사용해 주세요.")
    material = (
        next(s.material for s in value.states if s.key == transition.input_state)
        if transition
        else None
    )
    codebook = load_codebook()
    if request.waste_code and request.waste_code not in codebook["records"]:
        raise TreatmentError("invalid-code", "별표 4 분류번호를 확인해 주세요.")
    stamp = {
        "algorithm": ALGORITHM,
        "graph": generation,
        "registry": registry["generation"] if registry else "not-imported",
        "codes": codebook["sha256"],
        "request": binding,
        "namespace": namespace,
    }
    if cursor:
        if cursor["namespace"] != namespace or cursor["request"] != binding:
            raise cursor_error()
        if any(cursor[key] != stamp[key] for key in ("graph", "registry", "codes")):
            raise cursor_error("stale-cursor")
    matches, counts = (
        registry_matches(registry["records"], material, request, codebook=codebook)
        if registry
        else ([], {})
    )
    offset = cursor["offset"] if cursor else 0
    if cursor and offset >= len(matches):
        raise cursor_error()
    selected = matches[offset : offset + request.page_size]
    more = offset + len(selected) < len(matches)
    items = []
    for record, match, distance in selected:
        packet = {k: v for k, v in record.items() if k != "raw_record"}
        packet.update(
            material_match=match,
            code_interpretations=code_interpretations(record["waste_codes"], material, codebook),
            code_mapping_source=codebook["source"],
            stage_capability="not_established",
            equipment_mentions=equipment_mentions(record, request.transition_key),
            equipment_evidence_scope="literal_mentions_only_not_whole_transition_or_material_compatibility",
            region_match="not_requested"
            if not request.region
            else "label_match"
            if record["address"]
            else "unknown",
            straight_line_distance_km=distance,
            road_distance_km=None,
            transport_cost_krw=None,
            next_action="시설 식별·해당 공정 설비·투입 규격·현행 허가·이번 로트 인수 조건 확인",
        )
        external = request.audience == "external_model"
        items.append(
            {
                "listing_id": record["listing_id"],
                "research_packet": None if external else packet,
                "external_model_allowed": False,
                "withheld": external,
                "dispatch_approved": False,
            }
        )
    refs = reference_bindings(value, transition, request.audience) if transition else []
    return FacilitySearchResponse(
        backend=backend,
        status="reference_only"
        if registry is None
        else "candidates"
        if matches or refs
        else "no_candidates",
        transition_key=request.transition_key,
        material=material,
        reference_bindings=refs,
        registry_candidates=items,
        web_research_leads=read_web_leads(material, request.region)
        if request.audience == "internal" and material
        else [],
        pagination={
            "total_registry_candidates": len(matches),
            "returned_count": len(items),
            "has_more": more,
            "next_cursor": encode_cursor({**stamp, "offset": offset + len(items)})
            if more
            else None,
        },
        graph_trace={
            "generation": generation,
            "reference_sha256": fingerprint,
            "codebook_sha256": codebook["sha256"],
            "registry_generation": stamp["registry"],
            "registry_source_sha256": registry["manifest"]["source_sha256"] if registry else None,
        },
        search_scope={
            "registry_imported": registry is not None,
            "registry_record_count": registry["manifest"]["record_count"] if registry else 0,
            "filter_counts": counts,
            "match_counts": dict(Counter(match for _, match, _ in matches)),
            "ordering": "equipment_mentions_then_material_match_bucket_then_straight_line_then_id",
            "not_feasibility_or_cost_ranking": True,
            "code_categories_not_material_or_permit_approval": True,
            "unmapped_codes_preserved": request.waste_code is None,
            "location_filters_apply_to_registry_only": True,
            "automatic_path_insertion": False,
        },
        limitations=LIMITATIONS,
    )
