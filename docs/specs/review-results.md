# Spec: 검토 결과 조회

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | API 명세 v3 API-030·031·034·035·047 (ROUTE·COMP·SAVE-003), 요구사항 명세 FR-3.3·3.5·4.5·4.6·5.7 |
| 관련 todo | T-115 |

## 1. 목적

저장된 엔진 응답(review-runs)을 화면이 쓰기 좋은 형태로 조회함. 엔진은 다시 호출하지 않음. 엔진이 하지 않은 판단(적합 판정, 순위, 비용·탄소, Critic)은 만들어 채우지 않고 "하지 않음·미확인"으로 보여줌 (product-plan 4장).

## 2. 범위

- 포함: 후보 목록·상세, 전문가 검토 대기 목록, 확인 과제 목록, 같은 검토의 두 실행 비교
- 제외: 리스크 결정·증빙 연결(review-risks-supplements), 보고서·공정 지도(post-MVP, FR-5.7에 따라 frontend 담당), 순위(ranking)·제외(excluded)·검출 게이트(checks)·단계별 리스크(risk-steps) 별도 조회 — API 명세 v3에서 후보 목록·상세로 통합

## 3. 요구사항

### 공통

1. 실행 status가 completed 또는 partial이고 결과가 있을 때만 조회함. 아니면 409 `RESULT_NOT_READY`
2. 다른 기업의 검토·실행은 404
3. `stale_company_profile`: 실행에 고정한 기업 정보 버전과 현재 버전이 다르면 true

### 후보 판정 (엔진 → server)

| 엔진 후보 status | judgment | 뜻 |
| --- | --- | --- |
| `needs_verification` | `needs_check` | 공개 조건·법령·허가 확인이 필요함 |
| `unmet` | `unsuitable` | 공개 조건과 어긋난 것이 확인됨 |
| 그 밖의 값 | `verification_failed` | 엔진 응답을 해석할 수 없음 |

4. 엔진은 적합(`suitable`)이나 제외(`excluded`)를 내지 않음. 필터 값으로는 받지만 현재 결과는 항상 비어 있음
5. **어떤 후보도 숨기지 않음** (FR-3.5). `unsuitable`도 목록에 남고 사유(`judgment_reasons`)를 붙임
6. 사유는 엔진 `blockers` 코드와 한글 설명: 법령 적용성 검토 전, 현행 허가·인수 조건 미확인, 시설 공개 조건과 맞지 않음, 법령 검색 결과 없음·실패·한도 초과, 법령 출처·시행일 확인 필요

### 후보 목록

7. 공정 경로(`process_route`): 단계 번호, 전이(파쇄 등), 연결 시설(없으면 null), 시설 조건 대조 결과와 사유
8. `facility`: 시설이 연결된 첫 단계의 시설
9. `tentative_rank`, `exclusion_reason`은 null, `cost_status`·`carbon_status`는 `missing` (FR-4.5: 추정해 채우지 않음)
10. `risk_counts`: 심각(high, 공개 조건과 어긋남)·보통(medium, 확인되지 않음) 리스크 수
11. `judgment` 필터 값이 5개 중 하나가 아니면 422 `INVALID_FILTER`

### 후보 상세

12. 목록 항목에 더해: `checks`(단계별 조건 대조), `risks`(리스크 id·단계·대상·심각도·다음 조치·출처 id), `legal_evidence`(법령 조사 과제별 검색 상태, 원문·조문·출처·시행일), `handoffs`(인계 구간), `cost`·`carbon`(`missing`), `critic`(`not_performed`), `unconfirmed`(확인되지 않은 리스크와 결과가 없는 법령 검색), 실행에 고정한 `evidence_grade`
13. 법령 근거의 `applicability`는 엔진이 적용성을 검토하지 않아 항상 `not_audited`. 검색 성공을 적법으로 해석하지 않음 (요구사항 11장 제약)
14. 없는 후보 id는 404

### 검토 대기·확인 과제

15. 검토 대기: 엔진 `route`가 REVIEW일 때 `needs_check` 후보와 확인할 리스크 이름. 담당 역할은 정해지지 않아 null (요구사항 가정: 기업 단일 역할)
16. 확인 과제: 리스크마다 1개(`risk:<risk_id>`), 결과가 없는 법령 검색마다 1개. 현재 status는 모두 `open` (done은 review-risks-supplements에서 리스크가 해소되면 생김)

### 버전 비교

