import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.domains.companies.models import Company, GenerationCycle


class WasteProfileCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100, examples=["PP"])
    generation_cycle: GenerationCycle
    expected_monthly_volume_kg: float | None = Field(default=None, ge=0)


class WasteProfileRead(WasteProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["김담당"])
    phone: str | None = Field(default=None, max_length=50, examples=["031-123-4567"])
    email: str | None = Field(default=None, max_length=320)


class CompanyCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    business_registration_no: str = Field(
        description="숫자 10자리. 하이픈 허용, 숫자만 저장", examples=["123-45-67890"]
    )
    representative_name: str = Field(min_length=1, max_length=100)
    industry: str = Field(min_length=1, max_length=100)
    head_office_address: str = Field(min_length=1, max_length=500)
    contact: Contact
    main_waste_types: list[WasteProfileCreate] = []

    @field_validator("business_registration_no")
    @classmethod
    def _normalize_brn(cls, value: str) -> str:
        digits = value.replace("-", "")
        if not re.fullmatch(r"\d{10}", digits):
            raise ValueError("사업자등록번호는 숫자 10자리여야 함")
        return digits


class CompanyRead(BaseModel):
    id: uuid.UUID
    company_name: str
    business_registration_no: str
    representative_name: str
    industry: str
    head_office_address: str
    contact: Contact
    main_waste_types: list[WasteProfileRead]
    profile_version: int

    @classmethod
    def from_company(cls, company: Company) -> "CompanyRead":
        return cls(
            id=company.id,
            company_name=company.company_name,
            business_registration_no=company.business_registration_no,
            representative_name=company.representative_name,
            industry=company.industry,
            head_office_address=company.head_office_address,
            contact=Contact(
                name=company.contact_name,
                phone=company.contact_phone,
                email=company.contact_email,
            ),
            main_waste_types=[WasteProfileRead.model_validate(w) for w in company.waste_profiles],
            profile_version=company.profile_version,
        )


# Field names a PATCH may change. Also used as changed_fields values.
EDITABLE_FIELDS = ("industry", "head_office_address", "contact", "main_waste_types")


class CompanyUpdate(BaseModel):
    """Only the fields that are sent are changed. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    profile_version: int = Field(ge=1, description="화면이 불러온 버전. 현재 버전과 다르면 409")
    industry: str | None = Field(default=None, min_length=1, max_length=100)
    head_office_address: str | None = Field(default=None, min_length=1, max_length=500)
    contact: Contact | None = None
    main_waste_types: list[WasteProfileCreate] | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = [f for f in EDITABLE_FIELDS if f in data and data[f] is None]
            if nulls:
                raise ValueError(f"null로 바꿀 수 없음: {', '.join(nulls)}")
        return data


class CompanyUpdateResult(BaseModel):
    profile_version: int
    changed_fields: list[str]


class CompanyHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_version: int
    # Read from the row's created_at; FastAPI re-validates the dumped "changed_at" too.
    changed_at: datetime = Field(validation_alias=AliasChoices("changed_at", "created_at"))
    changed_fields: list[str]

    @field_validator("changed_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite drops the offset; stored values are UTC (CURRENT_TIMESTAMP).
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class PagingInfo(BaseModel):
    """Paging block in the API spec's camelCase format."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    current_page_number: int
    page_size: int
    element_count: int = Field(description="전체 항목 수")
    total_page_count: int
    is_last_page: bool
    is_empty: bool


class CompanyHistoryPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[CompanyHistoryItem]
    paging_info: PagingInfo = Field(alias="pagingInfo")
