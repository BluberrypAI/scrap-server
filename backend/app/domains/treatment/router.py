from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.transport.shared import recipient_for
from app.domains.treatment.classification import (
    PROFILES,
    ClassificationHold,
    ClassifierStart,
    classifier_request,
    verified_recycling_types,
)
from app.domains.treatment.directory import project
from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.intake import (
    IntakeBatchResult,
    IntakeRequest,
    IntakeResult,
    IntakeSelection,
    build_intake_batch,
    build_intake_packet,
    review_intakes,
)
from app.domains.treatment.process import next_step, normalize_form, web_search_packet
from app.domains.treatment.reference import resolve_material
from app.domains.treatment.repository import read_reference, read_registry
from app.domains.treatment.schemas import (
    FacilitySearchRequest,
    FacilitySearchResponse,
    FacilityWebSearchRequest,
    FacilityWebSearchResponse,
    HandoffVerification,
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


async def with_classification(request):
    # This legacy endpoint accepts search context, not authenticated law provenance.
    request = request.model_copy(update={"recycling_basis": None})
    if request.classification_session_id is None or request.completed_transitions:
        return request
    types = await verified_recycling_types(
        request.classification_session_id,
        resolve_material(request.material),
        normalize_form(request.input_form),
        request.waste_code,
    )
    return request.model_copy(update={"recycling_types": types})


@router.post("/next-step", response_model=NextStepResponse)
async def next_process(request: NextStepRequest, db: DbSession):
    try:
        request = await with_classification(request)
        reference, _ = await read_reference(db)
        result = next_step(request, reference)
        simulation_sites = {}
        for option in result.options:
            for facility in option.facilities:
                key = facility.facility_key
                if request.preview_transition is None and key not in simulation_sites:
                    simulation_sites[key] = bool(await recipient_for(db, key))
                review = facility.intake_review
                facility.handoff_verification = HandoffVerification(
                    process=(
                        "public_evidence"
                        if facility.evidence_basis == "published_site_process"
                        else "unverified"
                    ),
                    intake_form=(
                        "public_example"
                        if review and review.form_evidence == "site_example"
                        else "unverified"
                    ),
                    simulation_available=simulation_sites.get(key, False),
                )
        return result
    except ClassificationHold as error:
        return NextStepResponse(
            status="review_required",
            backend="postgresql",
            waste_code=request.waste_code,
            message=str(error),
        )
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


@router.post("/intake-review", response_model=IntakeResult)
async def intake_review(request: IntakeRequest, db: DbSession, user: CurrentUser):
    try:
        request = await with_classification(request)
        reference, _ = await read_reference(db)
        packet = build_intake_packet(request, reference)
    except ClassificationHold as error:
        return IntakeResult(status="needs_evidence", next_check=str(error))
    except TreatmentError as error:
        raise translate(error) from None
    if not packet["sources"]:
        return IntakeResult(status="needs_evidence", next_check=packet["next_check"])
    await db.rollback()
    result = await review_intakes([packet], get_settings())
    return result.results[request.capability_key]


@router.post("/intake-reviews", response_model=IntakeBatchResult)
async def intake_reviews(request: IntakeSelection, db: DbSession, user: CurrentUser):
    try:
        request = await with_classification(request)
        reference, _ = await read_reference(db)
        packets = build_intake_batch(request, reference)
    except ClassificationHold:
        return IntakeBatchResult(results={})
    except TreatmentError as error:
        raise translate(error) from None
    await db.rollback()
    return await review_intakes(packets, get_settings())


@router.post("/facility-web-search", response_model=FacilityWebSearchResponse)
async def facility_web_search(request: FacilityWebSearchRequest, db: DbSession, user: CurrentUser):
    try:
        reference, _ = await read_reference(db)
        packet = web_search_packet(request, reference)
    except TreatmentError as error:
        raise translate(error) from None
    settings = get_settings()
    token = settings.scrap_intake_service_token.get_secret_value()
    if settings.ai_base_url and token:
        try:
            async with httpx.AsyncClient(timeout=65) as client:
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/treatment/facility-web-search",
                    headers={"Authorization": f"Bearer {token}"},
                    json=packet,
                )
                response.raise_for_status()
                return FacilityWebSearchResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError):
            pass
    return FacilityWebSearchResponse(status="unavailable")


def proxy_response(upstream):
    return Response(
        upstream.content, status_code=upstream.status_code, media_type="application/json"
    )


@classification_router.get("/profiles")
async def classification_profiles():
    return [
        {"profile": key, "label": row.label, "material": row.material, "input_form": row.input_form}
        for key, row in PROFILES.items()
    ]


@classification_router.post("/sessions")
async def start_session(request: ClassifierStart):
    return proxy_response(
        await classifier_request("POST", "/sessions", json=request.engine_payload())
    )


@classification_router.post("/sessions/{session_id}/answer")
async def answer_session(session_id: UUID, request: Request):
    return proxy_response(
        await classifier_request(
            "POST", f"/sessions/{session_id.hex}/answer", content=await request.body()
        )
    )


@classification_router.post("/sessions/{session_id}/undo")
async def undo_session(session_id: UUID, request: Request):
    return proxy_response(
        await classifier_request(
            "POST", f"/sessions/{session_id.hex}/undo", content=await request.body()
        )
    )
