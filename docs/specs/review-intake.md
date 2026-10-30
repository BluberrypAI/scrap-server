# Spec: 검토 생성·조회와 입력 정리

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | product-plan 3장(분석 연동), API 명세 v3 API-019~022·API-046 (INPUT-001~003, SAVE-001), 요구사항 명세 FR-1.1·1.3·1.4·1.5 |
| 관련 todo | T-112 |

## 1. 목적

검토(review)의 시작점. 사용자의 자연어 상황 설명과 구조화 항목을 받아 검토를 만들고, 기업 기본값을 스냅샷으로 남긴 뒤 확인된 값·미확인 값·보완 질문으로 정리함. 이 입력 객체가 이후 검토 실행(review-runs)에서 AI 엔진에 보내는 lot의 원본이 됨.

## 2. 범위

- 포함: 검토 생성, 목록·상세 조회, 입력 객체 조회, 보완 질문 답변, 탈퇴 purge 시 삭제
- 제외: 자연어에서 항목을 뽑아내는 처리(LLM 호출은 server 범위 밖, AI 엔진에도 아직 없음), 사업장(site) 선택(사업장 API가 post-MVP라 `site_id`는 받지 않음), 문서 업로드(review-documents), 실행(review-runs)

## 3. 요구사항

### 생성

1. 기업 정보가 없으면 409 `COMPANY_REQUIRED`
2. `free_text`는 앞뒤 공백을 지운 뒤 1~5000자. 비면 422 `EMPTY_INPUT`, 넘으면 422 `TEXT_TOO_LONG`
3. `title`이 없으면 `free_text`의 연속 공백을 하나로 줄인 앞 30자
4. 생성 시점의 기업 정보 버전(`company_profile_version`)과 기본값(업종, 주요 폐기물)을 스냅샷으로 저장함. 주소·연락처 등 식별 정보는 스냅샷에 넣지 않음
5. `overrides`로 보낸 항목은 확인된 값(source=user)이 됨. `null`을 보내면 "모름"으로 기록함

### 입력 객체

6. 항목: `material`, `input_form`, `color`, `contamination`, `quantity_kg`, `generation_process`, `region`, `current_treatment`, `moisture_pct`, `contamination_pct`, `designated_waste`, `has_test_report`. 길이·범위 제한은 AI 엔진 lot 스키마와 같음 (`has_test_report`는 server 전용)
7. 기업 기본값은 **미확인 값**(source=company_profile)으로만 들어감. 주요 폐기물이 정확히 1개면 `material`, 업종이 있으면 `generation_process`. 주요 폐기물이 여러 개면 소재 기본값을 두지 않음 (product-plan 4장: 추정해 채우지 않음)
8. 미확인 값은 사용자가 답해야 확인된 값이 됨. 엔진에는 확인된 값만 보냄 (review-runs)

### 보완 질문 (FR-1.4·1.5)

9. 필수 항목은 `material`, `quantity_kg`. 확인되지 않았거나 "모름"이면 required 질문이 남고 status는 `intake_pending`
10. required 질문이 없으면 status는 `intake_ready`
11. 미확인 기본값마다 "기본값이 맞는지" 질문 (required는 필수 항목일 때만)
12. `has_test_report`에 답하지 않았으면 그 질문을 냄. `false`면 `moisture_pct`, `contamination_pct` 질문, `true`면 `documents`(업로드) 질문
13. `region`에 답하지 않았으면 질문 (모르면 null로 답함)
14. 모순: `contamination_pct`가 0인데 `contamination` 내용이 있으면 required 질문을 냄
15. 질문 순서는 required 먼저, 그다음 항목 순서(6번)

### 답변

16. `answers[]`의 각 항목은 `field`, `value`, `unit`(선택). 같은 항목을 두 번 보내면 422
17. 단위: `quantity_kg`는 `kg`, `t`(1000배 환산), `moisture_pct`·`contamination_pct`는 `%`. 다른 항목에 단위를 보내거나 허용되지 않은 단위면 422
18. 값이 하나라도 바뀌면 `intake_version`이 1 오르고 status를 다시 계산함. 같은 값이면 버전 그대로

### 조회

