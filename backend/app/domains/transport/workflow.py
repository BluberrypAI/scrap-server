"""Company-owned material handoffs. Recorded observations, never browser-built history."""

import base64
import hashlib
import io
import secrets
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, File, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db.session import DbSession
from app.domains.companies.models import Company
from app.domains.diagnosis.client import Engine
from app.domains.diagnosis.router import CompanyId
from app.domains.diagnosis.schemas import TreatmentSelectionIn
from app.domains.diagnosis.treatment import treatment_context
from app.domains.transport.models import (
    WorkflowFacilityAccount,
    WorkflowLot,
    WorkflowOffer,
    WorkflowPhoto,
)
from app.domains.treatment.conditions import attach_answers, published_conditions, questionnaire
from app.domains.treatment.directory import project
from app.domains.treatment.intake import IntakeSelection, build_intake_batch, review_intakes
from app.domains.treatment.process import next_step
from app.domains.treatment.reference import digest
from app.domains.treatment.repository import read_reference, read_registry
from app.domains.treatment.schemas import FacilitySearchRequest, NextStepRequest
from app.domains.wastes.models import (
    CheckRole,
    QrFieldCheck,
    RouteStep,
    Waste,
    WasteCompletionSnapshot,
    WasteStatus,
)

router = APIRouter(prefix="/workflow", tags=["transport"])

# 문진(scrap-diagnosis)과 처리경로(scrap-route)가 함께 지원하는 재질·형태만 인계한다.
# (재질, 형태) → 참조 자료의 시작 상태
LOT_STARTS = {
    ("pp", "scrap"): "pp-scrap",
    ("pp", "shredded"): "pp-shredded",
    ("pe", "film"): "pe-scrap",
    ("aluminium", "can"): "al-used-can",
    ("pet", "bottle"): "pet-bottle",  # Only a compatible confirmed code passes treatment_context.
}
# 완료로 인정하는 실제 산출물. 파쇄품은 카탈로그 종료 표시가 있어도 완료로 보지 않는다.
FINISH_STATES = {
    "pp": {"pp-pellet", "pp-compound"},
    "pe": {"pe-pellet", "pe-compound"},
    "aluminium": {"al-sheet", "al-sheet-ingot"},
    "pet": {"pet-flake", "pet-pellet"},
}
MATERIAL_LABELS = {"pp": "PP", "pe": "PE", "aluminium": "알루미늄", "pet": "PET"}


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateLot(Body):
    diagnosis_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    input_form: Literal["scrap", "shredded", "film", "bottle", "can"]
    mass_kg: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    condition: str = Field(min_length=3, max_length=1500)


class Version(Body):
    revision: int = Field(ge=1)


class OfferIn(Version):
    capability_key: str = Field(max_length=100)


class Decision(Version):
    accept: bool
    note: str = Field(min_length=3, max_length=1000)
    scope_checked: bool = False
    intake_checked: bool = False
    resolved_condition_ids: list[str] = Field(default_factory=list, max_length=12)


class IntakeAnswers(Version):
    capability_key: str = Field(max_length=100)
    answers: dict[str, str] = Field(min_length=1, max_length=24)


class ConditionsIn(Version):
    conditions: list[str] = Field(min_length=1, max_length=12)
    note: str = Field(min_length=3, max_length=1000)


class ConditionResponses(Version):
    responses: dict[str, str] = Field(min_length=1, max_length=12)


class DirectoryIn(Version):
    transition_key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,100}$")
    cursor: str | None = Field(default=None, max_length=2048)
    page_size: int = Field(default=10, ge=1, le=50)


class DirectoryInquiry(DirectoryIn):
    listing_id: str = Field(min_length=1, max_length=100)
    answers: dict[str, str] = Field(default_factory=dict, max_length=24)


class Receipt(Version):
    token: str = Field(min_length=20, max_length=160)


class Output(Version):
    # 로트 재질의 등록 상태인지는 참조 자료로 따로 확인한다
    state_key: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    mass_kg: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    purity_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    condition: str = Field(min_length=3, max_length=1500)
    evidence: str = Field(min_length=3, max_length=300)


class Finish(Version):
    reference: str = Field(min_length=3, max_length=300)
    intended_use: str = Field(min_length=3, max_length=500)
    confirmed: bool


# 공통 오류 형식({code, message})으로 내야 화면에 이유가 그대로 보인다
_FAIL_CODES = {
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.WORKFLOW_CONFLICT,
    413: ErrorCode.FILE_TOO_LARGE,
    422: ErrorCode.VALIDATION_ERROR,
}


def fail(message, status=409, code=None):
    raise AppError(status, code or _FAIL_CODES[status], message)


