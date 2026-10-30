"""엔진 응답(candidate-research-v1)을 화면용 결과로 바꾸는 순수 함수.

docs/specs/review-results.md 3장.

엔진이 판정하지 않은 값(적합 판정, 비용·탄소, 순위)은 만들지 않고 미확인으로 둠.
"""

from typing import Any

# 엔진 후보 status → 판정 코드. 엔진은 적합(suitable)을 내지 않음
_JUDGMENT = {"unmet": "unsuitable", "needs_verification": "needs_check"}
JUDGMENTS = ("suitable", "needs_check", "unsuitable", "verification_failed", "excluded")

BLOCKER_LABELS = {
    "legal_applicability_not_audited": "법령 적용성 검토 전",
    "operational_conditions_unverified": "현행 허가·인수 조건 미확인",
    "facility_condition_unmet": "시설 공개 조건과 맞지 않음",
    "legal_search_no_hits": "법령 검색 결과 없음",
    "legal_search_unavailable": "법령 검색 실패",
    "legal_search_budget_exhausted": "법령 검색 한도 초과",
    "legal_source_review_required": "법령 출처·시행일 확인 필요",
}

_NOT_COMPUTED = {
    "status": "missing",
    "total": None,
    "missing": ["제출된 비용·탄소 근거가 없어 계산하지 않음"],
}


def judgment_of(candidate: dict[str, Any]) -> str:
    return _JUDGMENT.get(candidate.get("status"), "verification_failed")


def _reasons(candidate: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"code": code, "label": BLOCKER_LABELS.get(code, code)}
        for code in candidate.get("blockers", [])
    ]