19. 목록은 내 기업의 검토만, 기본 최신순. `sort`는 `created_at,desc` 또는 `created_at,asc`. 페이지네이션은 company-onboarding 15~17번과 같음
20. 다른 기업의 검토는 404 (존재 여부를 드러내지 않음)
21. `latest_run_id`는 실행이 생기기 전까지 null

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/reviews | access | 검토 생성 | 201 | 401, 409, 422 |
| GET | /api/v1/reviews | access | 검토 목록 | 200 | 401, 409, 422 |
| GET | /api/v1/reviews/{reviewId} | access | 검토 상세 | 200 | 401, 404, 409 |
| GET | /api/v1/reviews/{reviewId}/intake | access | 입력 객체·보완 질문 | 200 | 401, 404, 409 |
| PATCH | /api/v1/reviews/{reviewId}/intake | access | 보완 질문 답변 | 200 | 401, 404, 409, 422 |

**`POST /reviews`**

```json
// 요청
{ "free_text": "사출 공정에서 나온 PP 파쇄품이 월 3톤 정도 나옵니다.", "overrides": { "quantity_kg": 3000 } }
// 응답 201
{ "review_id": "…", "status": "intake_pending", "company_profile_version": 1 }
```

**`GET /reviews/{reviewId}/intake`**

```json
{
  "status": "intake_pending",
  "intake_version": 1,
  "intake": {
    "confirmed": [{ "field": "quantity_kg", "value": 3000, "source": "user" }],
    "unconfirmed": [{ "field": "material", "value": "PP", "source": "company_profile" }]
  },
  "questions": [
    { "field": "material", "reason": "기업 정보의 기본값(PP)이 맞는지 확인이 필요함", "required": true },
    { "field": "has_test_report", "reason": "시험성적서 보유 여부에 따라 이후 확인할 항목이 달라짐", "required": false }
  ]
}
```

**`PATCH /reviews/{reviewId}/intake`**

```json
// 요청
{ "answers": [{ "field": "material", "value": "PP" }, { "field": "quantity_kg", "value": 3, "unit": "t" }] }
// 응답
{ "status": "intake_ready", "intake_version": 2 }
```

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| reviews | id, company_id, title, free_text, status, company_profile_version, company_snapshot(JSON), intake(JSON), intake_version, created_at, updated_at | FK companies (cascade). purge 시 기업보다 먼저 명시적으로 삭제 |

`intake`는 항목 이름 → `{"value", "source", "confirmed"}`. 항목이 없으면 아직 답하지 않은 것, `value`가 null이면 "모름"으로 답한 것.

## 6. 완료 조건

- [x] 기업이 없으면 생성 시 409 COMPANY_REQUIRED
- [x] 생성 시 201, status intake_pending, company_profile_version 1
- [x] 공백만 보내면 422 EMPTY_INPUT, 5001자면 422 TEXT_TOO_LONG
- [x] 기업 기본값(소재 PP, 업종)은 unconfirmed에만 있고 confirmed는 비어 있으며, material·quantity_kg가 required 질문임
- [x] overrides로 소재·물량을 보내면 confirmed에 들어가고 status가 intake_ready
- [x] title이 없으면 free_text 앞 30자
- [x] 답변하면 intake_version 2, 3 t는 3000 kg로 저장
- [x] 같은 값으로 답하면 버전 그대로
- [x] null 답변은 확인된 "모름"으로 기록되고 해당 질문이 사라짐
- [x] 필수 항목을 null로 답하면 intake_pending 유지
- [x] 시험성적서 없음이면 측정값 질문, 있음이면 documents 질문
- [x] 오염도 0%와 오염 내용이 함께 있으면 required 질문으로 intake_pending
- [x] 없는 항목·범위 밖 값·허용되지 않은 단위·타입이 다른 값은 422 VALIDATION_ERROR, 같은 항목 중복도 422
- [x] 목록은 최신순·페이지네이션·asc 정렬, 잘못된 sort는 422
- [x] 다른 기업 사용자는 상세·입력 조회·답변이 404이고 목록에 보이지 않음
- [x] 탈퇴 사용자 purge 시 검토가 삭제됨

## 7. 미정 사항

- 자연어 원문에서 항목을 자동으로 채우는 처리를 누가 할지 (AI 엔진에 입력 정리 엔드포인트가 생기면 미확인 값으로 넣는 방식 제안)
- 사업장 API가 생기면 `site_id`를 받아 사업장 좌표·지역을 기본값으로 넣을지
- 모순 검사 규칙을 더 늘릴지 (현재는 오염도 0%와 오염 내용 1건)
