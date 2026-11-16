"""Source-scoped questions. User answers never establish permits or acceptance."""

import hashlib
from copy import deepcopy
from functools import lru_cache

from app.domains.treatment.material_scope import PLASTICS
from app.domains.treatment.reference import read_bundle


@lru_cache
def published_conditions():
    return read_bundle("intake-conditions.json")


def question(
    key, label, choices=None, *, reason="이번 물량을 받는 업체가 확인할 정보", source=None
):
    return {
        "key": key,
        "label": label,
        "choices": choices or [],
        "reason": reason,
        "source": source,
        "required": True,
    }


def questionnaire(reference, facility_key, material, *, ai_review=None, directory_record=None):
    profile = published_conditions()["facilities"].get(facility_key, {})
    sources = {s.key: s for s in reference.sources}
    facts = []
    for entry in profile.get("facts", []):
        source = sources[entry["source_id"]]
        facts.append(
            {
                **entry,
                "url": source.url,
                "publisher": source.publisher,
                "checked_at": profile.get("checked_at"),
            }
        )
    caps = [
        c
        for c in reference.capabilities
        if c.facility == facility_key and material in c.input_profile.material_examples
    ]
    if not facts:
        for cap in caps[:1]:
            p = cap.input_profile
            facts.append(
                {
                    "text": (
                        f"공개 투입 예시: {', '.join(p.material_examples)} / "
                        f"{', '.join(p.form_examples)}"
                    ),
                    "kind": "public_example",
                    "source_id": p.source_ids[0],
                    "url": sources[p.source_ids[0]].url,
                    "publisher": sources[p.source_ids[0]].publisher,
                    "checked_at": sources[p.source_ids[0]].checked_date,
                    "scope": p.evidence_scope,
                }
            )
    qs = [
        question("contamination", "기름·약품·내용물 등의 오염이 있나요?", ["없음", "있음", "모름"]),
        question("separation", "다른 재질과 분리되어 있나요?", ["분리됨", "혼합됨", "모름"]),
        question(
            "packaging",
            "현재 포장·적재 형태는 무엇인가요?",
            ["벌크", "마대", "압축 베일", "팔레트", "기타", "모름"],
        ),
        question("shipment_date", "반출 희망일 또는 가능한 기간을 알려 주세요."),
    ]
    if material in PLASTICS:
        qs.append(
            question(
                "moisture",
                "세척 후 수분이나 젖은 부분이 남아 있나요?",
                ["건조됨", "젖어 있음", "모름"],
            )
        )
    if material in {"pe", "ps", "abs", "san", "pvc", "eps", "pa6", "pa66", "pcabs"}:
        qs.append(
            question(
                "resin_grade",
                "수지 세부 등급·첨가제·충전재 정보를 알고 있나요?",
                ["자료 있음", "자료 없음", "모름"],
                reason=(
                    "PE의 밀도 등급, PS의 발포 여부, 난연제·충전재 등은 재질명만으로 확인되지 않음"
                ),
            )
        )
    if material == "aluminium":
        qs.append(
            question(
                "alloy",
                "알루미늄 외 철·다른 금속 또는 내용물이 섞였나요?",
                ["없음", "있음", "모름"],
            )
        )
    if material == "paper":
        qs.append(
            question("coating", "방수 코팅·비닐·음식물 오염이 있나요?", ["없음", "있음", "모름"])
        )
    for q in profile.get("questions", []):
        source = sources[q["source_id"]]
        qs.append(
            question(
                q["key"],
                q["label"],
                q.get("choices"),
                reason=q["reason"],
                source={"url": source.url, "publisher": source.publisher},
            )
        )
    for text in ((ai_review or {}).get("lot_review") or {}).get("questions", [])[:8]:
        qs.append(
            question(
                "ai-" + hashlib.sha256(text.encode()).hexdigest()[:16],
                text,
                reason="현재 물량의 AI 검토에서 나온 확인 질문; 업체 반입 규정이 아님",
            )
        )
    if directory_record:
        qs.append(
            question(
                "process_evidence",
                "해당 사업장의 이번 공정 수행 근거가 있나요?",
                ["자료 있음", "자료 없음", "모름"],
                reason="명부의 폐기물 코드·설비명만으로 공정 전체 수행 능력을 확인할 수 없음",
            )
        )
    return {
        "version": "intake-questions-v1",
        "facts": facts,
        "questions": qs,
        "unknown_limits": [
            "허용 오염·수분 수치",
            "최소 반입량·최대 로트량",
            "현재 여유 용량",
            "가격·인수 일정",
            "현행 허가 범위",
        ],
        "recipient_confirmation_required": True,
        "dispatch_approved": False,
    }


def answer_assessment(form, answers):
    """No answer, including 'clean', can turn a public lead into an approved facility."""
    values = {key: row["value"] for key, row in answers.items()}
    missing = [q["key"] for q in form["questions"] if not values.get(q["key"])]
    flags = [
        key
        for key, value in values.items()
        if value in {"모름", "있음", "혼합됨", "젖어 있음", "자료 없음", "외부 회수 물량", "미선별"}
    ]
    return {
        "status": "needs_answers" if missing else "recipient_review_required",
        "unanswered": missing,
        "confirmation_keys": flags,
        "dispatch_approved": False,
        "basis": "sender_declared_not_verified",
    }


def attach_answers(form, answers):
    return {
        **deepcopy(form),
        "answers": deepcopy(answers),
        "assessment": answer_assessment(form, answers),
    }
