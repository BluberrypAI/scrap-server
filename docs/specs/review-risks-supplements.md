# Spec: 리스크 단계 결정, 추가 자료, 재실행

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | API 명세 v3 API-040~044 (RISK-001~003, REVISE-001~004), 엔진 연동 INT-005, 요구사항 명세 11장(최종 채택은 사람에게 위임) |
| 관련 todo | T-116 |

## 1. 목적

사람이 개입하는 컴플라이언스 흐름. 후보의 공정 단계별 리스크를 순서대로 확인·보류·자료 요청으로 결정하고, 증빙을 연결해야만 리스크가 해소되게 함. 실행 뒤 받은 추가 자료(검사 결과, 시설 회신, 견적, 규격)를 등록하고, 물량이 맞는 자료로 재실행함.

## 2. 범위

- 포함: 단계 결정, 리스크 증빙 연결, 추가 자료 등록·목록, 재실행, 후보 상세·확인 과제에 결정·해소 상태 반영, 탈퇴 purge 시 삭제
- 제외: 일부 단계만 다시 실행(엔진 미지원, INT-005), 추가 자료 값을 엔진 입력에 자동 반영(엔진 lot에 해당 필드 없음), 추가 자료 수정·삭제, 법령 확인 과제 닫기

## 3. 요구사항

### 단계 결정

1. 단계는 후보의 공정 경로 순서(1부터)임. 범위 밖 단계, 없는 후보는 404
2. 결정은 `confirm`(확인), `request_evidence`(자료 요청), `hold`(보류)
3. **현재 단계에만 결정할 수 있음**. 현재 단계 = 결정이 없거나 마지막 결정이 `request_evidence`인 첫 단계. 그 밖의 단계는 409 `STEP_OUT_OF_ORDER`
4. `confirm`·`hold`는 다음 단계로 넘어가고, `request_evidence`는 같은 단계에 머묾. 마지막 단계까지 결정하면 `next_step`은 null
5. 그 단계에 **해소되지 않은 심각(high) 리스크**가 있는데 `confirm`하려면 `proceed_option`(`hold_and_proceed`, `exclude`)이 필요함. 없으면 409 `RISK_OPTION_REQUIRED`
6. 결정은 기록만 함. 엔진 판정(`judgment`)을 바꾸지 않음 (최종 채택은 사람 몫, 시스템이 대신하지 않음)

### 리스크 상태

7. `resolved`: 증빙이 연결됨. `confirmed`: 해당 단계의 마지막 결정이 confirm. 그 외 `open`
8. **confirm 결정만으로는 resolved가 되지 않음**
9. 후보 상세의 `risks[].status`와 `risk_steps{current_step, steps[]}`에 반영함. 확인 과제 중 리스크 과제는 리스크가 resolved면 `done`

### 증빙 연결

10. `supplement_id`와 `document_id` 중 정확히 하나. 둘 다 없거나 둘 다 있으면 422 `VALIDATION_ERROR`
11. 실행 결과에 없는 리스크, 이 검토에 없는 자료·문서는 404
12. 추가 자료는 `counted_in_judgment`(물량 일치 + 검수됨)여야 하고, 문서는 검수된 측정값이 1개 이상 있어야 함. 아니면 422 `EVIDENCE_NOT_APPLICABLE`

### 추가 자료

13. multipart/form-data: `type`(inspection_result, facility_response, quote, specification), `effective_date`, `applied_quantity_value`, `applied_quantity_unit`(kg 기본, t), `verification_status`(기본 unverified), `value`(선택), `file`(선택, 문서와 같은 형식·크기 제한)
14. 적용 물량이 없으면 422 `MISSING_QUANTITY`. 단위는 kg로 환산해 저장
15. 검토에서 **확인된** 물량과 같으면 `matched`, 다르거나 검토 물량이 확인되지 않았으면 `mismatch`와 이유
16. `counted_in_judgment` = matched이고 verified. false인 자료는 증빙·재실행에 쓰지 않음

### 재실행

17. `supplement_ids`(1개 이상)는 모두 이 검토의 자료여야 하고(아니면 404), 모두 `counted_in_judgment`여야 함(아니면 409 `NO_APPLICABLE_SUPPLEMENT`)
18. 새 실행은 `parent_run_id`=원래 실행, `rerun_from_stage`=`research`, 원래 실행의 `document_ids`와 **현재** 입력 버전을 씀. 진행 중 실행·입력 미완료·엔진 미설정 규칙은 review-runs와 같음
19. 엔진에 부분 재실행이 없어 research부터 다시 실행함. 재사용 단계는 `intake`뿐 (INT-005 "자체 구현 vs 기능 축소" 중 기능 축소로 구현)
20. 추가 자료는 엔진 lot에 넣지 않고 `pinned_versions.supplement_ids`로 고정함 (어떤 자료를 보고 재실행했는지 추적용)

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/reviews/{reviewId}/runs/{runId}/candidates/{candidateId}/risk-steps/{stepNo}/decision | access | 단계 결정 | 200 | 401, 404, 409, 422 |
| POST | /api/v1/reviews/{reviewId}/runs/{runId}/risks/{riskId}/evidence | access | 증빙 연결 | 200 | 401, 404, 409, 422 |
| POST | /api/v1/reviews/{reviewId}/supplements | access | 추가 자료 등록 | 201 | 401, 404, 409, 413, 415, 422 |
| GET | /api/v1/reviews/{reviewId}/supplements | access | 추가 자료 목록 | 200 | 401, 404, 409 |
| POST | /api/v1/reviews/{reviewId}/runs/{runId}/rerun | access | 재실행 | 202 | 401, 404, 409, 422, 503 |

