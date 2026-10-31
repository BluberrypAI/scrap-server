# Spec: 검토 실행과 AI 엔진 연동

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 (워커는 프로세스 내 실행) |
| 관련 기획 | product-plan 3장(분석 연동), API 명세 v3 API-028·029·045 (ROUTE-001, SAVE-004, REVISE-005), 엔진 연동 INT-002·INT-003, 요구사항 명세 NFR-3·NFR-5·NFR-6 |
| 관련 todo | T-105, T-106, T-114 |

## 1. 목적

정리된 입력으로 검토를 실행함. 요청은 202로 바로 돌려주고 워커가 AI 엔진을 호출해 결과를 저장함. 실행에 쓴 입력·기업 정보·근거·그래프 버전을 고정해 어떤 결과가 어떤 입력에서 나왔는지 추적할 수 있게 함 (NFR-3).

## 2. 범위

- 포함: 실행 생성(202), 실행 상태 조회(polling), 실행 이력, AI 엔진 `POST /analysis/research` 호출, 엔진 오류 분류, 서버 재시작 시 미완료 실행 정리, 탈퇴 purge 시 삭제
- 제외: 결과 가공 조회(review-results), 재실행(review-risks-supplements), Service Bus·별도 워커 파드(infra 확정 후), 예산 상한 429 `BUDGET_LIMIT`(엔진에 비용 정보가 없음, INT-010), 비용·탄소 계산 호출(제출 수치가 없음)

## 3. 요구사항

### 엔진 계약 (ai 레포 develop, 2026-10-28 `c210b5c` 기준)

1. 호출: `POST {AI_BASE_URL}/analysis/research`, 본문 `{"lot": {...}}`. `max_pages` 등은 엔진 기본값을 씀
2. lot에는 **확인된 값만** 넣음. 엔진 lot 스키마가 받는 항목(`material`, `input_form`, `color`, `contamination`, `quantity_kg`, `generation_process`, `region`, `current_treatment`, `moisture_pct`, `contamination_pct`, `designated_waste`)만 보내고, 값이 null("모름")인 항목은 뺌. `has_test_report`는 보내지 않음
3. 응답 `contract_version`이 `candidate-research-v1`이 아니면 실패(`ENGINE_CONTRACT_MISMATCH`)
4. 엔진은 동기 응답이라 진행 상태를 물어볼 수 없음. 실행 상태는 server가 직접 기록함 (INT-003)

### 실행 생성

5. `intake_version`이 현재 입력 버전과 다르면 409 `VERSION_CONFLICT`
6. 검토 status가 `intake_ready`가 아니면 409 `INTAKE_INCOMPLETE`
7. 같은 검토에 queued·running 실행이 있으면 409 `RUN_IN_PROGRESS`
8. `AI_BASE_URL`이 비어 있으면 503 `ENGINE_UNAVAILABLE` (실행을 만들지 않음)
9. `document_ids`는 이 검토의 문서여야 함. 아니면 422 `VALIDATION_ERROR`. 지정한 문서의 **검수된 측정값 id**를 고정함
10. 근거 등급(FR-1.6): 지정한 시험성적서에 검수된 측정값이 있으면 A, 사용자가 측정값(함수율·오염도)을 직접 확인했으면 B, 그 외 C
11. 응답은 202와 `run_id`, `status=queued`, `pinned_versions`

### 워커

12. queued → running → completed / partial / failed
13. 엔진 응답의 `coverage.all_pages_read`가 true면 completed, 아니면 partial (결과는 있으나 조회 한도에 걸림)
14. 완료 시 엔진 응답 원문을 저장하고 `router_state`(엔진 `route`), `graph_trace`, `request_sha256`, 엔진 `run_id`를 고정함
15. 엔진 오류 분류 (NFR-5): 연결 실패·5xx → `ENGINE_UNAVAILABLE`, 시간 초과 → `ENGINE_TIMEOUT`, 409 → `GRAPH_VERSION_CHANGED`, 400·422 → `ENGINE_REJECTED_INPUT`, 계약 불일치 → `ENGINE_CONTRACT_MISMATCH`, 그 외 → `INTERNAL_ERROR`. 엔진 오류 본문은 코드만 남기고 메시지는 저장하지 않음
16. 실패한 실행이 있어도 새 실행을 만들 수 있음
17. 워커는 API 프로세스 안의 asyncio 작업(`InProcessRunQueue`)임. 서버가 시작할 때 queued·running으로 남은 실행은 failed `WORKER_INTERRUPTED`로 바꿈. Service Bus로 바꿀 때는 `RunQueue.enqueue`만 교체하고 워커 파드가 `execute_run`을 호출함

### 단계 (stages)

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| intake | 입력 정리 | 생성 시 done |
| research | 엔진: KG 후보 전체 조회 + 시설 공개 조건 대조 + 법령 검색 | pending → running → done / limit_reached / failed |
| cost_carbon | 비용·탄소 계산 | skipped (제출 근거 없음, 추정하지 않음) |
| critic | 전체 후보 종합 판정 | skipped (엔진 미구현) |
| router | PASS / REVISE / REVIEW | 엔진 응답의 route로 done |

### 조회

