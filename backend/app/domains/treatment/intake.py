from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.process import next_step, normalize_form
from app.domains.treatment.reference import resolve_material
from app.domains.treatment.schemas import (
    CatalogKey,
    NextStepRequest,
    ObservedOutput,
    RecyclingTypes,
    SourceLink,
)


class IntakeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    waste_code: str = Field(pattern=r"^\d{2}-\d{2}-\d{2}$")
    material: str = Field(min_length=1, max_length=80)
    input_form: str = Field(min_length=1, max_length=80)
    recycling_types: RecyclingTypes | None = None
    completed_transitions: list[CatalogKey] = Field(default_factory=list, max_length=8)
    observed_output: ObservedOutput | None = None

    @model_validator(mode="after")
    def validate_observation(self):
        if self.observed_output is not None and not self.completed_transitions:
            raise ValueError("An observed output requires a completed transition")
        return self


class IntakeRequest(IntakeSelection):
    capability_key: CatalogKey


class IntakeResult(BaseModel):
    status: Literal["reviewed", "needs_evidence", "model_unavailable"]
    finding: Literal["form_mentioned", "restriction_mentioned", "insufficient"] = "insufficient"
    next_check: str
    source: SourceLink | None = None
    quote: str | None = None
    dispatch_approved: Literal[False] = False


class IntakeBatchResult(BaseModel):
    results: dict[CatalogKey, IntakeResult]


def build_intake_batch(request: IntakeSelection, reference):
    follow_up = bool(request.completed_transitions)
    if follow_up and request.observed_output is None:
        return []
    result = next_step(NextStepRequest(**request.model_dump(exclude={"capability_key"})), reference)
    capabilities = {row.key: row for row in reference.capabilities}
    allowed = {row.key: row for row in reference.sources if row.model_transfer_allowed}
    material = resolve_material(request.material)
    form = normalize_form(request.input_form)
    return [
        {
            "capability_key": facility.capability_key,
            "site": facility.label,
            "site_scope": facility.evidence_basis,
            "process": option.label,
            "waste_code": None if follow_up else request.waste_code,
            "material": material,
            "form": option.input_state.label if follow_up else form,
            "recycling_types": option.recycling_types.model_dump()
            if not follow_up and option.recycling_types
            else {},
            "next_check": (
                facility.intake_review.next_check
                if facility.intake_review
                else "현재 형태의 반입 근거를 확인해 주세요."
            ),
            "sources": [
                {
                    "source_id": row.key,
                    "summary": row.summary,
                    "publisher": row.publisher,
                    "url": row.url,
                    "locator": row.locator,
                }
                for source_id in capabilities[facility.capability_key].input_profile.source_ids
                if (row := allowed.get(source_id)) is not None
            ],
        }
        for option in result.options
        for facility in option.facilities
    ]


def build_intake_packet(request: IntakeRequest, reference):
    for packet in build_intake_batch(request, reference):
        if packet["capability_key"] == request.capability_key:
            return packet
    raise TreatmentError("invalid-capability", "현재 공정에 연결된 업체를 선택해 주세요.")


async def review_intakes(packets, settings):
    results = {
        packet["capability_key"]: IntakeResult(
            status="model_unavailable", next_check=packet["next_check"]
        )
        for packet in packets
    }
    token = settings.scrap_intake_service_token.get_secret_value()
    if not packets or not settings.ai_base_url or not token:
        return IntakeBatchResult(results=results)

    async with httpx.AsyncClient(timeout=45) as client:
        for start in range(0, len(packets), 5):
            batch = packets[start : start + 5]
            try:
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/treatment/intake-reviews",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"candidates": batch},
                )
                response.raise_for_status()
                reviewed = IntakeBatchResult.model_validate(response.json())
            except (httpx.HTTPError, ValueError):
                continue
            for packet in batch:
                key = packet["capability_key"]
                if key in reviewed.results:
                    results[key] = reviewed.results[key]
    return IntakeBatchResult(results=results)