```json
// POST .../risk-steps/1/decision
{ "decision": "confirm", "proceed_option": "hold_and_proceed" }
→ { "decision": "confirm", "proceed_option": "hold_and_proceed", "decided_at": "…", "next_step": 2 }

// POST .../risks/{riskId}/evidence
{ "supplement_id": "…" }  →  { "risk_id": "…", "status": "resolved" }

// POST /reviews/{reviewId}/supplements 응답 201
{ "supplement_id": "…", "type": "inspection_result", "applicability": "mismatch",
  "mismatch_reason": "적용 물량 2000 kg가 검토 물량 3000 kg와 다름", "counted_in_judgment": false }

// POST .../runs/{runId}/rerun
{ "supplement_ids": ["…"] }  →  202 { "new_run_id": "…", "rerun_from_stage": "research", "reused_stages": ["intake"] }
```

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| supplements | id, review_id, type, value, applied_quantity_kg, effective_date, verification_status, applicability, mismatch_reason, file_name, storage_key, created_at, updated_at | FK reviews (cascade) |
| risk_step_decisions | id, run_id, candidate_id, step_no, decision, proceed_option, created_at(= decided_at), updated_at | FK runs (cascade). 같은 단계에 여러 건, 마지막이 유효 |
| risk_evidence | id, run_id, candidate_id, risk_id, supplement_id, document_id, created_at, updated_at | FK runs·supplements·documents (cascade) |

purge 순서: 리스크 기록 → 추가 자료(파일 포함) → 실행 → 문서 → 검토 → 기업.

## 6. 완료 조건

- [x] confirm하면 다음 단계로 넘어가지만 리스크는 confirmed이고 resolved가 아님
- [x] 뒤 단계를 먼저 결정하거나 끝난 단계를 다시 결정하면 409 STEP_OUT_OF_ORDER
- [x] request_evidence는 같은 단계에 머물고 이후 같은 단계를 confirm할 수 있음
- [x] 해소되지 않은 심각 리스크 단계를 option 없이 confirm하면 409 RISK_OPTION_REQUIRED, option을 주면 200
- [x] 마지막 단계를 결정하면 next_step null
- [x] 범위 밖 단계, 없는 후보는 404
- [x] 적용 물량이 없으면 422 MISSING_QUANTITY, 허용되지 않은 단위는 422
- [x] 3 t는 검토 물량 3000 kg와 matched, 2000 kg는 mismatch와 이유
- [x] 검수되지 않은 자료는 matched여도 counted_in_judgment false
- [x] 파일·값이 있는 자료가 목록에 kg 환산 물량과 함께 나옴
- [x] matched·verified 자료를 연결하면 resolved, 후보 상세와 확인 과제(done)에 반영
- [x] 심각 리스크가 해소되면 option 없이 confirm할 수 있음
- [x] 검수 안 됨·물량 불일치 자료는 422 EVIDENCE_NOT_APPLICABLE
- [x] 문서는 검수된 측정값이 생긴 뒤에만 연결됨
- [x] 자료·문서 id를 둘 다 안 보내면 422, 없는 리스크는 404
- [x] 재실행하면 202, 새 실행은 parent_run_id·supplement_ids가 고정되고 research부터 다시 실행됨
- [x] mismatch 자료로 재실행하면 409 NO_APPLICABLE_SUPPLEMENT, 없는 자료는 404
- [x] 다른 기업 사용자는 결정·자료 등록·목록이 404
- [x] 탈퇴 purge 시 추가 자료·결정·증빙이 삭제됨

## 7. 미정 사항

- 추가 자료(검사 결과 등)의 값을 엔진 입력에 반영할 방법 (엔진 lot에 해당 필드가 생기거나, 사용자가 입력 항목으로 다시 답하는 흐름)
- 사용자가 `exclude`로 넘긴 후보를 후보 목록에서 표시할지 (현재는 결정 기록만 하고 엔진 판정은 그대로)
- 일부 단계만 다시 실행 (INT-005 자체 구현)을 할지
- 법령 확인 과제를 사람이 닫는 API가 필요한지