18. 실행 상태: 상태, 단계, `router_state`, `pinned_versions`, 오류(code, message), 엔진 `coverage`·`limitations`·`next_actions`
19. 실행 이력: 최신순 페이지네이션. 재실행은 `parent_run_id`, `rerun_from_stage`로 원래 실행을 가리킴
20. 검토 목록·상세의 `latest_run_id`는 가장 최근 실행
21. 다른 기업의 검토·실행은 404

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/reviews/{reviewId}/runs | access | 검토 실행 | 202 | 401, 404, 409, 422, 503 |
| GET | /api/v1/reviews/{reviewId}/runs | access | 실행 이력 | 200 | 401, 404, 409 |
| GET | /api/v1/reviews/{reviewId}/runs/{runId} | access | 실행 상태 | 200 | 401, 404, 409 |

```json
// POST /reviews/{reviewId}/runs
{ "intake_version": 2, "document_ids": ["…"] }
// 202
{
  "run_id": "…", "status": "queued",
  "pinned_versions": {
    "intake_version": 2, "company_profile_version": 1, "evidence_grade": "A",
    "document_ids": ["…"], "verified_value_ids": ["…"],
    "engine_contract_version": null, "engine_run_id": null, "request_sha256": null, "graph_trace": null
  }
}

// GET /reviews/{reviewId}/runs/{runId}
{
  "run_id": "…", "parent_run_id": null, "rerun_from_stage": null, "status": "completed",
  "stages": [{ "stage": "research", "status": "done", "reason": null }, { "stage": "critic", "status": "skipped", "reason": "AI 엔진에 전체 후보 종합 판정(Critic)이 아직 없음" }],
  "router_state": "REVIEW",
  "pinned_versions": { "graph_trace": { "graph_generation": "…", "reference_sha256": "…" }, "…": "…" },
  "error": null,
  "coverage": { "all_pages_read": true, "collected_candidates": 2 },
  "limitations": ["법령은 검색 후보입니다. …"], "next_actions": ["…"],
  "created_at": "…", "started_at": "…", "finished_at": "…"
}
```

API 명세 v3의 `pinned_versions{kg_snapshot, facility_db_snapshot, engine_version, prompt_version}`은 엔진이 주지 않는 값이라 쓰지 않고, 엔진이 실제로 주는 `graph_trace`, `engine_contract_version`, `request_sha256`으로 대신함.

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| runs | id, review_id, parent_run_id, rerun_from_stage, status, stages(JSON), router_state, pinned_versions(JSON), lot(JSON), result(JSON), error_code, error_message, started_at, finished_at, created_at, updated_at | FK reviews (cascade), parent_run_id FK runs (set null) |

환경변수: `AI_BASE_URL`(비우면 실행 불가), `AI_TIMEOUT_SECONDS`(기본 300).

## 6. 완료 조건

- [x] 실행하면 202, queued, 입력·기업 정보 버전과 근거 등급 C, graph_trace null
- [x] 완료된 실행은 completed, router_state REVIEW, graph_trace·계약 버전이 고정되고 단계 상태가 맞음
- [x] 엔진이 받은 lot에는 확인된 엔진 항목만 있음 (미확인 기본값, has_test_report 제외)
- [x] AI_BASE_URL이 없으면 503 ENGINE_UNAVAILABLE
- [x] 필수 입력이 남은 검토는 409 INTAKE_INCOMPLETE
- [x] 입력 버전이 바뀐 뒤 옛 버전으로 실행하면 409 VERSION_CONFLICT
- [x] queued 실행이 있으면 409 RUN_IN_PROGRESS
- [x] 엔진 503·409·422·계약 불일치는 각각 ENGINE_UNAVAILABLE, GRAPH_VERSION_CHANGED, ENGINE_REJECTED_INPUT, ENGINE_CONTRACT_MISMATCH로 failed
- [x] 엔진 연결 실패는 ENGINE_UNAVAILABLE
- [x] 실패 후 새 실행을 만들 수 있음
- [x] 전체 페이지를 읽지 못하면 partial, research 단계는 limit_reached
- [x] 검수된 시험성적서 측정값을 지정하면 근거 등급 A와 측정값 id가 고정됨
- [x] 사용자가 측정값을 확인하면 근거 등급 B
- [x] 다른 검토의 문서를 지정하면 422
- [x] 실행 이력은 최신순이고 검토의 latest_run_id가 최신 실행
- [x] 다른 기업 사용자는 실행 조회·생성이 404
- [x] 서버 시작 시 미완료 실행은 WORKER_INTERRUPTED로 failed
- [x] 탈퇴 purge 시 실행이 삭제됨

## 7. 미정 사항

- Service Bus와 별도 워커 파드로 옮기는 시점 (요구사항 NFR-6, infra 레포 리소스 확정 후)
- 예산 상한(429 BUDGET_LIMIT)을 어디서 관리할지 (엔진 연동 INT-010: server 자체 집계로 확정됐으나 엔진 응답에 비용 정보가 없음)
- 동시에 두 실행 요청이 들어오면 둘 다 만들어질 수 있음 (DB 제약이 없음). 필요하면 부분 유니크 인덱스 추가
- 엔진 `max_pages`, `max_legal_queries`를 server 설정으로 노출할지
- server ↔ ai 서비스 간 인증 (엔진 OpenAPI에 인증 정의가 없음, 요구사항 NFR-1 Entra ID)
