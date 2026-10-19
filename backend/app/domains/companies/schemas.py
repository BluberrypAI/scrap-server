import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domains.companies.models import GenerationCycle


class WasteProfileCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100, examples=["PP"])
    generation_cycle: GenerationCycle
    expected_monthly_volume_kg: float | None = Field(default=None, ge=0)


class WasteProfileRead(WasteProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=500)
    industry: str = Field(min_length=1, max_length=100)
    manager_name: str = Field(min_length=1, max_length=100)
    manager_phone: str | None = Field(default=None, max_length=50)
    waste_profiles: list[WasteProfileCreate] = []


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    industry: str
    manager_name: str
    manager_phone: str | None
    waste_profiles: list[WasteProfileRead]
