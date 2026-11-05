from pydantic import BaseModel, ConfigDict, Field

from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.process import next_step, normalize_form
from app.domains.treatment.reference import resolve_material
from app.domains.treatment.schemas import CatalogKey, NextStepRequest


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    waste_code: str = Field(pattern=r"^\d{2}-\d{2}-\d{2}$")
    material: str = Field(min_length=1, max_length=80)
    input_form: str = Field(min_length=1, max_length=80)
    capability_key: CatalogKey


def build_intake_packet(request: IntakeRequest, reference):
    result = next_step(NextStepRequest(**request.model_dump(exclude={"capability_key"})), reference)
    candidate = next(
        (
            facility
            for option in result.options
            for facility in option.facilities
            if facility.capability_key == request.capability_key
        ),
        None,
    )
    if candidate is None or candidate.intake_review is None:
        raise TreatmentError("invalid-capability", "현재 첫 공정에 연결된 업체를 선택해 주세요.")
    capability = next(row for row in reference.capabilities if row.key == request.capability_key)
    return {
        "site": candidate.label,
        "material": resolve_material(request.material),
        "form": normalize_form(request.input_form),
        "next_check": candidate.intake_review.next_check,
        "sources": [
            {
                "source_id": row.key,
                "summary": row.summary,
                "publisher": row.publisher,
                "url": row.url,
                "locator": row.locator,
            }
            for row in reference.sources
            if row.key in capability.input_profile.source_ids and row.model_transfer_allowed
        ],
    }
