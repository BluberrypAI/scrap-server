"""Trust only a company-owned engine result bound to the current verdict."""

from datetime import date

from pydantic import ValidationError

from app.domains.treatment.schemas import RecyclingTypes


def recycling_for_handoff(detail):
    h = detail.get("handoff") or {}
    value = detail.get("recycling") or h.get("recycling")
    if not isinstance(value, dict):
        return None
    if (
        value.get("contract") != "recycling-types-v1"
        or value.get("case_id") != h.get("case_id")
        or value.get("verdict_version") != h.get("verdict_version")
        or value.get("waste_code") != h.get("waste_code")
        or value.get("as_of") != (h.get("timestamps") or {}).get("as_of")
        or h.get("category") != "GENERAL"
        or h.get("result_type") != "WASTE_CODE"
        or (h.get("route_guidance") or {}).get("action") != "RECOMMEND_ROUTE"
    ):
        return None
    if value.get("status") == "table_listed":
        try:
            source = value["source"]
            if (
                not source["url"].startswith("https://www.law.go.kr/")
                or date.fromisoformat(value["as_of"])
                < date.fromisoformat(source["law_effective_from"])
                or not value.get("version")
                or not value.get("checksum")
                or value.get("facility_permit_verified") is not False
            ):
                return None
            RecyclingTypes.model_validate(value["types"])
        except (KeyError, ValueError, TypeError, ValidationError):
            return None
    return value


def route_recycling(value):
    if not value or value.get("status") != "table_listed":
        return {"recycling_types": None, "recycling_basis": None}
    # No company/case identifiers leave the server as legal lookup metadata.
    return {
        "recycling_types": value["types"],
        "recycling_basis": {
            "version": value["version"],
            "as_of": value["as_of"],
            "source_url": value["source"]["url"],
            "pages": value["pages"],
            "notes": value["notes"],
        },
    }
