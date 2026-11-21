"""Prepare a human-readable inquiry; never send it or imply intake approval."""

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.domains.transport.schemas import InquirySummary

MAIL_BODY_MAX_LENGTH = 900
INQUIRY_QUESTIONS = (
    "이 물량의 반입 가능 여부",
    "반입 조건 (선별·세척 상태, 포장, 최소 수량 등)",
    "처리 단가와 가능한 일정",
)
PROVINCE_OR_CITY = re.compile(
    r"(?:서울(?:특별시)?|세종(?:특별자치시)?|(?:부산|대구|인천|광주|대전|울산)(?:광역시)?|"
    r"경기(?:도)?|강원(?:도|특별자치도)?|충[북남]|충청[북남]도|"
    r"전[북남]|전라[북남]도|전북특별자치도|경[북남]|경상[북남]도|제주(?:도|특별자치도)?)"
)
DISTRICT = re.compile(r"[가-힣]{1,12}[시군구]")
INTERNAL_MAIL_TEXT = re.compile(
    r"(?i:\b(?:https?://|www\.)\S+)|SCRAP\s+검토|"
    r"(?<![A-Za-z0-9])(?:AI|UTC)(?![A-Za-z0-9])|"
    r"(?i:\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b)"
)


class InquiryPacketRead(BaseModel):
    version: str = "vendor-inquiry-v1"
    generated_at: str
    filename: str
    subject: str
    text: str
    mail_body: str = Field(max_length=MAIL_BODY_MAX_LENGTH)


def _origin_region(address: str) -> str | None:
    parts = re.sub(r"\([^)]*\)", " ", address).replace(",", " ").split(maxsplit=2)
    if not parts:
        return None
    if not PROVINCE_OR_CITY.fullmatch(parts[0]):
        # 시·도 없이 "과천시 ..."처럼 시·군·구로 시작하는 주소는 그 단어만 쓴다.
        return parts[0] if DISTRICT.fullmatch(parts[0]) else None
    if len(parts) >= 2 and DISTRICT.fullmatch(parts[1]):
        return " ".join(parts[:2])
    if parts[0] in {"세종", "세종특별자치시"}:
        return parts[0]
    return None


def _inquiry_summary(lot, company, option, facility, material_label, state_label) -> InquirySummary:
    current = lot.data["current"]
    input_label = option["input_state"]["label"]
    output_label = option["output_state"]["label"]
    # "PE" + "PE 잔재...", "알루미늄" + "사용 후 알루미늄 음료캔"처럼
    # 형태 이름에 이미 재질이 들어 있으면 재질을 다시 붙이지 않는다.
    item = (
        state_label
        if state_label and material_label and material_label in state_label
        else " ".join(filter(None, [material_label, state_label]))
    )
    return InquirySummary(
        item=item,
        weight_kg=current["mass_kg"],
        condition=(current.get("condition") or "").strip() or None,
        # The initial waste code is only a reference for the first shipment.
        waste_code=None if lot.data["completed"] else lot.data["initial"].get("waste_code"),
        origin_region=_origin_region(company.site_address),
        road_distance_km=(
            facility.get("road_distance_km")
            if facility.get("road_distance_status") == "available"
            else None
        ),
        process=f"{input_label} → {output_label}" if input_label and output_label else None,
        questions=list(INQUIRY_QUESTIONS),
    )


