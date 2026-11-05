from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.treatment.directory import project
from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.intake import IntakeRequest, build_intake_packet
from app.domains.treatment.process import next_step
from app.domains.treatment.repository import read_reference, read_registry
from app.domains.treatment.schemas import (
    FacilitySearchRequest,
    FacilitySearchResponse,
    NextStepRequest,
    NextStepResponse,
)

router = APIRouter(prefix="/api/treatment", tags=["treatment"])
classification_router = APIRouter(prefix="/api/classification", tags=["classification"])


def translate(error):
    if error.code in {"invalid-progress", "stale-cursor"}:
        return AppError(409, ErrorCode.INVALID_FILTER, str(error))
    if error.code in {"invalid-cursor", "invalid-transition", "invalid-capability", "invalid-code"}:
        return AppError(400, ErrorCode.INVALID_FILTER, str(error))
    return AppError(503, ErrorCode.ENGINE_UNAVAILABLE, str(error))


@router.post("/next-step", response_model=NextStepResponse)
async def next_process(request: NextStepRequest, db: DbSession):
    try:
        reference, _ = await read_reference(db)
        return next_step(request, reference)
    except TreatmentError as error:
        raise translate(error) from None


@router.post("/facility-candidates", response_model=FacilitySearchResponse)
async def facility_candidates(request: FacilitySearchRequest, db: DbSession):
    try:
        reference, checksum = await read_reference(db) if request.transition_key else (None, None)
        registry = await read_registry(
            db, recycling_only=request.transition_key is not None, waste_code=request.waste_code
        )
        return project(
            reference,
            registry,
            request,
            generation=checksum or "code-only",
            fingerprint=checksum,
            namespace="scrap-server",
            backend="postgresql",
        )
    except TreatmentError as error:
        raise translate(error) from None


@router.post("/intake-review")
async def intake_review(request: IntakeRequest, db: DbSession, user: CurrentUser):
    try:
        reference, _ = await read_reference(db)
        packet = build_intake_packet(request, reference)
    except TreatmentError as error:
        raise translate(error) from None
    fallback = {
        "status": "model_unavailable",
        "finding": "insufficient",
        "next_check": packet["next_check"],
        "source": None,
        "quote": None,
        "dispatch_approved": False,
    }
    if not packet["sources"]:
        return {**fallback, "status": "needs_evidence"}
    settings = get_settings()
    token = settings.scrap_intake_service_token.get_secret_value()
    if settings.ai_base_url and token:
        try:
            async with httpx.AsyncClient(timeout=40) as client:
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/treatment/intake-review",
                    headers={"Authorization": f"Bearer {token}"},
                    json=packet,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            pass
    return fallback


async def classification_call(request: Request, path: str):
    settings = get_settings()
    if not settings.classification_base_url:
        raise AppError(503, ErrorCode.ENGINE_UNAVAILABLE, "문진 엔진 주소를 확인해 주세요.")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            upstream = await client.request(
                request.method,
                f"{settings.classification_base_url.rstrip('/')}/api/classification{path}",
                content=await request.body(),
                headers={"content-type": "application/json"},
            )
    except httpx.HTTPError:
        raise AppError(
            503, ErrorCode.ENGINE_UNAVAILABLE, "문진 엔진에 연결하지 못했어요."
        ) from None
    return Response(
        upstream.content, status_code=upstream.status_code, media_type="application/json"
    )


@classification_router.post("/sessions")
async def start_session(request: Request):
    return await classification_call(request, "/sessions")


@classification_router.post("/sessions/{session_id}/answer")
async def answer_session(session_id: UUID, request: Request):
    return await classification_call(request, f"/sessions/{session_id.hex}/answer")


@classification_router.post("/sessions/{session_id}/undo")
async def undo_session(session_id: UUID, request: Request):
    return await classification_call(request, f"/sessions/{session_id.hex}/undo")