async def lot_for(db, key, cid, lock=False):
    query = select(WorkflowLot).where(WorkflowLot.id == key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    lot = await db.scalar(query)
    if not lot:
        fail("해당 처리 건을 찾을 수 없습니다.", 404)
    participant = cid in {lot.owner_company_id, lot.current_company_id}
    if not participant:
        participant = await db.scalar(
            select(WorkflowOffer.id)
            .where(
                WorkflowOffer.lot_id == key,
                or_(WorkflowOffer.sender_id == cid, WorkflowOffer.recipient_id == cid),
            )
            .limit(1)
        )
    if not participant:
        fail("해당 처리 건을 찾을 수 없습니다.", 404)
    return lot


def version(lot, rev):
    if lot.revision != rev:
        fail(
            "다른 화면에서 기록이 변경됐습니다. 새로고침해 주세요.",
            code=ErrorCode.VERSION_CONFLICT,
        )


def active(lot, cid, states):
    if lot.current_company_id != cid:
        fail("현재 물량을 담당하는 기업만 처리할 수 있습니다.", 403)
    if lot.status not in states:
        fail("현재 진행 상태에서는 이 작업을 할 수 없습니다.")


def stamp(lot, action, cid, extra=None):
    data = deepcopy(lot.data)
    data.setdefault("events", []).append(
        {
            "action": action,
            "company_id": str(cid),
            "at": datetime.now(UTC).isoformat(),
            **(extra or {}),
        }
    )
    lot.data = data
    lot.revision += 1


async def view(db, lot, cid):
    ref, _ = await read_reference(db)
    material = lot.data["initial"]["material"]
    states = [s for s in ref.states if s.material == material]
    offers = list(
        await db.scalars(
            select(WorkflowOffer)
            .where(WorkflowOffer.lot_id == lot.id)
            .order_by(WorkflowOffer.created_at)
        )
    )
    companies = {lot.owner_company_id, lot.current_company_id}
    companies.update(o.recipient_id for o in offers)
    companies.update(o.sender_id for o in offers)
    names = {
        str(c.id): c.company_name
        for c in await db.scalars(select(Company).where(Company.id.in_(companies)))
    }
    photos = list(await db.scalars(select(WorkflowPhoto).where(WorkflowPhoto.lot_id == lot.id)))
    return {
        "id": str(lot.id),
        "revision": lot.revision,
        "status": lot.status,
        "owner_company_id": str(lot.owner_company_id),
        "current_company_id": str(lot.current_company_id),
        "companies": names,
        "can_manage": lot.current_company_id == cid,
        "data": lot.data,
        "review": lot.review,
        "output_states": [
            {"key": s.key, "label": s.label}
            for s in states
            if s.key in {t.output_state for t in ref.transitions}
        ],
        "terminal_states": [s.key for s in states if s.key in FINISH_STATES.get(material, set())],
        "photos": [
            {"id": str(p.id), "stage": p.stage, "url": f"/api/v1/workflow/photos/{p.id}"}
            for p in photos
        ],
        "offers": [
            {
                "id": str(o.id),
                "sender_id": str(o.sender_id),
                "recipient_id": str(o.recipient_id),
                "status": o.status,
                "data": o.data,
                "can_decide": cid == o.recipient_id and o.status in {"pending", "conditional"},
                "can_respond_conditions": cid == o.sender_id and o.status == "conditional",
                "can_receive": cid == o.recipient_id and o.status == "accepted",
                "can_issue_qr": cid == o.sender_id and o.status == "accepted",
            }
            for o in offers
        ],
    }


@router.post("/lots")
async def create_lot(body: CreateLot, company_id: CompanyId, db: DbSession, engine: Engine):
    cid = uuid.UUID(company_id)
    existing = await db.scalar(
        select(WorkflowLot).where(
            WorkflowLot.owner_company_id == cid, WorkflowLot.diagnosis_id == body.diagnosis_id
        )
    )
    if existing:
        return await view(db, existing, cid)
    ctx = await treatment_context(
        engine, db, company_id, body.diagnosis_id, TreatmentSelectionIn(input_form=body.input_form)
    )
    material = (ctx.route_input or {}).get("material")
    start = LOT_STARTS.get((material, (ctx.route_input or {}).get("input_form")))
    if ctx.status != "ready" or start is None:
        fail(
            "기업 인계는 확정된 일반 문진 중 PP 사출 잔재·파쇄품, PE 필름, "
            "알루미늄 음료캔, 분류번호가 공정 자료와 일치하는 PET병만 지원합니다."
        )
    waste = Waste(
        company_id=cid,
        name=f"{MATERIAL_LABELS[material]} 자원순환",
        status=WasteStatus.CANDIDATES,
        waste_code=ctx.handoff["waste_code"],
        category=ctx.handoff["category"],
        code_name=ctx.handoff.get("waste_name"),
        quantity_value=body.mass_kg,
        quantity_unit="kg",
        classified_at=datetime.now(UTC),
    )
    db.add(waste)
    await db.flush()
    lot = WorkflowLot(
        id=waste.id,
        owner_company_id=cid,
        current_company_id=cid,
        diagnosis_id=body.diagnosis_id,
        status="ready",
        data={
            "handoff": ctx.handoff,
            "warnings": ctx.warnings,
            "initial": ctx.route_input,
            "completed": [],
            "current": {
                "state_key": start,
                "mass_kg": body.mass_kg,
                "condition": body.condition,
                "purity_percent": None,
            },
            "events": [],
        },
    )
    db.add(lot)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        fail("이미 등록된 문진입니다. 처리 목록을 다시 열어 주세요.")
    return await view(db, lot, cid)


@router.get("/lots")
async def list_lots(company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    query = select(WorkflowLot).where(
        or_(
            WorkflowLot.owner_company_id == cid,
            WorkflowLot.current_company_id == cid,
            WorkflowLot.id.in_(
                select(WorkflowOffer.lot_id).where(
                    or_(WorkflowOffer.recipient_id == cid, WorkflowOffer.sender_id == cid)
                )
            ),
        )
    )
    lots = list(await db.scalars(query.order_by(WorkflowLot.updated_at.desc()).limit(100)))
    return [await view(db, lot, cid) for lot in lots]


@router.get("/lots/{key}")
async def get_lot(key: uuid.UUID, company_id: CompanyId, db: DbSession, response: Response):
    response.headers["Cache-Control"] = "no-store"
    cid = uuid.UUID(company_id)
    return await view(db, await lot_for(db, key, cid), cid)


@router.post("/lots/{key}/photos")
async def add_photo(
    key: uuid.UUID, company_id: CompanyId, db: DbSession, file: UploadFile = File(...)
):
    cid = uuid.UUID(company_id)
    raw = await file.read(3 * 1024 * 1024 + 1)
    if len(raw) > 3 * 1024 * 1024:
        fail("사진은 3MB 이하로 올려 주세요.", 413)
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in {"JPEG", "PNG", "WEBP"} or img.width * img.height > 16000000:
                fail("JPEG·PNG·WebP 사진(1600만 화소 이하)만 가능합니다.", 422)
            img.load()
            img.thumbnail((1600, 1600))
            encoded = io.BytesIO()
            img.convert("RGB").save(encoded, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        fail("사진 파일을 읽을 수 없습니다.", 422)
    lot = await lot_for(db, key, cid, lock=True)
    active(lot, cid, {"ready", "processed"})
    stage = len(lot.data["completed"])
    count = list(
        await db.scalars(
            select(WorkflowPhoto.id).where(
                WorkflowPhoto.lot_id == key, WorkflowPhoto.stage == stage
            )
        )
    )
    if len(count) >= 4:
        fail("단계당 사진은 4장까지 올릴 수 있습니다.")
    db.add(
        WorkflowPhoto(
            lot_id=key, company_id=cid, stage=stage, mime="image/jpeg", content=encoded.getvalue()
        )
    )
    lot.review = None
    stamp(lot, "사진 첨부", cid)
    await db.commit()
    return await view(db, lot, cid)


@router.get("/photos/{key}")
async def photo(key: uuid.UUID, company_id: CompanyId, db: DbSession):
    row = await db.get(WorkflowPhoto, key)
    if not row:
        fail("사진을 찾을 수 없습니다.", 404)
    await lot_for(db, row.lot_id, uuid.UUID(company_id))
    return Response(
        row.content,
        media_type=row.mime,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def process_request(lot):
    initial = lot.data["initial"]
    return NextStepRequest(
        waste_code=initial["waste_code"],
        material=initial["material"],
        input_form=initial["input_form"],
        completed_transitions=[s["transition_key"] for s in lot.data["completed"]],
        observed_output={
            k: lot.data["current"].get(k) for k in ("state_key", "mass_kg", "purity_percent")
        }
        if lot.data["completed"]
        else None,
    )


@router.post("/lots/{key}/candidates")
async def candidates(key: uuid.UUID, body: Version, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid)
    active(lot, cid, {"ready", "processed"})
    version(lot, body.revision)
    ref, reference_checksum = await read_reference(db)
    conditions_checksum = digest(published_conditions())
    if (
        lot.review
        and lot.review.get("version") == "lot-vision-v1"
        and lot.review.get("analysis_version") == "isolated-vision-v2"
        and lot.review.get("conditions_version") == "intake-questions-v1"
        and lot.review.get("reference_checksum") == reference_checksum
        and lot.review.get("conditions_checksum") == conditions_checksum
        and all(
            r.get("status") in {"reviewed", "needs_evidence"}
            and (r.get("lot_review") or {}).get("status") == "reviewed"
            and (r.get("lot_review") or {}).get("observation_method")
            in {"isolated_vision", "no_photo"}
            for r in lot.review.get("results", {}).values()
        )
    ):
        return await view(db, lot, cid)
    request = process_request(lot)
    current_company = await db.get(Company, cid)
    if current_company.site_latitude is not None and current_company.site_longitude is not None:
        from app.domains.treatment.schemas import Coordinates

        request.origin = Coordinates(
            latitude=current_company.site_latitude, longitude=current_company.site_longitude
        )
    result = next_step(request, ref)
    packets = build_intake_batch(
        IntakeSelection.model_validate(
            request.model_dump(exclude={"origin", "preview_transition"})
        ),
        ref,
    )
    photos = list(
        await db.scalars(
            select(WorkflowPhoto)
            .where(
                WorkflowPhoto.lot_id == key,
                WorkflowPhoto.stage == len(lot.data["completed"]),
            )
            .order_by(WorkflowPhoto.created_at, WorkflowPhoto.id)
        )
    )
    lot_context = {
        k: lot.data["current"].get(k)
        for k in ("state_key", "mass_kg", "purity_percent", "condition")
    }
    lot_context["photos"] = [
        {
            "photo_id": str(p.id),
            "data_url": "data:image/jpeg;base64," + base64.b64encode(p.content).decode("ascii"),
        }
        for p in photos
    ]
    # Candidate-specific sender answers are untrusted observations, not facility rules.
    stage_answers = lot.data.get("intake_answers", {}).get(str(len(lot.data["completed"])), {})
    for packet in packets:
        answers = stage_answers.get(packet["capability_key"], {})
        if answers:
            packet["intake_answers"] = {
                f"{k}: {v['question']}" if v.get("question") else k: v["value"]
                for k, v in answers.items()
            }
    await db.rollback()
    reviewed = await review_intakes(packets, get_settings(), lot_context=lot_context)
    lot = await lot_for(db, key, cid, lock=True)
    active(lot, cid, {"ready", "processed"})
    version(lot, body.revision)
    output = result.model_dump(mode="json")
    bindings = {b.facility_key: b for b in await db.scalars(select(WorkflowFacilityAccount))}
    for option in output["options"]:
        for f in option["facilities"]:
            binding = bindings.get(f["facility_key"])
            enabled = binding and (
                not binding.synthetic or get_settings().app_env in {"local", "test"}
            )
            target = await db.get(Company, binding.company_id) if enabled else None
            f["recipient"] = (
                {"id": str(target.id), "name": target.company_name, "synthetic": binding.synthetic}
                if target and target.id != cid
                else None
            )
            f["intake_conditions"] = attach_answers(
                questionnaire(
                    ref,
                    f["facility_key"],
                    request.material,
                    ai_review=reviewed.results[f["capability_key"]].model_dump(),
                ),
                stage_answers.get(f["capability_key"], {}),
            )
    lot.review = {
        "version": "lot-vision-v1",
        "analysis_version": "isolated-vision-v2",
        "conditions_version": "intake-questions-v1",
        "reference_checksum": reference_checksum,
        "conditions_checksum": conditions_checksum,
        "next_step": output,
        "results": reviewed.model_dump()["results"],
        "at": datetime.now(UTC).isoformat(),
    }
    await db.commit()
    return await view(db, lot, cid)


@router.post("/lots/{key}/intake-answers")
async def intake_answers(key: uuid.UUID, body: IntakeAnswers, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid, lock=True)
    active(lot, cid, {"ready", "processed"})
    version(lot, body.revision)
    review = deepcopy(lot.review or {})
    fs = [
        f
        for o in review.get("next_step", {}).get("options", [])
        for f in o["facilities"]
        if f["capability_key"] == body.capability_key
    ]
    if len(fs) != 1 or "intake_conditions" not in fs[0]:
        fail("현재 업체 후보를 먼저 검토해 주세요.")
    form = fs[0]["intake_conditions"]
    questions = {q["key"]: q for q in form["questions"]}
    if any(
        k not in questions
        or not isinstance(v, str)
        or not 1 <= len(v.strip()) <= 600
        or (questions[k]["choices"] and v not in questions[k]["choices"])
        for k, v in body.answers.items()
    ):
        fail("현재 질문에 맞는 답변을 입력해 주세요.", 422)
    data = deepcopy(lot.data)
    saved = (
        data.setdefault("intake_answers", {})
        .setdefault(str(len(data["completed"])), {})
        .setdefault(body.capability_key, {})
    )
    # Retain only the current questionnaire, keeping the AI request bounded.
    for obsolete in set(saved) - set(questions):
        del saved[obsolete]
    for k, v in body.answers.items():
        saved[k] = {
            "value": v.strip(),
            "question": questions[k]["label"],
            "company_id": str(cid),
            "at": datetime.now(UTC).isoformat(),
            "basis": "sender_declared",
        }
    lot.data = data
    # Editing answers invalidates AI judgement, never silently keeps a positive old result.
    lot.review = None
    stamp(lot, "업체별 반입 질문 답변", cid, {"capability_key": body.capability_key})
    await db.commit()
    return await view(db, lot, cid)


@router.post("/lots/{key}/directory")
async def directory(key: uuid.UUID, body: DirectoryIn, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid)
    active(lot, cid, {"ready", "processed"})
    version(lot, body.revision)
    ref, checksum = await read_reference(db)
    result = next_step(process_request(lot), ref)
    if body.transition_key not in {o.transition_key for o in result.options}:
        fail("현재 단계에서 가능한 공정만 조회할 수 있습니다.", 422)
    company = await db.get(Company, cid)
    # B's output is a new observation: never reuse A's original waste code as a permit filter.
    request = FacilitySearchRequest(
        transition_key=body.transition_key,
        waste_code=None if lot.data["completed"] else lot.data["initial"]["waste_code"],
        origin_latitude=company.site_latitude,
        origin_longitude=company.site_longitude,
        page_size=body.page_size,
        cursor=body.cursor,
    )
    registry = await read_registry(db, recycling_only=True, waste_code=None)
    from app.domains.treatment.errors import TreatmentError

    try:
        found = project(
            ref,
            registry,
            request,
            generation=checksum,
            fingerprint=checksum,
            namespace=f"lot-{key}-{lot.revision}",
            backend="postgresql",
        )
    except TreatmentError as error:
        fail(str(error))
    for row in found.registry_candidates:
        packet = row["research_packet"]
        packet["intake_conditions"] = questionnaire(
            ref, row["listing_id"], lot.data["initial"]["material"], directory_record=packet
        )
        packet["can_request_intake"] = False
        packet["next_action"] = (
            "사업장별 공정·반입규격 근거와 확인된 수신계정 연결 후 AI 검토가 필요합니다."
        )
    return found


@router.post("/lots/{key}/directory-inquiries")
async def save_directory_inquiry(
    key: uuid.UUID, body: DirectoryInquiry, company_id: CompanyId, db: DbSession
):
    page = await directory(
        key, DirectoryIn(**body.model_dump(exclude={"listing_id", "answers"})), company_id, db
    )
    row = next((r for r in page.registry_candidates if r["listing_id"] == body.listing_id), None)
    if row is None:
        fail("현재 명부 조회 결과에 있는 업체를 선택해 주세요.", 422)
    form = row["research_packet"]["intake_conditions"]
    questions = {q["key"]: q for q in form["questions"]}
    if any(
        k not in questions
        or not 1 <= len(v.strip()) <= 600
        or (questions[k]["choices"] and v not in questions[k]["choices"])
        for k, v in body.answers.items()
    ):
        fail("명부 후보의 질문에 맞게 답변해 주세요.", 422)
    # Querying above populated the identity map. Reload under the row lock so
    # a concurrent edit cannot pass using an already-loaded stale revision.
    await db.rollback()
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid, lock=True)
    version(lot, body.revision)
    active(lot, cid, {"ready", "processed"})
    data = deepcopy(lot.data)
    stage = str(len(data["completed"]))
    entries = data.setdefault("directory_inquiries", {}).setdefault(stage, {})
    inquiry_key = body.transition_key + ":" + body.listing_id
    if inquiry_key not in entries and len(entries) >= 100:
        fail("한 단계에 저장할 수 있는 조사 업체는 100곳입니다.", 422)
    answers = (entries.get(inquiry_key, {}).get("intake_conditions") or {}).get("answers", {})
    for k, v in body.answers.items():
        answers[k] = {
            "value": v.strip(),
            "company_id": str(cid),
            "at": datetime.now(UTC).isoformat(),
            "basis": "sender_declared",
        }
    entries[inquiry_key] = {
        "transition_key": body.transition_key,
        "listing_id": body.listing_id,
        "name": row["research_packet"]["name"],
        "address": row["research_packet"]["address"],
        "source_url": row["research_packet"]["source_url"],
        "status": "evidence_and_account_required",
        "source_sha256": row["research_packet"]["source_sha256"],
        "intake_conditions": attach_answers(form, answers),
        "dispatch_approved": False,
    }
    lot.data = data
    stamp(lot, "명부 업체 확인 목록 저장", cid, {"listing_id": body.listing_id})
    await db.commit()
    return await view(db, lot, cid)


@router.post("/lots/{key}/offers")
async def offer(key: uuid.UUID, body: OfferIn, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid, lock=True)
    active(lot, cid, {"ready", "processed"})
    version(lot, body.revision)
    review = lot.review or {}
    _, reference_checksum = await read_reference(db)
    if review.get("reference_checksum") != reference_checksum or review.get(
        "conditions_checksum"
    ) != digest(published_conditions()):
        fail("공정·반입조건 자료가 바뀌었거나 구버전 검토입니다. 업체 검토를 다시 실행해 주세요.")
    found = [
        (o, f)
        for o in review.get("next_step", {}).get("options", [])
        for f in o["facilities"]
        if f["capability_key"] == body.capability_key
    ]
    if len(found) != 1:
        fail("현재 물량의 업체 검토를 먼저 실행해 주세요.")
    option, facility = found[0]
    check = review["results"].get(body.capability_key, {})
    if (
        check.get("status") not in {"reviewed", "needs_evidence"}
        or check.get("finding") == "restriction_mentioned"
        or review.get("version") != "lot-vision-v1"
        or review.get("analysis_version") != "isolated-vision-v2"
        or (check.get("lot_review") or {}).get("status") != "reviewed"
        or (check.get("lot_review") or {}).get("observation_method")
        not in {"isolated_vision", "no_photo"}
    ):
        fail("상태·사진 AI 검토 미완료 또는 제한 근거가 있어 요청을 보류합니다.")
    binding = await db.get(WorkflowFacilityAccount, facility["facility_key"])
    if (
        not binding
        or binding.company_id == cid
        or (binding.synthetic and get_settings().app_env not in {"local", "test"})
    ):
        fail("이 업체의 확인된 수신 계정이 연결되지 않았습니다.")
    photos = list(
        await db.scalars(
            select(WorkflowPhoto.id).where(
                WorkflowPhoto.lot_id == key, WorkflowPhoto.stage == len(lot.data["completed"])
            )
        )
    )
    row = WorkflowOffer(
        lot_id=key,
        sender_id=cid,
        recipient_id=binding.company_id,
        data={
            "current": deepcopy(lot.data["current"]),
            "option": option,
            "facility": facility,
            "ai_review": check,
            "intake_conditions": deepcopy(facility.get("intake_conditions")),
            "synthetic": binding.synthetic,
            "photo_ids": [str(p) for p in photos],
        },
    )
    db.add(row)
    lot.status = "offered"
    stamp(lot, "인수 검토 요청", cid, {"facility": facility["label"]})
    await db.commit()
    return await view(db, lot, cid)


async def offer_and_lot(db, key, cid):
    row = await db.get(WorkflowOffer, key)
    if not row:
        fail("인계 요청을 찾을 수 없습니다.", 404)
    lot = await lot_for(db, row.lot_id, cid, lock=True)
    await db.refresh(row)
    return row, lot


@router.post("/offers/{key}/decision")
async def decision(key: uuid.UUID, body: Decision, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    row, lot = await offer_and_lot(db, key, cid)
    version(lot, body.revision)
    if cid != row.recipient_id:
        fail("요청받은 업체만 수락·거절할 수 있습니다.", 403)
    if row.status not in {"pending", "conditional"} or lot.status not in {"offered", "conditional"}:
        fail("이미 응답한 요청입니다.")
    conditions = row.data.get("conditions", [])
    if body.accept and conditions:
        expected = {c["id"] for c in conditions}
        responses = row.data.get("condition_responses", {})
        if set(body.resolved_condition_ids) != expected or not all(
            responses.get(k, {}).get("text") for k in expected
        ):
            fail("조건별 자료가 모두 제출되고 수신기업이 모두 확인해야 최종 수락할 수 있습니다.")
    form = row.data.get("intake_conditions") or {}
    declared = {k: v["value"] for k, v in form.get("answers", {}).items()}
    if body.accept and declared.get("designated") in {"예", "모름"}:
        fail("지정폐기물 제외 업체입니다. 분류·유해성을 다시 확인하기 전 수락할 수 없습니다.")
    if body.accept and not (body.scope_checked and body.intake_checked):
        fail("업체의 허가 범위·반입 규격과 이번 물량을 확인해 주세요.")
    row.status = "accepted" if body.accept else "rejected"
    row.data = {
        **row.data,
        "decision": {**body.model_dump(exclude={"revision"}), "at": datetime.now(UTC).isoformat()},
    }
    lot.status = "accepted" if body.accept else ("processed" if lot.data["completed"] else "ready")
    if body.accept:
        step = RouteStep(
            waste_id=lot.id,
            seq=len(lot.data["completed"]) + 1,
            stage="처리",
            process=row.data["option"]["label"],
            facility_name=row.data["facility"]["label"],
            status="수락",
        )
        db.add(step)
        await db.flush()
        row.route_step_id = step.id
    stamp(lot, "인수 수락" if body.accept else "인수 거절", cid, {"note": body.note})
    await db.commit()
    return await view(db, lot, cid)


@router.post("/offers/{key}/conditions")
async def set_conditions(key: uuid.UUID, body: ConditionsIn, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    row, lot = await offer_and_lot(db, key, cid)
    version(lot, body.revision)
    if cid != row.recipient_id:
        fail("요청받은 업체만 반입조건을 제시할 수 있습니다.", 403)
    if row.status != "pending" or lot.status != "offered":
        fail("응답 대기 중인 요청에 조건을 제시해 주세요.")
    if any(not isinstance(c, str) or not 3 <= len(c.strip()) <= 600 for c in body.conditions):
        fail("각 조건을 3~600자로 작성해 주세요.", 422)
    row.data = {
        **row.data,
        "conditions": [
            {
                "id": str(uuid.uuid4()),
                "text": c.strip(),
                "proposed_by": str(cid),
                "at": datetime.now(UTC).isoformat(),
            }
            for c in body.conditions
        ],
        "condition_responses": {},
        "conditional_note": body.note,
    }
    row.status = "conditional"
    lot.status = "conditional"
    stamp(lot, "조건부 수락 · 자료 확인 전 운송 보류", cid, {"note": body.note})
    await db.commit()
    return await view(db, lot, cid)


@router.post("/offers/{key}/condition-responses")
async def condition_responses(
    key: uuid.UUID, body: ConditionResponses, company_id: CompanyId, db: DbSession
):
    cid = uuid.UUID(company_id)
    row, lot = await offer_and_lot(db, key, cid)
    version(lot, body.revision)
    if cid != row.sender_id:
        fail("발송기업만 조건별 자료를 제출할 수 있습니다.", 403)
    if row.status != "conditional" or lot.status != "conditional":
        fail("조건부 수락 중인 요청이 아닙니다.")
    allowed = {c["id"] for c in row.data["conditions"]}
    if any(
        k not in allowed or not isinstance(v, str) or not 3 <= len(v.strip()) <= 1000
        for k, v in body.responses.items()
    ):
        fail("요청된 조건의 자료·확인 내용을 3~1000자로 입력해 주세요.", 422)
    data = deepcopy(row.data)
    for k, v in body.responses.items():
        data["condition_responses"][k] = {
            "text": v.strip(),
            "company_id": str(cid),
            "at": datetime.now(UTC).isoformat(),
        }
    row.data = data
    stamp(lot, "조건 확인 자료 제출 · 수신기업 최종 확인 대기", cid)
    await db.commit()
    return await view(db, lot, cid)


@router.post("/offers/{key}/qr")
async def issue_qr(key: uuid.UUID, body: Version, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    row, lot = await offer_and_lot(db, key, cid)
    version(lot, body.revision)
    if row.sender_id != cid or row.status != "accepted":
        fail("수락된 요청의 발송 기업만 QR을 발급할 수 있습니다.", 403)
    token = secrets.token_urlsafe(32)
    row.qr_hash = hashlib.sha256(token.encode()).hexdigest()
    row.qr_expires_at = datetime.now(UTC) + timedelta(days=7)
    stamp(lot, "입고 QR 발급", cid)
    await db.commit()
    return {"offer_id": str(row.id), "token": token, "revision": lot.revision}


@router.get("/offers/{key}")
async def read_offer(key: uuid.UUID, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    row = await db.get(WorkflowOffer, key)
    if not row or cid not in {row.sender_id, row.recipient_id}:
        fail("인계 요청을 찾을 수 없습니다.", 404)
    return await view(db, await lot_for(db, row.lot_id, cid), cid)


@router.post("/offers/{key}/receive")
async def receive(key: uuid.UUID, body: Receipt, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    row, lot = await offer_and_lot(db, key, cid)
    version(lot, body.revision)
    if row.recipient_id != cid:
        fail("지정된 수신 기업으로 로그인해 주세요.", 403)
    if row.status != "accepted" or lot.status != "accepted":
        fail("이미 입고됐거나 수락 전인 요청입니다.")
    if (
        not row.qr_hash
        or not row.qr_expires_at
        or row.qr_expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
        or not secrets.compare_digest(row.qr_hash, hashlib.sha256(body.token.encode()).hexdigest())
    ):
        fail("QR이 유효하지 않거나 만료됐습니다.", 403)
    row.status = "received"
    row.qr_hash = None
    lot.current_company_id = cid
    lot.status = "processing"
    step = await db.get(RouteStep, row.route_step_id)
    step.status = "입고 확인"
    company = await db.get(Company, cid)
    db.add(
        QrFieldCheck(
            waste_id=lot.id,
            route_step_id=step.id,
            role=CheckRole.RECIPIENT,
            actor_name=company.company_name[:80],
        )
    )
    waste = await db.get(Waste, lot.id)
    waste.status = WasteStatus.IN_PROGRESS
    stamp(lot, "QR 입고 확인", cid)
    await db.commit()
    return await view(db, lot, cid)


@router.post("/lots/{key}/output")
async def output(key: uuid.UUID, body: Output, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid, lock=True)
    active(lot, cid, {"processing"})
    version(lot, body.revision)
    ref, _ = await read_reference(db)
    if body.state_key not in {
        s.key
        for s in ref.states
        if s.material == lot.data["initial"]["material"]
        and s.key in {t.output_state for t in ref.transitions}
    }:
        fail("현재 소재에 대응하는 산출물 상태를 선택해 주세요.", 422)
    row = await db.scalar(
        select(WorkflowOffer).where(WorkflowOffer.lot_id == key, WorkflowOffer.status == "received")
    )
    if not row or body.mass_kg > row.data["current"]["mass_kg"]:
        fail("입고 중량을 초과한 산출물은 별도 물질수지 확인이 필요합니다.")
    expected = row.data["option"]["output_state"]["key"]
    record = body.model_dump(exclude={"revision"})
    data = deepcopy(lot.data)
    data["current"] = record
    data["completed"].append(
        {
            "transition_key": row.data["option"]["transition_key"],
            "company_id": str(cid),
            "facility": row.data["facility"]["label"],
            "expected_state": expected,
            "output": record,
            "offer_id": str(row.id),
        }
    )
    lot.data = data
    lot.status = "processed" if expected == body.state_key else "review_required"
    lot.review = None
    row.status = "processed"
    step = await db.get(RouteStep, row.route_step_id)
    step.status = "처리 확인" if lot.status == "processed" else "산출물 불일치 보류"
    step.output = body.state_key
    step.actual_date = datetime.now(UTC).date()
    stamp(lot, "실제 산출물 기록", cid)
    await db.commit()
    return await view(db, lot, cid)


@router.post("/lots/{key}/finish")
async def finish(key: uuid.UUID, body: Finish, company_id: CompanyId, db: DbSession):
    cid = uuid.UUID(company_id)
    lot = await lot_for(db, key, cid, lock=True)
    active(lot, cid, {"processed"})
    version(lot, body.revision)
    finish_states = FINISH_STATES.get(lot.data["initial"]["material"], set())
    if not body.confirmed or lot.data["current"]["state_key"] not in finish_states:
        fail(
            "실제 최종 산출물(PP·PE 펠렛·컴파운드, PET 플레이크·펠렛, "
            "알루미늄 판재·잉곳)과 완료 확인이 필요합니다. "
            "파쇄품만으로 종료하지 않습니다."
        )
    lot.status = "completed"
    stamp(
        lot, "처리 완료 확인", cid, {"reference": body.reference, "intended_use": body.intended_use}
    )
    now = datetime.now(UTC)
    waste = await db.get(Waste, lot.id)
    waste.status = WasteStatus.COMPLETED
    waste.completed_at = now
    # Waste.quantity_value is the originally registered mass, not the final yield.
    owner = await db.get(Company, lot.owner_company_id)
    db.add(
        WasteCompletionSnapshot(
            waste_id=lot.id,
            company_name=owner.company_name,
            site_name=owner.site_name,
            site_address=owner.site_address,
            completed_at=now,
        )
    )
    steps = await db.scalars(select(RouteStep).where(RouteStep.waste_id == lot.id))
    for step in steps:
        step.status = "완료"
    await db.commit()
    return await view(db, lot, cid)
