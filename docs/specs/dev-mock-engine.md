# Spec: AI 없이 백엔드를 검증하는 가짜 엔진 모드

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | review-runs, 엔진 연동 INT-002, team-conventions 1장(레포 사이의 약속은 API 형식뿐임) |
| 관련 todo | T-120 |

## 1. 목적

AI 서버와 프론트 없이 백엔드만으로 MVP API의 입출력과 흐름을 검증함. server는 AI 서버가 아니라 **약속된 응답 형식**에만 의존함.

## 2. 범위

- 포함: 가짜 엔진 모드(`AI_ENGINE_MODE=mock`), 응답·요청의 계약 스냅샷 검사, 로컬 전용 샘플 측정값 API, 운영 차단
- 제외: 실패 상황을 고르는 시나리오(엔진 오류는 pytest로 검증), 실제 AI 서버와의 통합 확인

### 검증되는 것과 안 되는 것

| 검증됨 | 검증 안 됨 |
| --- | --- |
| API 입출력 형식, 인증, 접근 격리 | 실제 판정의 품질 |
| 서버 규칙 (필수 입력, 순서, 물량 비교 등) | 입력에 따라 후보가 달라지는지 (샘플은 고정) |
| 엔진 호출·응답 해석 코드, 비동기 워커 | 실제 AI 서버와의 네트워크·시간 초과 |
| 샘플이 계약 스냅샷의 필수 필드·타입에 맞는지 | 스냅샷 이후 ai 레포의 변경, `dict[str, Any]`인 내부 필드 |

## 3. 요구사항

1. `AI_ENGINE_MODE`는 `http`(기본) 또는 `mock`. 기본값은 항상 실제 엔진임
2. mock은 `EngineClient`를 바꾸지 않고 **HTTP 전송만** `httpx.MockTransport`로 바꿈. 응답 형식 확인과 오류 분류 코드를 그대로 지남
3. 응답은 입력과 무관한 고정 샘플(`app/domains/runs/mock_engine.py`). 테스트도 같은 샘플을 씀
4. `limitations` 첫 항목에 개발용 가짜 응답이라는 문구를 넣음
5. `APP_ENV=prod`에서 mock이면 설정 검증에서 실패해 서버가 시작되지 않음
6. `POST /api/v1/documents/{documentId}/dev-values`: 미검수 샘플 측정값 2개를 넣음. `local`·`test`에서만 경로가 있음. 다른 기업 문서는 404

### 계약 스냅샷

7. `backend/tests/contracts/candidate-research-v1.json`에 ai 레포의 `ResearchRequest`·`ResearchResponse` JSON Schema와 출처 커밋을 저장함
8. 테스트는 샘플 응답, 보내는 lot, `LOT_FIELDS`가 스냅샷에 맞는지 확인함
9. 스냅샷은 자동으로 갱신되지 않음. ai 레포의 스키마를 바꾸는 PR을 server 담당자가 리뷰할 때(team-conventions 1장) 다시 받아 넣음. 그때 테스트가 실패하면 샘플과 `transform.py`를 고침
10. `facility_assessment`, `research_packet`은 엔진 스키마가 `dict[str, Any]`라 스냅샷으로 검사되지 않음. 이 부분의 샘플은 ai 레포 코드(`knowledge_graph/facility_assessment.py`)를 보고 맞춘 것임

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/documents/{documentId}/dev-values | access | 샘플 측정값 넣기 (로컬 전용) | 201 | 401, 404, 409 |

## 5. 데이터

새 테이블 없음. 환경변수 `AI_ENGINE_MODE`(기본 `http`).

## 6. 완료 조건

- [x] mock이면 AI 서버 없이 실행이 completed가 되고 limitations에 가짜 응답 표시가 있음
- [x] 기본값은 http이고, prod에서 mock이면 설정 검증이 실패함
- [x] 샘플 응답과 lot이 계약 스냅샷에 맞고, lot 항목이 계약에 모두 있음
- [x] prod에는 dev-values 경로가 없음
- [x] 샘플 측정값을 넣고 검수할 수 있고, 다른 기업 문서는 404
- [x] 실행, 후보, 리스크 결정, 증빙, 재실행, 비교까지 mock으로 이어짐
- [x] 입력이 달라도 mock 후보는 같음 (고정 샘플임을 드러내는 테스트)

## 7. 미정 사항

- 스냅샷 갱신을 ai 레포 CI로 자동화할지
- Swagger에서 엔진 실패 상황을 고를 수 있게 할지
