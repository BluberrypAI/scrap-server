"""법정 서식 작성본 API. 저장·발송 없이 미리보기 목록과 HWPX 파일만 돌려줌.

spec: docs/specs/legal-forms.md
"""

from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Response, status

from app.core.errors import AppError, ErrorCode, NotFoundError
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service as company_service
from app.domains.diagnosis.client import Engine
from app.domains.legal_forms import pdf, service
from app.domains.legal_forms.hwpx import TemplateMismatchError
from app.domains.legal_forms.schemas import (
    FormEditRead,
    FormKind,
    LegalFormIn,
    LegalFormPreviewRead,
)

router = APIRouter(prefix="/diagnosis", tags=["legal-forms"])

CaseId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
NO_STORE = {"Cache-Control": "no-store"}
HWPX_TYPE = "application/hwp+zip"
PDF_TYPE = "application/pdf"
FileFormat = Literal["hwpx", "pdf"]


async def _prepare(
    kind: FormKind, case_id: str, body: LegalFormIn, user: Any, db: Any, engine: Any
) -> tuple[list[service.Edit], service.Verdict]:
    company = await company_service.get_company_by_user(db, user.id)
    if company is None:
        raise NotFoundError("등록된 기업이 없음")
    company_id = str(company.id)
    # Read profile values before releasing the DB transaction (rollback expires them).
    form_company = service.company_from(company, body.company)
    await db.rollback()
    # The engine only returns cases of this company (X-Company-Id gate).
    detail = (await engine.request("GET", f"/cases/{case_id}", company_id)).body
    handoff = detail.get("handoff") if isinstance(detail, dict) else None
    confirmed = (detail.get("case") or {}).get("status") == "CODE_CONFIRMED" if handoff else False
    if (
        not confirmed
        or handoff.get("contract") != "diagnosis-handoff-v1"
        or handoff.get("case_id") != case_id
    ):
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CASE_NOT_CONFIRMED,
            "문진 결과를 확정한 건만 서식을 만들 수 있음",
        )
    verdict = service.verdict_from(handoff, body.waste)
    edits = service.form_edits(kind, verdict, form_company, body.waste, body.submit)
    return edits, verdict


def _submit_notes(kind: FormKind, body: LegalFormIn) -> list[str]:
    notes = ["④ 생년월일은 받은 파일에 직접 적어 주세요."]
    if kind == "form5":
        return [*notes, "제5호의 날짜·서명은 처리 업체(수탁자)가 적습니다."]
    if body.submit.signature_png:
        notes.append(
            "서명·날인 이미지가 한글 파일과 PDF에 들어갑니다. 기관에 따라 직접 서명·날인을 "
            "요구할 수 있으니 제출 전에 확인해 주세요."
        )
    else:
        notes.append("서명이 없으면 받은 파일을 인쇄해 서명하거나 도장을 찍어 주세요.")
    return notes


def _invalid(error: Exception) -> AppError:
    return AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_ERROR, str(error))


@router.post(
    "/cases/{case_id}/legal-forms/{kind}/preview",
    response_model=LegalFormPreviewRead,
    summary="법정 서식 칸별 값 미리보기 (저장하지 않음)",
)
async def preview_legal_form(
    case_id: CaseId,
    kind: FormKind,
    body: LegalFormIn,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    engine: Engine,
) -> LegalFormPreviewRead:
    response.headers.update(NO_STORE)
    title, filename = service.TITLES[kind]
    try:
        edits, verdict = await _prepare(kind, case_id, body, user, db, engine)
    except service.FormInputError as error:
        return LegalFormPreviewRead(
            kind=kind, title=title, filename=filename, edits=[], warnings=[], problem=str(error)
        )
    # A signature problem blocks the download only; the preview keeps showing the values.
    problem = None
    try:
        service.signature_bytes(kind, body.submit)
    except service.FormInputError as error:
        problem = str(error)
    return LegalFormPreviewRead(
        problem=problem,
        kind=kind,
        title=title,
        filename=filename,
        edits=[
            FormEditRead(
                slot=e.slot,
                cell=e.cell,
                op=e.op,  # type: ignore[arg-type]
                show=e.show,
                place=e.place,  # type: ignore[arg-type]
                **(
                    {"pattern": e.pattern, "before": e.before, "after": e.after}
                    if e.op == "sub"
                    else {}
                ),
            )
            for e in edits
        ],
        warnings=[*verdict.warnings, *_submit_notes(kind, body)],
    )


@router.post(
    "/cases/{case_id}/legal-forms/{kind}",
    summary="법정 서식 작성본 받기: 한글(HWPX) 또는 PDF (저장·제출하지 않음)",
    response_class=Response,
    responses={200: {"content": {HWPX_TYPE: {}, PDF_TYPE: {}}}},
)
async def download_legal_form(
    case_id: CaseId,
    kind: FormKind,
    body: LegalFormIn,
    user: CurrentUser,
    db: DbSession,
    engine: Engine,
    file_format: Annotated[FileFormat, Query(alias="format")] = "hwpx",
) -> Response:
    try:
        edits, _ = await _prepare(kind, case_id, body, user, db, engine)
        sign = service.signature_bytes(kind, body.submit)
        mark_type = body.submit.mark_type
        content = (
            pdf.form_pdf(kind, edits, sign, mark_type)
            if file_format == "pdf"
            else service.form_hwpx(kind, edits, signature=sign, mark_type=mark_type)
        )
    except service.FormInputError as error:
        raise _invalid(error) from None
    except (TemplateMismatchError, pdf.LayoutMissingError) as error:
        raise AppError(
            status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_ERROR, str(error)
        ) from None
    filename = service.TITLES[kind][1].removesuffix(".hwpx") + f".{file_format}"
    return Response(
        content,
        media_type=PDF_TYPE if file_format == "pdf" else HWPX_TYPE,
        headers={
            **NO_STORE,
            "Content-Disposition": (
                f"attachment; filename=\"{kind}.{file_format}\"; filename*=UTF-8''{quote(filename)}"
            ),
        },
    )
