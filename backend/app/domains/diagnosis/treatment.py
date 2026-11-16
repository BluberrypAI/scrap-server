"""Bridge the current company-owned handoff to the existing treatment engine.

No classification inference, guessed R codes, or browser-supplied verdicts.
"""

from uuid import UUID

from app.core.config import get_settings
from app.domains.companies.models import Company
from app.domains.diagnosis.client import EngineUnavailableError
from app.domains.diagnosis.recycling import recycling_for_handoff, route_recycling
from app.domains.diagnosis.schemas import TreatmentContextRead, TreatmentSelectionIn
from app.domains.treatment.classification import INITIAL_PROFILES
from app.domains.treatment.intake import IntakeSelection, build_intake_batch, review_intakes
from app.domains.treatment.material_scope import FORM_LABELS
from app.domains.treatment.process import next_step, normalize_form
from app.domains.treatment.reference import resolve_material
from app.domains.treatment.repository import read_reference
from app.domains.treatment.schemas import HandoffVerification, NextStepRequest

# Confirmations narrow an upstream family; they never change its legal code.
MATERIAL_DETAILS = {
    ("plastic_packaging", "51-03-07"): ("pp", "pe", "pet"),
    ("fishing_net", "51-03-08"): ("pa6",),
    ("other_resin", "51-03-01"): ("san", "pa66", "pcabs"),
    ("nonferrous_scrap", "51-29-02"): ("aluminium",),
    ("aqua_buoy", "51-03-05"): ("eps",),
    ("metal_container", "51-29-04"): ("ferrous",),
}
DETAIL_LABELS = {
    "pp": "PP (폴리프로필렌)",
    "pe": "PE (폴리에틸렌)",
    "pet": "PET",
    "pa6": "PA6 (나일론 6) 폐어망",
    "san": "SAN (AS 수지)",
    "pa66": "PA66 (나일론 66)",
    "pcabs": "PC/ABS",
    "aluminium": "알루미늄 스크랩",
    "eps": "EPS (스티로폼) 부표 — PE·PP 부표 제외",
    "ferrous": "철제 드럼 — IBC·플라스틱 용기 제외",
}


