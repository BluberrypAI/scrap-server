import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


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
