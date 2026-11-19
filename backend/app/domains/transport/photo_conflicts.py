"""User acknowledgment of a specific review, never a classification override."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import AppError, ErrorCode
from app.domains.treatment.reference import digest


class PhotoConflictResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=1)
    action: Literal["correct", "confirm"]
    condition: str | None = Field(default=None, min_length=3, max_length=1500)
    note: str = Field(min_length=10, max_length=1000)
    classification_unchanged: bool = False

    @model_validator(mode="after")
    def required_fields(self):
        if self.action == "correct" and not self.condition:
            raise ValueError("수정할 상태 설명이 필요합니다.")
        if self.action == "confirm" and not self.classification_unchanged:
            raise ValueError("재질·발생 공정이 문진 답변과 같은지 확인해 주세요.")
        if self.action == "confirm" and self.condition is not None:
            raise ValueError("설명을 바꾸려면 수정 후 재검토를 선택해 주세요.")
        return self


def review_token(lot):
    return digest(
        {
            "review": lot.review,
            "current": lot.data["current"],
            "stage": len(lot.data["completed"]),
            "company": str(lot.current_company_id),
        }
    )


def conflict_gate(lot):
    issues = []
    invalid_photos = {}
    for key, result in (lot.review or {}).get("results", {}).items():
        for photo in (result.get("lot_review") or {}).get("photo_observations", []):
            if photo.get("visibility") == "not_waste":
                invalid_photos[photo["photo_id"]] = photo
        for c in (result.get("lot_review") or {}).get("concerns", []):
            if c.get("category") == "description_conflict":
                issues.append({"capability_key": key, **c})
    record = lot.data.get("photo_conflict_resolution")
    valid = bool(
        issues
        and not invalid_photos
        and record
        and record.get("action") == "confirm"
        and record.get("review_token") == review_token(lot)
    )
    return {
        "issues": issues,
        "blocked": bool(invalid_photos) or (bool(issues) and not valid),
        "invalid_photos": list(invalid_photos.values()),
        "resolution": record if valid else None,
    }


def resolve_conflict(lot, cid, body):
    gate = conflict_gate(lot)
    if gate["invalid_photos"]:
        raise AppError(
            409,
            ErrorCode.WORKFLOW_CONFLICT,
            "폐기물과 무관한 사진을 실제 물량 사진으로 교체하고 다시 검토해 주세요.",
        )
    if not lot.review or not gate["issues"]:
        raise AppError(
            409, ErrorCode.WORKFLOW_CONFLICT, "현재 검토에서 확인할 사진·설명 불일치가 없습니다."
        )
    data = deepcopy(lot.data)
    record = {
        "action": body.action,
        "note": body.note,
        "classification_unchanged": body.classification_unchanged,
        "company_id": str(cid),
        "at": datetime.now(UTC).isoformat(),
        "review_token": review_token(lot),
        "issues": gate["issues"],
        "previous_condition": data["current"]["condition"],
    }
    if body.action == "correct":
        if body.condition == data["current"]["condition"]:
            raise AppError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "상태 설명을 수정하거나 기존 설명 확인을 선택해 주세요.",
            )
        data["current"]["condition"] = body.condition
        record["corrected_condition"] = body.condition
        lot.review = None
    data["photo_conflict_resolution"] = record
    lot.data = data
    return record
