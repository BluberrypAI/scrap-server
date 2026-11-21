import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserRead(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None
    provider: str = Field(examples=["microsoft"])
    company_id: uuid.UUID | None
    guest: bool = False


class WithdrawRequest(BaseModel):
    confirm: Literal[True] = Field(description="탈퇴 의사 확인. true만 허용")


class WithdrawRead(BaseModel):
    deletion_scheduled_at: datetime