def _assessments(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stages = (candidate.get("facility_assessment") or {}).get("stages", [])
    return {s["stage_id"]: s for s in stages}


def _packet(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate["plan"].get("research_packet") or {"stages": [], "handoffs": []}


def process_route(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    assessed = _assessments(candidate)
    route = []
    for step_no, stage in enumerate(_packet(candidate)["stages"], 1):
        check = assessed.get(stage["stage_id"], {})
        facility = stage.get("facility")
        route.append(
            {
                "step_no": step_no,
                "stage_id": stage["stage_id"],
                "transition": (stage.get("transition") or {}).get("label"),
                "facility": {"facility_id": facility.get("key"), "name": facility.get("label")}
                if facility
                else None,
                "condition_status": check.get("status", "needs_verification"),
                "condition_reason": check.get("reason"),
            }
        )
    return route


def risks(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """시설 조건 대조에서 나온 리스크. 단계 순서대로."""
    step_of = {s["stage_id"]: i for i, s in enumerate(_packet(candidate)["stages"], 1)}
    found = []
    for stage_id, check in _assessments(candidate).items():
        for risk in (check.get("assessment") or {}).get("risks", []):
            found.append(
                {
                    "risk_id": risk["risk_id"],
                    "step_no": step_of.get(stage_id),
                    "target_id": risk.get("target_id", stage_id),
                    "target_type": risk.get("target_type", "stage"),
                    "label": risk.get("label"),
                    "reason": risk.get("reason"),
                    # 공개 조건과 실제로 어긋난 것은 심각, 확인되지 않은 것은 보통
                    "severity": "high" if risk.get("status") == "unmet" else "medium",
                    "engine_status": risk.get("status"),
                    "next_action": risk.get("next_action"),
                    "source_ids": risk.get("source_ids", []),
                }
            )
    return sorted(found, key=lambda r: (r["step_no"] or 0, r["risk_id"]))


def _first_facility(route: list[dict[str, Any]]) -> dict[str, Any] | None:
    for step in route:
        if step["facility"]:
            return {**step["facility"], "status_label": step["condition_status"]}
    return None


def list_item(candidate: dict[str, Any], stale_company_profile: bool) -> dict[str, Any]:
    route = process_route(candidate)
    found = risks(candidate)
    return {
        "candidate_id": candidate["plan"]["plan_id"],
        "judgment": judgment_of(candidate),
        "judgment_reasons": _reasons(candidate),
        "process_route": route,
        "facility": _first_facility(route),
        # 엔진이 순위·제외를 정하지 않음 (Pareto 비교 전)
        "tentative_rank": None,
        "exclusion_reason": None,
        "cost_status": "missing",
        "carbon_status": "missing",
        "risk_counts": {
            "high": sum(r["severity"] == "high" for r in found),
            "medium": sum(r["severity"] == "medium" for r in found),
        },
        "stale_company_profile": stale_company_profile,
    }


def _legal_evidence(
    candidate: dict[str, Any], searches: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    evidence = []
    for task in candidate.get("legal_tasks", []):
        search = searches.get(task["search_id"], {})
        evidence.append(
            {
                "target_id": task["target_id"],
                "target_type": task["target_type"],
                "topic": task["topic"],
                "search_status": search.get("status", "unavailable"),
                "query": search.get("query"),
                "results": [
                    {
                        key: hit.get(key)
                        for key in (
                            "evidence_id",
                            "title",
                            "citation",
                            "content",
                            "source_url",
                            "effective_from",
                            "source_checks",
                            "applicability",
                        )
                    }
                    for hit in search.get("results", [])
                ],
            }
        )
    return evidence


def detail(
    candidate: dict[str, Any], result: dict[str, Any], stale_company_profile: bool
) -> dict[str, Any]:
    searches = {s["search_id"]: s for s in result.get("legal_searches", [])}
    evidence = _legal_evidence(candidate, searches)
    found = risks(candidate)
    route = process_route(candidate)
    unconfirmed = [
        {"kind": "risk", "ref_id": r["risk_id"], "label": r["label"]}
        for r in found
        if r["engine_status"] != "matched"
    ] + [
        {
            "kind": "legal_search",
            "ref_id": e["target_id"],
            "label": f"{e['topic']} 법령 검색: {e['search_status']}",
        }
        for e in evidence
        if e["search_status"] != "retrieved"
    ]
    return {
        **list_item(candidate, stale_company_profile),
        "judgment": {"status": judgment_of(candidate), "reasons": _reasons(candidate)},
        "process_route": route,
        "handoffs": _packet(candidate).get("handoffs", []),
        "checks": [
            {"step_no": s["step_no"], "stage_id": s["stage_id"], "result": s["condition_status"]}
            for s in route
        ],
        "risks": found,
        "legal_evidence": evidence,
        "cost": dict(_NOT_COMPUTED),
        "carbon": dict(_NOT_COMPUTED),
        "critic": {"status": "not_performed", "issues": []},
        "unconfirmed": unconfirmed,
    }


def review_queue(result: dict[str, Any], router_state: str | None) -> list[dict[str, Any]]:
    """전문가 검토 대기. 엔진 판정이 REVIEW일 때 확인이 필요한 후보."""
    if router_state != "REVIEW":
        return []
    return [
        {
            "candidate_id": c["plan"]["plan_id"],
            "reason": ", ".join(r["label"] for r in _reasons(c)),
            "required_checks": [r["label"] for r in risks(c)],
            # 역할 체계가 없어 미정 (요구사항 가정: 기업 단일 역할)
            "assignee_role": None,
        }
        for c in result.get("candidates", [])
        if judgment_of(c) == "needs_check"
    ]


def tasks(result: dict[str, Any]) -> list[dict[str, Any]]:
    """확인 과제: 리스크마다 하나, 결과가 없는 법령 검색마다 하나."""
    searches = {s["search_id"]: s for s in result.get("legal_searches", [])}
    found = []
    for candidate in result.get("candidates", []):
        candidate_id = candidate["plan"]["plan_id"]
        for risk in risks(candidate):
            found.append(
                {
                    "task_id": f"risk:{risk['risk_id']}",
                    "candidate_id": candidate_id,
                    "risk_id": risk["risk_id"],
                    "item": risk["label"],
                    "required_material": risk["next_action"],
                    "assignee_role": None,
                }
            )
        for e in _legal_evidence(candidate, searches):
            if e["search_status"] != "retrieved":
                found.append(
                    {
                        "task_id": f"legal:{candidate_id}:{e['target_id']}:{e['topic']}",
                        "candidate_id": candidate_id,
                        "risk_id": None,
                        "item": f"{e['topic']} 법령 근거 확인 ({e['search_status']})",
                        "required_material": e["query"],
                        "assignee_role": None,
                    }
                )
    return found


def compare(base: dict[str, Any], target: dict[str, Any]) -> list[dict[str, Any]]:
    """두 실행 결과의 후보 단위 차이."""

    def summary(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        out = {}
        for c in result.get("candidates", []):
            found = risks(c)
            out[c["plan"]["plan_id"]] = {
                "judgment": judgment_of(c),
                "high_risks": sum(r["severity"] == "high" for r in found),
                "blockers": sorted(c.get("blockers", [])),
            }
        return out

    a, b = summary(base), summary(target)
    changes = []
    for candidate_id in sorted(a.keys() | b.keys()):
        if candidate_id not in a or candidate_id not in b:
            changes.append(
                {
                    "candidate_id": candidate_id,
                    "field": "presence",
                    "base_value": candidate_id in a,
                    "target_value": candidate_id in b,
                }
            )
            continue
        for field in ("judgment", "high_risks", "blockers"):
            if a[candidate_id][field] != b[candidate_id][field]:
                changes.append(
                    {
                        "candidate_id": candidate_id,
                        "field": field,
                        "base_value": a[candidate_id][field],
                        "target_value": b[candidate_id][field],
                    }
                )
    return changes
