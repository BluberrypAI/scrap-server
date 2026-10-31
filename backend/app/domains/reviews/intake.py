"""입력 객체 규칙 (docs/specs/review-intake.md 3장).

입력 객체는 항목 이름 → {"value", "source", "confirmed"} 딕셔너리임.
- source=user: 사용자가 직접 입력·답변한 값. confirmed=True
- source=company_profile: 기업 정보에서 가져온 기본값. 사용자가 답하기 전까지 confirmed=False
항목이 없으면 아직 답하지 않은 것이고, value=None이면 사용자가 "모름"이라고 답한 것임.
"""

from typing import Any

from app.domains.reviews.models import ReviewStatus
from app.domains.reviews.schemas import IntakeValues

# 비어 있으면 실행할 수 없는 항목. 엔진은 소재가 없으면 후보를 찾지 않고, 비교에는 물량이 필요함
REQUIRED_FIELDS = ("material", "quantity_kg")

# 시험성적서가 없을 때 직접 확인해야 하는 측정값 (FR-1.4)
MEASURED_FIELDS = ("moisture_pct", "contamination_pct")

# 질문·응답 순서를 고정하기 위한 전체 항목 순서
FIELD_ORDER = tuple(IntakeValues.model_fields)


def _entry(value: Any, source: str) -> dict[str, Any]:
    return {"value": value, "source": source, "confirmed": source == "user"}


def initial_intake(overrides: IntakeValues, snapshot: dict[str, Any]) -> dict[str, Any]:
    """기업 기본값을 미확인 값으로 깔고, 사용자가 보낸 항목을 확인된 값으로 덮음."""
    intake: dict[str, Any] = {}
    categories = [w["category"] for w in snapshot.get("main_waste_types", [])]
    # 주요 폐기물이 여러 개면 어느 것인지 알 수 없으므로 기본값을 두지 않음
    if len(categories) == 1:
        intake["material"] = _entry(categories[0], "company_profile")
    if snapshot.get("industry"):
        intake["generation_process"] = _entry(snapshot["industry"], "company_profile")
    for field in overrides.model_fields_set:
        intake[field] = _entry(getattr(overrides, field), "user")
    return intake


def apply_answers(intake: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any] | None:
    """답변을 반영한 새 입력 객체를 돌려줌. 바뀐 값이 없으면 None."""
    updated = dict(intake)
    for field, value in answers.items():
        updated[field] = _entry(value, "user")
    return None if updated == intake else updated


def _confirmed(intake: dict[str, Any], field: str) -> bool:
    entry = intake.get(field)
    return entry is not None and entry["confirmed"]


def _value(intake: dict[str, Any], field: str) -> Any:
    entry = intake.get(field)
    return entry["value"] if entry is not None else None


def questions(intake: dict[str, Any]) -> list[dict[str, Any]]:
    """보완 질문 목록. required=True인 질문이 남아 있으면 실행할 수 없음."""
    found: dict[str, dict[str, Any]] = {}

    def ask(field: str, reason: str, required: bool) -> None:
        found.setdefault(field, {"field": field, "reason": reason, "required": required})

    for field in REQUIRED_FIELDS:
        entry = intake.get(field)
        if entry is not None and not entry["confirmed"]:
            ask(field, f"기업 정보의 기본값({entry['value']})이 맞는지 확인이 필요함", True)
        elif _value(intake, field) is None:
            ask(field, "필수 항목. 값이 없으면 검토를 실행할 수 없음", True)

    # 오염도 0%인데 오염 내용이 있으면 둘 중 하나가 잘못된 것임 (FR-1.5)
    if (
        _confirmed(intake, "contamination_pct")
        and _value(intake, "contamination_pct") == 0
        and _value(intake, "contamination")
    ):
        ask(
            "contamination_pct",
            "오염도가 0%인데 오염 내용이 입력되어 있음. 둘 중 맞는 값을 확인해야 함",
            True,
        )

    for field, entry in intake.items():
        if not entry["confirmed"]:
            ask(field, f"기업 정보의 기본값({entry['value']})이 맞는지 확인이 필요함", False)

    if "has_test_report" not in intake:
        ask("has_test_report", "시험성적서 보유 여부에 따라 이후 확인할 항목이 달라짐", False)
    elif _value(intake, "has_test_report") is False:
        for field in MEASURED_FIELDS:
            if field not in intake:
                ask(field, "시험성적서가 없어 측정값을 직접 확인해야 함. 모르면 비워 둠", False)
    elif _value(intake, "has_test_report") is True:
        ask("documents", "시험성적서를 업로드하면 문서의 측정값을 근거로 씀", False)

    if "region" not in intake:
        ask("region", "처리 시설과의 거리 비교에 쓰임. 모르면 비워 둠", False)

    order = {f: i for i, f in enumerate(FIELD_ORDER)}
    return sorted(found.values(), key=lambda q: (not q["required"], order.get(q["field"], 99)))


def status_of(intake: dict[str, Any]) -> ReviewStatus:
    if any(q["required"] for q in questions(intake)):
        return ReviewStatus.INTAKE_PENDING
    return ReviewStatus.INTAKE_READY


def grouped(intake: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(확인된 값, 미확인 값) 목록. 항목 순서는 FIELD_ORDER를 따름."""
    confirmed, unconfirmed = [], []
    for field in FIELD_ORDER:
        entry = intake.get(field)
        if entry is None:
            continue
        item = {"field": field, "value": entry["value"], "source": entry["source"]}
        (confirmed if entry["confirmed"] else unconfirmed).append(item)
    return confirmed, unconfirmed


def confirmed_values(intake: dict[str, Any]) -> dict[str, Any]:
    """확인되고 값이 있는 항목만. 엔진에 보낼 때 씀 (미확인 기본값은 보내지 않음)."""
    return {
        field: entry["value"]
        for field, entry in intake.items()
        if entry["confirmed"] and entry["value"] is not None
    }