def _mail_value(value: str | None, limit: int) -> str:
    cleaned = " ".join(INTERNAL_MAIL_TEXT.sub(" ", value or "").split())
    if len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _mail_body(company, facility_label: str, summary: InquirySummary) -> str:
    # Bound variable labels to leave room for the questions and the complete reply address.
    vendor = _mail_value(facility_label, 40)
    sender = _mail_value(company.company_name, 40) or "발송 기업"
    site = _mail_value(company.site_name, 35)
    origin = summary.origin_region
    if summary.road_distance_km is not None:
        distance = f"도로 약 {summary.road_distance_km:.1f} km"
        origin = f"{origin} ({distance})" if origin else f"귀사까지 {distance}"
    heading = "\n".join(
        [
            f"안녕하세요, {vendor} 담당자님." if vendor else "안녕하세요, 담당자님.",
            f"{' '.join(filter(None, [sender, site]))}입니다. "
            "아래 물량을 귀사에서 받아 주실 수 있는지 여쭙고자 연락드립니다.",
            "",
            "■ 물량 정보",
            f"- 품목: {_mail_value(summary.item, 50)}",
            f"- 중량: {summary.weight_kg:g} kg",
        ]
    )
    footer = f"{sender} 드림"
    if company.contact_email:
        footer += f" ({company.contact_email})"
    remainder = "\n".join(
        [
            *(
                f"- {label}: {value}"
                for label, value in (
                    ("폐기물 분류번호(참고)", _mail_value(summary.waste_code, 16)),
                    ("출발지", origin),
                    ("희망 처리", _mail_value(summary.process, 55)),
                )
                if value
            ),
            "",
            "■ 여쭙고 싶은 내용",
            *(f"{n}. {question}" for n, question in enumerate(summary.questions, 1)),
            "",
            "번거로우시겠지만 회신 부탁드립니다. 감사합니다.",
            footer,
        ]
    )
    condition_prefix = "\n- 상태: "
    budget = MAIL_BODY_MAX_LENGTH - len(heading) - len(remainder) - len(condition_prefix) - 1
    condition = _mail_value(summary.condition, budget) if budget > 1 else ""
    condition_line = condition_prefix + condition if condition else ""
    return f"{heading}{condition_line}\n{remainder}"


def review_candidates(lot, capability_key):
    return [
        (option, facility)
        for option in (lot.review or {}).get("next_step", {}).get("options", [])
        for facility in option["facilities"]
        if facility["capability_key"] == capability_key
    ]