17. `base_run_id`, `target_run_id`는 같은 검토의 실행이어야 함. 같은 기업의 다른 검토 실행이면 422 `DIFFERENT_REVIEW`, 다른 기업 실행이나 없는 실행은 404 (존재 여부를 드러내지 않음)
18. 후보별로 있음/없음(`presence`), `judgment`, 심각 리스크 수(`high_risks`), 사유(`blockers`)가 다르면 변경으로 돌려줌. 지식그래프 버전이 다르면 `graph_changed` true

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| GET | /api/v1/reviews/{reviewId}/runs/{runId}/candidates | access | 후보 목록 | 200 | 401, 404, 409, 422 |
| GET | /api/v1/reviews/{reviewId}/runs/{runId}/candidates/{candidateId} | access | 후보 상세 | 200 | 401, 404, 409 |
| GET | /api/v1/reviews/{reviewId}/runs/{runId}/review-queue | access | 전문가 검토 대기 | 200 | 401, 404, 409 |
| GET | /api/v1/reviews/{reviewId}/runs/{runId}/tasks | access | 확인 과제 | 200 | 401, 404, 409, 422 |
| GET | /api/v1/reviews/{reviewId}/compare | access | 두 실행 비교 | 200 | 401, 404, 409, 422 |

```json
// GET .../candidates?judgment=unsuitable
{
  "items": [{
    "candidate_id": "plan-b",
    "judgment": "unsuitable",
    "judgment_reasons": [{ "code": "facility_condition_unmet", "label": "시설 공개 조건과 맞지 않음" }],
    "process_route": [
      { "step_no": 1, "stage_id": "…", "transition": "파쇄", "facility": { "facility_id": "…", "name": "…" }, "condition_status": "unmet", "condition_reason": null },
      { "step_no": 2, "stage_id": "…", "transition": "펠릿화", "facility": null, "condition_status": "needs_verification", "condition_reason": "시설 연결 근거 없음" }
    ],
    "facility": { "facility_id": "…", "name": "…", "status_label": "unmet" },
    "tentative_rank": null, "exclusion_reason": null,
    "cost_status": "missing", "carbon_status": "missing",
    "risk_counts": { "high": 1, "medium": 1 },
    "stale_company_profile": false
  }],
  "pagingInfo": { "…": "…" }
}

// GET /reviews/{reviewId}/compare?base_run_id=…&target_run_id=…
{ "base_run_id": "…", "target_run_id": "…", "graph_changed": true,
  "changes": [{ "candidate_id": "plan-b", "field": "judgment", "base_value": "unsuitable", "target_value": "needs_check" }] }
```

## 5. 데이터

새 테이블 없음. `runs.result`(엔진 응답 원문)를 읽어 변환함 (`domains/results/transform.py`).

## 6. 완료 조건

- [x] 후보 목록에 엔진의 모든 후보가 있고, needs_verification은 needs_check, unmet은 unsuitable이며 사유가 붙음
- [x] 순위·제외 사유는 null, 비용·탄소는 missing, 기업 정보가 그대로면 stale false
- [x] 공정 경로의 전이·시설·조건 사유와 첫 시설, 리스크 수가 맞음
- [x] judgment 필터와 페이지네이션이 동작하고, 잘못된 필터는 422 INVALID_FILTER
- [x] 실행 뒤 기업 정보를 고치면 stale true
- [x] 끝나지 않았거나 실패한 실행은 409 RESULT_NOT_READY
- [x] 상세에 단계별 조건 대조, 심각도가 나뉜 리스크, 법령 원문·조문·시행일·not_audited, missing 비용, not_performed Critic, 근거 등급이 있음
- [x] 확인되지 않은 리스크와 결과가 없는 법령 검색이 unconfirmed에 있음
- [x] 없는 후보는 404
- [x] 검토 대기는 REVIEW일 때 needs_check 후보만, PASS면 비어 있음
- [x] 확인 과제는 리스크 4개 + 결과 없는 법령 검색 2개이고 모두 open
- [x] 비교 결과에 후보 사라짐·판정 변경·그래프 버전 변경이 있음
- [x] 다른 검토의 실행과 비교하면 422 DIFFERENT_REVIEW
- [x] 다른 기업 사용자는 모든 결과 조회가 404

## 7. 미정 사항

- 엔진에 Auditor·Critic·Pareto 비교가 생기면 suitable, excluded, tentative_rank, cost·carbon을 엔진 값으로 채움 (계약 버전이 바뀌므로 transform 갱신 필요)
- 후보가 많아지면 후보를 별도 테이블로 풀어 저장할지 (지금은 실행 결과 JSON을 매번 변환)
- 담당 역할(assignee_role) 체계를 둘지
