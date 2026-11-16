"""문진 API: 로그인한 기업의 요청을 엔진 /internal/v1로 중계함.

엔진 경로와 1:1이고 응답 본문은 엔진 것을 그대로 돌려줌.
spec: docs/specs/diagnosis-engine-integration.md
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ErrorCode, NotFoundError
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service as company_service
from app.domains.diagnosis.client import Engine, EngineClient
from app.domains.diagnosis.schemas import (
    ApplyIn,
    CaseCreateIn,
    ConfirmIn,
    MessageIn,
    ReopenIn,
    RevokeIn,
    TreatmentContextRead,
    TreatmentSelectionIn,
)
from app.domains.diagnosis.treatment import treatment_context
from app.domains.treatment.errors import TreatmentError
from app.domains.users.models import User

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])

# 엔진 기본 상한은 10MB. server는 메모리 보호용으로 더 큰 값에서 먼저 끊음
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


async def _company_id(user: CurrentUser, db: DbSession) -> str:
    company = await company_service.get_company_by_user(db, user.id)
    if company is None:
        raise NotFoundError("등록된 기업이 없음")
    return str(company.id)


CompanyId = Annotated[str, Depends(_company_id)]
# 엔진 ID 형식만 받음 (경로 조작 방지)
_ID = r"^[A-Za-z0-9_-]{1,64}$"
CaseId = Annotated[str, Path(pattern=_ID)]
DocumentId = Annotated[str, Path(pattern=_ID)]


async def _forward(
    engine: EngineClient,
    company_id: str,
    method: str,
    path: str,
    **kwargs: Any,
) -> JSONResponse:
    res = await engine.request(method, path, company_id, **kwargs)
    return JSONResponse(res.body, status_code=res.status_code)


def _body(model: Any) -> dict[str, Any]:
    return model.model_dump(exclude_none=True)


async def _file_part(file: UploadFile, facts: str | None) -> dict[str, Any]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise AppError(
            status.HTTP_413_CONTENT_TOO_LARGE, ErrorCode.FILE_TOO_LARGE, "파일이 너무 큼"
        )
    files = {
        "file": (
            file.filename or "document",
            content,
            file.content_type or "application/octet-stream",
        )
    }
    return {"files": files, "data": {"facts": facts} if facts else None}


@router.post("/cases", status_code=status.HTTP_201_CREATED, summary="문진 건 만들기 + 첫 질문")
async def create_case(body: CaseCreateIn, company_id: CompanyId, engine: Engine) -> JSONResponse:
    return await _forward(engine, company_id, "POST", "/cases", json=_body(body))


@router.get("/cases", summary="내 기업의 문진 건 목록")
async def list_cases(
    company_id: CompanyId,
    engine: Engine,
    status_: Annotated[str | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    params = {"status": status_, "page": page, "size": size}
    return await _forward(engine, company_id, "GET", "/cases", params=params)


@router.get("/catalog/facts", summary="질문 항목·선택지 목록")
async def catalog_facts(company_id: CompanyId, engine: Engine) -> JSONResponse:
    return await _forward(engine, company_id, "GET", "/catalog/facts")


@router.get("/cases/{case_id}", summary="건 상세 (판정, 대화, 서류, 인계 객체)")
async def get_case(case_id: CaseId, company_id: CompanyId, engine: Engine) -> JSONResponse:
    return await _forward(engine, company_id, "GET", f"/cases/{case_id}")


@router.post("/cases/{case_id}/messages", summary="문진 답변 한 번 (말 또는 버튼)")
async def send_message(
    case_id: CaseId, body: MessageIn, company_id: CompanyId, engine: Engine
) -> JSONResponse:
    path = f"/cases/{case_id}/diagnosis/messages"
    return await _forward(engine, company_id, "POST", path, json=_body(body))


@router.post(
    "/cases/{case_id}/documents",
    status_code=status.HTTP_201_CREATED,
    summary="서류 업로드 (값은 검수 대기로만 저장)",
)
async def upload_document(
    case_id: CaseId,
    company_id: CompanyId,
    engine: Engine,
    file: Annotated[UploadFile, File()],
    facts: Annotated[
        str | None, Form(description='JSON 문자열, 예: {"oil_content_pct": 2}')
    ] = None,
) -> JSONResponse:
    parts = await _file_part(file, facts)
    return await _forward(engine, company_id, "POST", f"/cases/{case_id}/documents", **parts)


@router.post(
    "/cases/{case_id}/documents/{document_id}/versions",
    status_code=status.HTTP_201_CREATED,
    summary="서류 파일 교체 (새 버전)",
)
async def replace_document(
    case_id: CaseId,
    document_id: DocumentId,
    company_id: CompanyId,
    engine: Engine,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    parts = await _file_part(file, facts)
    path = f"/cases/{case_id}/documents/{document_id}/versions"
    return await _forward(engine, company_id, "POST", path, **parts)


@router.post(
    "/cases/{case_id}/documents/{document_id}/values/apply",
    summary="검수한 서류 값을 판정에 반영",
)
async def apply_values(
    case_id: CaseId,
    document_id: DocumentId,
    body: ApplyIn,
    user: CurrentUser,
    company_id: CompanyId,
    engine: Engine,
) -> JSONResponse:
    payload = {"values": [_reviewed(v.model_dump(exclude_none=True), user) for v in body.values]}
    path = f"/cases/{case_id}/documents/{document_id}/values/apply"
    return await _forward(engine, company_id, "POST", path, json=payload)


def _reviewed(value: dict[str, Any], user: User) -> dict[str, Any]:
    # 검수자와 검수 시각은 server가 채움 (브라우저 값은 받지 않음)
    return {**value, "reviewer": str(user.id), "reviewed_at": datetime.now(UTC).isoformat()}


@router.post("/cases/{case_id}/documents/{document_id}/revoke", summary="서류 효력 해제")
async def revoke_document(
    case_id: CaseId, document_id: DocumentId, body: RevokeIn, company_id: CompanyId, engine: Engine
) -> JSONResponse:
    path = f"/cases/{case_id}/documents/{document_id}/revoke"
    return await _forward(engine, company_id, "POST", path, json=_body(body))


@router.post("/cases/{case_id}/confirm", summary="판정 확정 + 인계 객체(handoff)")
async def confirm_case(
    case_id: CaseId, company_id: CompanyId, engine: Engine, body: ConfirmIn | None = None
) -> JSONResponse:
    payload = _body(body) if body else {}
    return await _forward(engine, company_id, "POST", f"/cases/{case_id}/confirm", json=payload)


@router.post("/cases/{case_id}/reopen", summary="확정 건 다시 열기")
async def reopen_case(
    case_id: CaseId, company_id: CompanyId, engine: Engine, body: ReopenIn | None = None
) -> JSONResponse:
    payload = _body(body) if body else {}
    return await _forward(engine, company_id, "POST", f"/cases/{case_id}/reopen", json=payload)


@router.post("/cases/{case_id}/rebase", summary="바뀐 규칙으로 다시 평가 (KB_CHANGED 후)")
async def rebase_case(case_id: CaseId, company_id: CompanyId, engine: Engine) -> JSONResponse:
    return await _forward(engine, company_id, "POST", f"/cases/{case_id}/rebase")


@router.get("/cases/{case_id}/trace", summary="판정 근거 추적")
async def get_trace(case_id: CaseId, company_id: CompanyId, engine: Engine) -> JSONResponse:
    return await _forward(engine, company_id, "GET", f"/cases/{case_id}/trace")


@router.post("/cases/{case_id}/treatment/next-step", response_model=TreatmentContextRead)
async def diagnosis_next_step(
    case_id: CaseId,
    body: TreatmentSelectionIn,
    company_id: CompanyId,
    db: DbSession,
    engine: Engine,
):
    try:
        return await treatment_context(engine, db, company_id, case_id, body)
    except TreatmentError as error:
        raise AppError(503, ErrorCode.ENGINE_UNAVAILABLE, str(error)) from None


@router.post("/cases/{case_id}/treatment/intake-reviews", response_model=TreatmentContextRead)
async def diagnosis_intake_reviews(
    case_id: CaseId,
    body: TreatmentSelectionIn,
    company_id: CompanyId,
    db: DbSession,
    engine: Engine,
):
    try:
        return await treatment_context(engine, db, company_id, case_id, body, audit=True)
    except TreatmentError as error:
        raise AppError(503, ErrorCode.ENGINE_UNAVAILABLE, str(error)) from None
