"""Prepare a human-readable inquiry; never send it or imply intake approval."""

from datetime import UTC, datetime

from pydantic import BaseModel


class InquiryPacketRead(BaseModel):
    version: str = "vendor-inquiry-v1"
    generated_at: str
    filename: str
    text: str


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
    return InquiryPacketRead(
        generated_at=now, filename="SCRAP-vendor-inquiry.txt", text="\n".join(lines)
    )
