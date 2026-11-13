import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.domains.companies.models import Company

# 이름 목록 항목 (배출시설, 주생산품)
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class WasteTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=100, examples=["PP"])
    expected_monthly_volume_kg: float | None = Field(default=None, ge=0)


class WasteTypeRead(WasteTypeCreate):
    # 저장된 값을 읽을 때는 모르는 키를 무시함 (예전 generation_cycle 등)
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID


class CompanyFields(BaseModel):
    """온보딩 필수 항목. 생성은 모두 받고, 수정은 보낸 것만 바꿈."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=200, examples=["(주)가천정밀"])
    contact_email: str = Field(
        max_length=320, pattern=EMAIL_PATTERN, examples=["manager@example.com"]
    )
    industry: str = Field(min_length=1, max_length=100, examples=["화학제품 제조업"])
    site_name: str = Field(min_length=1, max_length=200, examples=["화성 2공장"])
    site_address: str = Field(
        min_length=1, max_length=500, examples=["경기도 화성시 팔탄면 산업로 128"]
    )
    site_facilities: list[Name] = Field(min_length=1, examples=[["혼합시설", "세척시설"]])


class CompanyCreate(CompanyFields):
    # 선택 항목. 보내지 않으면 빈 목록
    main_products: list[Name] = Field(default=[], examples=[["산업용 윤활유"]])
    main_waste_types: list[WasteTypeCreate] = []


class CompanyRead(BaseModel):
    id: uuid.UUID
    company_name: str
    contact_email: str
    industry: str
    site_name: str
    site_address: str
    # 반경 검색 기준점. 지오코딩 전에는 null (입력받지 않음)
    site_latitude: float | None = None
    site_longitude: float | None = None
    site_facilities: list[str]
    main_products: list[str]
    main_waste_types: list[WasteTypeRead]
    profile_version: int

    @classmethod
    def from_company(cls, company: Company) -> "CompanyRead":
        return cls(
            id=company.id,
            company_name=company.company_name,
            contact_email=company.contact_email,
            industry=company.industry,
            site_name=company.site_name,
            site_address=company.site_address,
            site_latitude=company.site_latitude,
            site_longitude=company.site_longitude,
            site_facilities=company.site_facilities,
            main_products=company.main_products,
            main_waste_types=[WasteTypeRead.model_validate(w) for w in company.main_waste_types],
            profile_version=company.profile_version,
        )


# Field names a PATCH may change. Also used as changed_fields values.
EDITABLE_FIELDS = (*CompanyFields.model_fields, "main_products", "main_waste_types")


class CompanyUpdate(BaseModel):
    """Only the fields that are sent are changed. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    profile_version: int = Field(ge=1, description="화면이 불러온 버전. 현재 버전과 다르면 409")
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320, pattern=EMAIL_PATTERN)
    industry: str | None = Field(default=None, min_length=1, max_length=100)
    site_name: str | None = Field(default=None, min_length=1, max_length=200)
    site_address: str | None = Field(default=None, min_length=1, max_length=500)
    site_facilities: list[Name] | None = Field(default=None, min_length=1)
    # 선택 항목이라 빈 목록으로 비울 수 있음
    main_products: list[Name] | None = None
    main_waste_types: list[WasteTypeCreate] | None = None

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
