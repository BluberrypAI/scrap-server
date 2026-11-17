import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FormKind = Literal["form6", "form12", "form5"]


class _In(BaseModel):
    # Unknown fields (e.g. a browser-sent waste_code) are ignored, never trusted.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class FormCompanyIn(_In):
    """Overrides for company cells. Omitted fields fall back to the company profile."""

    name: str | None = Field(None, max_length=200, description="① 상호(명칭)")
    business_registration_number: str | None = Field(None, max_length=20)
    representative_name: str | None = Field(None, max_length=100)
    address: str | None = Field(None, max_length=500)
    industrial_complex_name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    industry: str | None = Field(None, max_length=200, description="⑥ 업종")
    raw_material: str | None = Field(None, max_length=300, description="⑦ 주 원료명 및 사용량")
    main_product: str | None = Field(None, max_length=300, description="⑧ 주 생산품명 및 생산량")
    process_flow: str | None = Field(None, max_length=1000, description="⑨ 제조공정")


class FormWasteIn(_In):
    group: Literal[1, 2] | None = Field(
        None, description="제6호 ⑩ 구분: 1 비배출시설계, 2 배출시설계"
    )
    designated_kind: str | None = Field(None, max_length=100, description="제12호 ⑩ 별표 1 종류")
    container: bool = Field(False, description="지정폐기물을 용기에 담아 배출 (성질·상태 '기타')")
    tons_per_month: float | None = Field(None, ge=0)
    kg_per_month: float | None = Field(None, ge=0)
    tons_per_year: float | None = Field(None, ge=0)
    frequency: str | None = Field(None, max_length=100, description="제12호 ⑬ 배출주기")
    carrier: str | None = Field(None, max_length=200, description="'자가' 또는 운반 업소명")
    carried_tons: float | None = Field(None, ge=0)
    treatment: Literal["자가", "위탁"] | None = None
    vendor: str | None = Field(None, max_length=200)
    method: str | None = Field(None, pattern=r"^\d{4}$", description="제5호 3쪽 처리방법 번호")
    treated_tons_per_year: float | None = Field(None, ge=0)
    # The filer's own entries; they take precedence over the engine verdict and are flagged.
    waste_code: str | None = Field(
        None, pattern=r"^\d{2}-\d{2}-\d{2}$", description="분류번호(사용자가 확인해 입력)"
    )
    physical_state: Literal["solid", "liquid"] | None = Field(
        None, description="성질·상태(사용자가 고름). 비우면 문진 답을 씀"
    )


class FormSubmitIn(_In):
    """제출 칸: 작성일, 받는 기관장, 신고인(제출인) 이름, 서명 이미지(PDF에만)."""

    date: datetime.date | None = None
    recipient: str | None = Field(None, max_length=60, description="예: 화성시장, 경기도지사")
    signer_name: str | None = Field(None, max_length=60, description="비우면 대표자 성명")
    # data:image/png;base64,... drawn by the signer in the browser. Never stored.
    signature_png: str | None = Field(None, max_length=400_000)
    signer_confirmed: bool = Field(
        False, description="신고인 본인(또는 위임받은 사람)이 직접 서명함"
    )


class LegalFormIn(_In):
    company: FormCompanyIn = FormCompanyIn()
    waste: FormWasteIn = FormWasteIn()
    submit: FormSubmitIn = FormSubmitIn()


class FormEditRead(BaseModel):
    slot: str = Field(description="칸 번호.칸 안 순번. 미리보기 위치 자료의 키")
    cell: int
    op: Literal["append", "set", "sub", "sign"]
    place: Literal["at"] | None = Field(
        None, description="at: 측정한 위치에 그대로 씀(줄 다시 그리기 없음)"
    )
    show: str = Field(description="그 칸에 보이는 글자")
    # sub only: the line text matching `pattern` is replaced by before + show + after.
    pattern: str | None = None
    before: str | None = None
    after: str | None = None


class LegalFormPreviewRead(BaseModel):
    kind: FormKind
    title: str
    filename: str
    edits: list[FormEditRead]
    warnings: list[str]
    problem: str | None = Field(None, description="입력이 서식 규칙에 맞지 않을 때 그 이유")