def inquiry_packet(
    *, lot, company, option, facility, result, state_label, material_label, source_dates
):
    now = datetime.now(UTC).isoformat()
    current = lot.data["current"]
    follow_up = bool(lot.data["completed"])
    purity = current.get("purity_percent")
    purity_label = f"{purity}%" if purity is not None else "미확인"
    code_label = "최초 배출 시" if follow_up else "문진 참고"
    process_discovery = (facility.get("intake_conditions") or {}).get(
        "purpose"
    ) == "recipient_conversation"
    statuses = {
        "reviewed": "공개 근거 확인",
        "needs_evidence": "추가 근거 필요",
        "model_unavailable": "AI 검토 미완료",
    }
    lines = [
        "[SCRAP 업체 반입조건 문의서]",
        "검토용 초안입니다. 인수 승인·운송 지시·계약서가 아닙니다.",
        f"생성 시각(UTC): {now}",
        "",
        "1. 문의 대상과 현재 발송 사업장",
        f"문의 대상: {facility['label']}",
        f"대상 사업장: {facility.get('address') or '주소 확인 필요'}",
        f"발송 기업: {company.company_name}",
        f"출발 사업장: {company.site_name} / {company.site_address}",
        "",
        "2. 현재 물량 (발송기업이 기록한 정보)",
        f"재질: {material_label}",
        f"현재 형태: {state_label}",
        f"중량: {current['mass_kg']:g} kg",
        f"상태 설명: {current.get('condition') or '미기록'}",
        f"순도: {purity_label}",
        f"{code_label} 분류번호: {lot.data['initial']['waste_code']}",
        (
            "후속 산출물입니다. 최초 분류번호·R유형을 이번 인계에 자동 적용하지 않습니다. "
            "현재 분류와 재활용 조건을 확인해 주세요."
            if follow_up
            else "문진 분류는 참고 결과입니다. 현재 허가 범위와 반입 가능 여부를 확인해 주세요."
        ),
        "사진은 이 문서에 포함하지 않았습니다. SCRAP 인수 요청에서 함께 확인해 주세요.",
        "",
        "3. 검토 중인 공정",
        option["label"],
        f"{option['input_state']['label']} → {option['output_state']['label']}",
    ]
    if facility.get("road_distance_status") == "available":
        lines.append(
            f"참고 도로거리: {facility['road_distance_km']:.1f} km "
            "(자동차 경로, 화물차 통행·운송비 별도 확인)"
        )
    else:
        lines.append("도로거리: 미확인")
    lines += [
        "",
        "4. AI 검토와 남은 확인",
        f"공개 자료 검토: {statuses.get(result.get('status'), '검토 미완료')}",
        f"검토 시각: {(lot.review or {}).get('at') or '미확인'}",
    ]
    if result.get("finding") == "restriction_mentioned":
        lines.append(
            "반입 제한 근거가 확인되어 인수 요청이 보류된 후보입니다. 제한 해소 전 운송하지 마세요."
        )
    if result.get("process_match") == "matched":
        lines.append("공정 관련 업체입니다. 이번 물량의 세부 반입조건은 수신 기업이 확인합니다.")
    if (result.get("lot_review") or {}).get("status") != "reviewed":
        lines.append("현재 물량·사진에 대한 AI 검토가 완료되지 않았습니다.")
    if result.get("next_check") and not process_discovery:
        lines.append(f"추가 확인: {result['next_check']}")
    lot_review = result.get("lot_review") or {}
    for concern in lot_review.get("concerns", []):
        lines.append(f"- {concern['concern']} / 확인: {concern['next_check']}")
    for question in [] if process_discovery else lot_review.get("questions", []):
        lines.append(f"- {question}")
    lines += ["", "5. 업체와 협의할 내용"]
    declared_policy = facility.get("supplier_policy") or {}
    if declared_policy:
        p = declared_policy["policy"]
        lines.append(f"업체 직접 등록한 반입조건 {declared_policy['version']}차 (허가 인증 아님)")
        for key, label in [
            ("materials_forms", "재질·형태"),
            ("contamination", "오염·수분"),
            ("packaging", "포장·운송"),
            ("schedule", "일정"),
        ]:
            lines.append(f"- {label}: {p[key]}")
        lines.append(
            f"- 물량(kg): {p.get('min_mass_kg')} ~ {p.get('max_mass_kg')} (미정 값은 별도 협의)"
        )
        lines.extend(f"- 필수 확인: {check}" for check in p["required_checks"])
    form = facility.get("intake_conditions") or {}
    for q in form.get("questions", []):
        answer = (form.get("answers", {}).get(q["key"]) or {}).get("value") or "미응답"
        lines.append(f"- {q['label']} / 발송기업 답변: {answer}")
    if process_discovery:
        lines.append(
            "이번 사진·상태·물량을 확인한 뒤 가능한 반입조건과 일정을 메시지로 알려 주세요."
        )
    else:
        lines += [
            "- 귀 사업장이 이번 재질·형태·분류를 허가 범위 내에서 처리할 수 있는지 확인해 주세요.",
            "- 허용 오염·수분·혼합재질 조건과 필요한 샘플·검사 항목은 무엇인가요?",
            "- 최소/최대 반입량, 포장·하역 조건, 가능한 반입 일정은 어떻게 되나요?",
            "- 처리비 또는 매입가, 운송비 포함 여부, 견적 유효기간을 알려 주세요.",
            "- 처리 후 예상 산출물과 후속 처리 필요 여부를 알려 주세요. "
            "실제 결과는 처리 후 기록합니다.",
        ]
    lines += ["", "6. 참고 공개 자료"]
    for source in facility.get("sources", []):
        lines.append(
            f"- {source.get('publisher', '')} / {source.get('locator', '')} / "
            f"확인일: {source_dates.get(source.get('url')) or '별도 확인'} / "
            f"{source.get('url', '')}"
        )
    lines += [
        "",
        "공개 정보와 자기신고로 준비한 문의입니다. "
        "현재 허가·잔여 용량·가격·반입 승인을 보장하지 않습니다.",
        "SCRAP 내 인계 진행은 업체의 수신 계정 연결과 최종 수락 이후에 가능합니다.",
    ]
    subject = re.sub(
        r"\s+",
        " ",
        f"[반입조건 문의] {company.company_name} - {material_label} {current['mass_kg']:g}kg",
    ).strip()
    summary = _inquiry_summary(lot, company, option, facility, material_label, state_label)
    return (
        InquiryPacketRead(
            generated_at=now,
            filename="SCRAP-vendor-inquiry.txt",
            subject=subject[:120],
            text="\n".join(lines),
            mail_body=_mail_body(company, facility["label"], summary),
        ),
        summary,
    )