def context_from_handoff(detail, case_id, selection, company):
    h = detail.get("handoff")
    context = TreatmentContextRead(
        status="review_required",
        case_id=case_id,
        message="문진 결과를 먼저 확정해 주세요.",
    )
    if detail.get("case", {}).get("status") != "CODE_CONFIRMED" or not h:
        return context
    if h.get("contract") != "diagnosis-handoff-v1" or h.get("case_id") != case_id:
        raise EngineUnavailableError()
    context.handoff = h
    context.warnings = list(h.get("assumptions") or [])
    if h.get("review") != "VERIFIED":
        context.warnings.append("검토 전 규칙에 따른 참고용 분류 결과입니다.")
    context.recycling = recycling_for_handoff(detail)
    if not context.recycling or context.recycling.get("status") != "table_listed":
        context.warnings.append("R코드는 미확인입니다. 적용 가능한 법령표를 확인해 주세요.")
    context.warnings.append("공정 후보와 R유형 조회는 업체 허가·반입 승인을 뜻하지 않습니다.")
    if (
        h.get("result_type") != "WASTE_CODE"
        or h.get("route_guidance", {}).get("action") != "RECOMMEND_ROUTE"
    ):
        context.message = (
            h.get("route_guidance", {}).get("summary")
            or "이 결과는 재활용 업체 조회 대상이 아닙니다."
        )
        return context
    if h.get("category") != "GENERAL":
        context.message = (
            "지정폐기물 등 별도 확인이 필요한 결과는 일반 재활용 후보로 연결하지 않습니다."
        )
        return context
    facts = h.get("facts", {})
    raw_material = (facts.get("material") or {}).get("value")
    material = resolve_material(raw_material)
    # A metal-can code includes steel cans too. Only the explicit aluminium-can
    # form selection below may bridge the classifier's broader material family.
    if raw_material == "metal_can" and h.get("waste_code") == "51-29-03":
        material = "aluminium"
        context.warnings.append(
            "폐금속캔 번호만으로 알루미늄을 판별하지 않습니다. "
            "아래에서 알루미늄 음료캔임을 확인한 물량만 연결하세요."
        )
    state = (facts.get("physical_state") or {}).get("value")
    code = h.get("waste_code")
    allowed = MATERIAL_DETAILS.get((raw_material, code))
    chosen = resolve_material(selection.material_detail)
    if allowed:
        allowed = tuple(
            m
            for m in allowed
            if any(p.material == m and code in p.waste_codes for p in INITIAL_PROFILES.values())
        )
        context.available_materials = [{"value": m, "label": DETAIL_LABELS[m]} for m in allowed]
        if not selection.material_detail:
            context.status = "needs_input"
            context.message = (
                "분류번호는 확인됐어요. 제품 표시·성적서로 확인한 세부 재질을 선택해 주세요."
            )
            return context
        if chosen not in allowed:
            context.message = (
                "재질이 미확인이거나 이 분류와 맞지 않습니다. 혼합물은 단일 재질로 선택하지 마세요."
            )
            return context
        material = chosen
        context.warnings.append(
            f"세부 재질 {DETAIL_LABELS[material]}은 사용자의 추가 확인입니다. "
            "원래 분류번호를 유지하며 성분 검사·반입 승인을 대신하지 않습니다."
        )
    elif selection.material_detail and (not chosen or chosen != material):
        context.message = (
            "확정 문진의 재질과 다른 재질로 변경할 수 없습니다. 문진을 다시 확인해 주세요."
        )
        return context
    context.selected_material = material
    profiles = [
        p for p in INITIAL_PROFILES.values() if p.material == material and code in p.waste_codes
    ]
    if not profiles:
        context.status = "unsupported"
        context.message = "이 분류번호·재질의 검수된 첫 공정 자료가 아직 없습니다."
        return context
    context.requires_solid_confirmation = state is None
    if state is None and not selection.solid_confirmed:
        context.status = "needs_input"
        context.message = "문진에 고체 여부가 없어 현재 물량의 상태를 확인해 주세요."
        return context
    if state is not None and state != "solid":
        context.message = "현재 고체 상태가 확인되지 않아 고체 재활용 공정 조회를 보류합니다."
        return context
    if state is None:
        context.warnings.append(
            "현재 고체 상태는 경로 화면에서 사용자가 추가 확인했습니다. "
            "성분·품질 검사 결과가 아닙니다."
        )
    context.available_forms = [
        {"value": p.input_form, "label": FORM_LABELS[p.input_form]} for p in profiles
    ]
    context.origin_label = company.site_address
    if company.site_latitude is not None and company.site_longitude is not None:
        context.origin = {"latitude": company.site_latitude, "longitude": company.site_longitude}
    else:
        context.warnings.append("사업장 좌표가 없어 거리 순위는 표시하지 않습니다.")
    form = normalize_form(selection.input_form)
    if not form:
        context.status = "needs_input"
        context.message = "분류는 확인됐어요. 문진에 없던 현재 물량의 형태만 확인해 주세요."
        return context
    if form not in {p.input_form for p in profiles}:
        context.status = "unsupported"
        context.message = "이 분류 결과와 현재 형태를 함께 지원하는 공정 자료가 없습니다."
        return context
    request = NextStepRequest(
        waste_code=code,
        material=material,
        input_form=form,
        origin=context.origin,
        **route_recycling(context.recycling),
    )
    context.route_input = request.model_dump(mode="json")
    context.status = "ready"
    context.message = "확정 문진을 기반으로 첫 처리 공정과 업체의 공개 근거를 조회합니다."
    return context


async def treatment_context(
    engine, db, company_id: str, case_id: str, selection: TreatmentSelectionIn, *, audit=False
):
    # Release the DB transaction before waiting for the remote engine/model.
    await db.rollback()
    # The caller's authenticated CompanyId gates access; the engine gates the case.
    detail = (await engine.request("GET", f"/cases/{case_id}", company_id)).body
    company = await db.get(Company, UUID(company_id))
    context = context_from_handoff(detail, case_id, selection, company)
    if context.status != "ready":
        return context
    reference, _ = await read_reference(db)
    request = NextStepRequest.model_validate(context.route_input)
    result = next_step(request, reference)
    for option in result.options:
        for facility in option.facilities:
            review = facility.intake_review
            facility.handoff_verification = HandoffVerification(
                process="public_evidence"
                if facility.evidence_basis == "published_site_process"
                else "unverified",
                intake_form="public_example"
                if review and review.form_evidence == "site_example"
                else "unverified",
            )
    context.next_step = result.model_dump(mode="json")
    if audit and result.status == "candidates":
        selected = IntakeSelection.model_validate(
            request.model_dump(exclude={"origin", "preview_transition"})
        )
        packets = build_intake_batch(selected, reference)
        await db.rollback()
        context.reviews = (await review_intakes(packets, get_settings())).model_dump(mode="json")
        latest = (await engine.request("GET", f"/cases/{case_id}", company_id)).body
        if (
            latest.get("case", {}).get("status") != "CODE_CONFIRMED"
            or latest.get("handoff") != detail.get("handoff")
            or recycling_for_handoff(latest) != context.recycling
        ):
            return TreatmentContextRead(
                status="review_required",
                case_id=case_id,
                message="AI 검토 중 문진 결과 또는 R유형 자료가 바뀌었습니다. 다시 확인해 주세요.",
            )
    return context
