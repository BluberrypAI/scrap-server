"""Initial SCRAP intake profiles and the team classifier's advisory handoff."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.domains.treatment.schemas import RecyclingTypes


@dataclass(frozen=True)
class Profile:
    label: str
    material: str
    input_form: str
    waste_codes: tuple[str, ...]
    engine_material: str
    resin_stream: str | None = None

    def seed(self) -> dict[str, Any]:
        answers = {"material": self.engine_material, "physical_state": "solid"}
        if self.resin_stream:
            answers["resin_stream"] = self.resin_stream
        return answers


PROFILES = {
    "pp-injection-scrap": Profile(
        "PP 사출 제조 잔재", "pp", "scrap", ("51-03-01",), "pp", "ordinary_resin"
    ),
    "pp-shredded": Profile("PP 파쇄품", "pp", "shredded", ("51-03-01",), "pp"),
    "pe-film": Profile("PE 폐필름", "pe", "film", ("51-03-01", "51-03-07"), "pe"),
    "pet-bottle": Profile(
        "사용 후 PET병", "pet", "bottle", ("51-03-07",), "pet", "discarded_packaging"
    ),
    "aluminium-beverage-can": Profile(
        "사용 후 알루미늄 음료캔", "aluminium", "can", ("51-29-03",), "metal_can"
    ),
}

INITIAL_PROFILES = {(row.material, row.input_form): row for row in PROFILES.values()}


class ClassifierStart(BaseModel):
    profile: str | None = None
    waste_id: str | None = None
    answers: dict[str, Any] = {}
    as_of: str | None = None

    def engine_payload(self):
        payload = self.model_dump(exclude={"profile"}, exclude_none=True)
        if self.profile is None:
            return payload
        profile = PROFILES.get(self.profile)
        if profile is None:
            raise AppError(422, ErrorCode.INVALID_FILTER, "지원하는 문진 유형을 선택해 주세요.")
        seed = profile.seed()
        if any(key in self.answers and self.answers[key] != value for key, value in seed.items()):
            raise AppError(422, ErrorCode.INVALID_FILTER, "선택한 유형과 답변이 서로 달라요.")
        payload["answers"] = {**self.answers, **seed}
        return payload


async def classifier_request(method, path, *, content=None, json=None):
    settings = get_settings()
    if not settings.classification_base_url:
        raise AppError(503, ErrorCode.ENGINE_UNAVAILABLE, "문진 엔진 주소를 확인해 주세요.")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            return await client.request(
                method,
                f"{settings.classification_base_url.rstrip('/')}/api/classification{path}",
                content=content,
                json=json,
                headers={"content-type": "application/json"},
            )
    except httpx.HTTPError:
        raise AppError(
            503, ErrorCode.ENGINE_UNAVAILABLE, "문진 엔진에 연결하지 못했어요."
        ) from None


class ClassificationHold(Exception):
    """A provisional candidate lookup must wait for a compatible classification."""


CLEAN_FACTS = {
    "physical_state": "solid",
    "oil_presence": "none",
    "pcb_possible": False,
    "toxic_chemical_discard": False,
    "designated_residue": False,
}


def recorded_recycling_types(record, profile, waste_code):
    items = record.get("items", {})
    hazards = record.get("hazards", {})
    code = items.get("code", {})
    recycling = items.get("recycling", {})
    if (
        record.get("record_version") != "1"
        or not record.get("complete")
        or record.get("open_items")
        or (record.get("material") or {}).get("id") != profile.engine_material
        or code.get("status") not in {"DETERMINED", "PROVISIONAL"}
        or code.get("code") != waste_code
        or items.get("designated", {}).get("value") != "NOT_DESIGNATED"
        or recycling.get("prohibited")
        or not recycling.get("allowed")
        or any(
            hazards.get(key, {}).get("state") != "VALUE" or hazards[key].get("value") != expected
            for key, expected in CLEAN_FACTS.items()
        )
    ):
        raise ClassificationHold("문진의 분류번호·재질·오염 여부를 확인해 주세요.")

    if profile.material == "aluminium":
        can_scope = code.get("facts_used", {}).get("can_scope", {})
        if can_scope.get("state") != "VALUE" or can_scope.get("value") != "covered_aluminium":
            raise ClassificationHold("알루미늄 음료캔인지 문진에서 확인해 주세요.")

    groups = {"free": [], "analysis": [], "unmarked": []}
    for item in recycling["allowed"]:
        required = item["pre_analysis_required"]
        group = "analysis" if required is True else "free" if required is False else "unmarked"
        groups[group].append(item["r_code"])
    return RecyclingTypes.model_validate(groups)


async def verified_recycling_types(
    session_id: UUID, material: str | None, input_form: str | None, waste_code: str
) -> RecyclingTypes:
    profile = INITIAL_PROFILES.get((material, input_form))
    if profile is None or waste_code not in profile.waste_codes:
        raise ClassificationHold("지원하는 분류번호·재질·형태 조합을 확인해 주세요.")
    upstream = await classifier_request("GET", f"/sessions/{session_id.hex}/record")
    if upstream.status_code == 404:
        raise ClassificationHold("문진 세션을 찾을 수 없어요. 문진을 다시 확인해 주세요.")
    try:
        upstream.raise_for_status()
        return recorded_recycling_types(upstream.json(), profile, waste_code)
    except (httpx.HTTPError, ValidationError, ValueError, KeyError, TypeError, AttributeError):
        raise AppError(503, ErrorCode.ENGINE_UNAVAILABLE, "문진 기록을 읽지 못했어요.") from None
