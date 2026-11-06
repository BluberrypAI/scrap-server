"""AI 서버 없이 검증할 때 쓰는 가짜 엔진 (docs/specs/dev-mock-engine.md).

실제 EngineClient는 그대로 두고 HTTP 전송만 교체함. 응답은 고정 샘플이라 입력이 달라도 후보가
같음. 형식은 tests/contracts/ 스냅샷으로 ai 레포 계약과 맞는지 테스트함.
후보 A는 조건 확인 필요(needs_verification), 후보 B는 공개 조건 불일치(unmet)임.
"""

import copy
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

MOCK_NOTICE = "개발용 가짜 엔진 응답입니다. 입력과 무관한 고정 샘플이며 실제 판정이 아닙니다."


def _stage(stage_id: str, transition: str, label: str, facility: str | None) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "transition": {"key": f"t-{transition}", "label": label},
        "facility": {"key": f"f-{stage_id}", "label": facility} if facility else None,
    }


def _risk(risk_id: str, target: str, status: str, label: str) -> dict[str, Any]:
    return {
        "risk_id": risk_id,
        "check_code": f"check-{risk_id}",
        "label": label,
        "reason": "검수된 수치 한도 또는 현행 운영 근거 미확보",
        "kind": "documented_mismatch" if status == "unmet" else "unverified_condition",
        "status": status,
        "next_action": f"시설에 확인: {label}",
        "target_id": target,
        "target_type": "stage",
        "source_ids": [f"src-{risk_id}"],
        "condition_mismatch_detected": status == "unmet",
        "actual_incident_confirmed": False,
    }


def _task(target: str, topic: str, search_id: str) -> dict[str, Any]:
    return {"target_id": target, "target_type": "stage", "topic": topic, "search_id": search_id}


def _candidate(plan_id: str, status: str, risk_status: str) -> dict[str, Any]:
    s1, s2 = f"{plan_id}-s1", f"{plan_id}-s2"
    blockers = ["legal_applicability_not_audited", "operational_conditions_unverified"]
    if status == "unmet":
        blockers.append("facility_condition_unmet")
    return {
        "plan": {
            "plan_id": plan_id,
            "state": "graph_compatible",
            "research_packet": {
                "stages": [
                    _stage(s1, "shred", "파쇄", f"{plan_id} 파쇄 시설"),
                    _stage(s2, "pellet", "펠릿화", None),
                ],
                "handoffs": [{"leg_id": f"{plan_id}-leg1"}],
            },
            "external_model_allowed": False,
            "withheld_evidence_ids": [],
            "recommended": False,
            "dispatch_approved": False,
        },
        "facility_assessment": {
            "plan_id": plan_id,
            "status": status,
            "stages": [
                {
                    "transition_key": "t-shred",
                    "stage_id": s1,
                    "status": risk_status,
                    "assessment": {
                        "capability_key": f"cap-{plan_id}",
                        "facility_key": f"f-{s1}",
                        "risks": [
                            _risk(f"{plan_id}-r1", s1, risk_status, "함수율 한도"),
                            _risk(f"{plan_id}-r2", s1, "needs_verification", "이물 허용 기준"),
                        ],
                    },
                },
                {
                    "transition_key": "t-pellet",
                    "stage_id": s2,
                    "status": "needs_verification",
                    "reason": "시설 연결 근거 없음",
                    "assessment": None,
                },
            ],
        },
        "legal_tasks": [
            {
                "target_id": s1,
                "target_type": "stage",
                "topic": "classification",
                "search_id": "ls-1",
            },
            {"target_id": s1, "target_type": "stage", "topic": "facility", "search_id": "ls-2"},
        ],
        "blockers": sorted(blockers),
        "status": status,
        "recommended": False,
    }


_RESULT: dict[str, Any] = {
    "contract_version": "candidate-research-v1",
    "run_id": "engine-run-1",
    "request_sha256": "sha-req-1",
    "generated_at": "2026-10-30T00:00:00+00:00",
    "input_context": {},
    "graph_trace": {"graph_generation": "gen-1", "reference_sha256": "ref-1"},
    "coverage": {
        "all_pages_read": True,
        "collected_candidates": 2,
        "complete_within_curated_scope": True,
        "legal_retrieval_complete": False,
        "legal_audit_complete": False,
    },
    "candidates": [
        _candidate("plan-a", "needs_verification", "needs_verification"),
        _candidate("plan-b", "unmet", "unmet"),
    ],
    "legal_searches": [
        {
            "search_id": "ls-1",
            "query": "PP 폐기물 분류 사업장폐기물 지정폐기물",
            "status": "retrieved",
            "attempted": True,
            "results": [
                {
                    "evidence_id": "legal-chunk:1",
                    "title": "폐기물관리법",
                    "document_type": "LAW",
                    "heading": "제2조",
                    "content": "이 법에서 사용하는 용어의 뜻은 다음과 같다.",
                    "citation": "폐기물관리법 제2조",
                    "source_url": "https://www.law.go.kr/법령/폐기물관리법",
                    "effective_from": "2025-01-01",
                    "retrieval_method": "hybrid",
                    "source_checks": [],
                    "applicability": "not_audited",
                }
            ],
            "applicability": "not_audited",
        },
        {
            "search_id": "ls-2",
            "query": "PP 파쇄 시설 폐기물처리업 허가",
            "status": "no_hits",
            "attempted": True,
            "results": [],
            "applicability": "not_audited",
        },
    ],
    "next_actions": ["검색 원문·시행일·적용 사실·예외를 Auditor에서 검증하세요."],
    "route": "REVIEW",
    "final_recommendations": [],
    "limitations": ["법령은 검색 후보입니다."],
    "dispatch_approved": False,
}


def research_result(**overrides: Any) -> dict[str, Any]:
    result = copy.deepcopy(_RESULT)
    result.update(overrides)
    return result


def _respond(request: httpx.Request) -> httpx.Response:
    if request.method != "POST" or request.url.path != "/analysis/research":
        return httpx.Response(404, json={"detail": "Not Found"})
    lot = json.loads(request.content)["lot"]
    result = research_result(
        run_id=f"mock-{uuid.uuid4()}",
        request_sha256=f"mock-{uuid.uuid4().hex}",
        generated_at=datetime.now(UTC).isoformat(),
        input_context=lot,
        limitations=[MOCK_NOTICE, *_RESULT["limitations"]],
    )
    return httpx.Response(200, json=result)


def mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(_respond)
