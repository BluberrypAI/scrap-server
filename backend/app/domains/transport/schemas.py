import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class SharedCaseUpdate(BaseModel):
    revision: int = Field(ge=0)
    snapshot: dict

    @field_validator("snapshot")
    @classmethod
    def check_shape(cls, snapshot):
        if len(json.dumps(snapshot, ensure_ascii=False).encode()) > 65536:
            raise ValueError("공유 처리 기록이 너무 큽니다.")
        if not isinstance(snapshot.get("completed"), list) or not isinstance(
            snapshot.get("input"), dict
        ):
            raise ValueError("공유 처리 기록 형식이 올바르지 않습니다.")
        if snapshot.get("pending") is not None and not isinstance(snapshot["pending"], dict):
            raise ValueError("공유 처리 기록 형식이 올바르지 않습니다.")
        return snapshot


class TransportCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    lot: str = Field(min_length=1, max_length=160)
    origin: str = Field(min_length=1, max_length=160)
    destination: str = Field(min_length=1, max_length=160)
    destination_key: str | None = Field(default=None, max_length=160)
    shared_case_id: uuid.UUID | None = None
    case_update: SharedCaseUpdate | None = None


class TransportEvent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    role: Literal["driver", "recipient"]
    actor: str = Field(min_length=1, max_length=80)


class TransportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    lot: str
    origin: str
    destination: str
    pickup_actor: str | None
    pickup_at: datetime | None
    receipt_actor: str | None
    receipt_at: datetime | None
    shared_case_id: uuid.UUID | None
    account_required: bool = False

    @field_serializer("pickup_at", "receipt_at")
    def utc_time(self, value: datetime | None) -> str | None:
        return (
            value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat() if value else None
        )


class PolicyData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    accepting_inquiries: bool = True
    materials_forms: str = Field(min_length=3, max_length=600)
    contamination: str = Field(min_length=3, max_length=600)
    packaging: str = Field(min_length=3, max_length=600)
    schedule: str = Field(min_length=3, max_length=600)
    min_mass_kg: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    max_mass_kg: float | None = Field(default=None, gt=0, le=1e9, allow_inf_nan=False)
    required_checks: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def valid_limits(self):
        if self.min_mass_kg is not None and self.max_mass_kg is not None:
            if self.min_mass_kg > self.max_mass_kg:
                raise ValueError("최소 물량은 최대 물량보다 클 수 없습니다.")
        if any(not 3 <= len(s.strip()) <= 600 for s in self.required_checks):
            raise ValueError("각 확인 조건은 3~600자여야 합니다.")
        self.required_checks = list(dict.fromkeys(s.strip() for s in self.required_checks))
        return self


class PolicyWrite(BaseModel):
    facility_key: str = Field(max_length=100)
    expected_version: int = Field(ge=0)
    policy: PolicyData


class SupplierPolicyRead(BaseModel):
    version: int
    company_id: str
    updated_at: str
    basis: Literal["supplier_declared_not_certified"]
    policy: PolicyData


class SupplierSiteRead(BaseModel):
    facility_key: str
    label: str
    synthetic: bool
    current: SupplierPolicyRead | None
