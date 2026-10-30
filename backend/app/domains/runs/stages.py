"""실행 단계 목록과 상태 (docs/specs/review-runs.md 3장).

엔진이 지금 제공하는 단계는 research 하나뿐임. 엔진에 없는 단계는 skipped와 이유를 남겨
"했는데 문제없음"과 "하지 않음"을 구분함.
"""

from typing import Any

INTAKE = "intake"
RESEARCH = "research"
COST_CARBON = "cost_carbon"
CRITIC = "critic"
ROUTER = "router"

# 엔진이 아직 하지 않는 단계와 그 이유
_NOT_PERFORMED = {
    COST_CARBON: "제출된 비용·탄소 근거가 없어 계산하지 않음 (추정해 채우지 않음)",
    CRITIC: "AI 엔진에 전체 후보 종합 판정(Critic)이 아직 없음",
}


def initial_stages() -> list[dict[str, Any]]:
    return [
        {"stage": INTAKE, "status": "done", "reason": None},
        {"stage": RESEARCH, "status": "pending", "reason": None},
        *({"stage": s, "status": "skipped", "reason": r} for s, r in _NOT_PERFORMED.items()),
        {"stage": ROUTER, "status": "pending", "reason": None},
    ]


def with_stage(
    stages: list[dict[str, Any]], stage: str, status: str, reason: str | None = None
) -> list[dict[str, Any]]:
    """한 단계의 상태를 바꾼 새 목록. JSON 컬럼 변경 감지를 위해 새 객체를 만듦."""
    return [
        {**s, "status": status, "reason": reason} if s["stage"] == stage else dict(s)
        for s in stages
    ]
