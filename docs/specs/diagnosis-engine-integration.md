# Spec: 문진 엔진(resource_engine) 연동

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | SCRAP 기획서 문진(폐기물 분류번호 판정) 단계 |
| 관련 todo | T-130 |

## 1. 목적

팀 문진 엔진(BluberrypAI/resource_engine, waste-diagnosis)을 별도 서비스로 두고, 로그인한 기업이 server를 거쳐서만 문진을 쓰게 함. 엔진은 자체 DB에 건·사실 이력·판정을 저장하고, server는 인증과 기업 격리를 맡음.

엔진 쪽 규약 원본: resource_engine `docs/api/server-engine-contract.md`, `docs/handoff-contract.md`, `docs/api/openapi.json`, 요약 `docs/api/engine-api-summary.md`.

팀 API 명세서의 엔진 내부 API(INT-001~017)는 엔진 요약 문서 기준으로 바뀜: 경로는 `/internal/v1/...`, 비동기 실행(runs, 202) 대신 답변마다 다음 질문이나 결과가 바로 오는 동기 방식, 서류 값 자동 추출(INT-008)과 INT-009~017은 엔진에 아직 없음.

## 2. 범위

- 포함
  - 엔진 `/internal/v1` 호출 클라이언트 (Bearer `ENGINE_SERVICE_TOKEN` + `X-Company-Id`)
  - 로그인한 기업용 문진 API `/api/v1/diagnosis/*` (엔진 경로를 1:1로 중계)
  - 엔진 오류를 공통 오류 형식으로 변환
  - 탈퇴 purge 때 엔진의 기업 데이터 삭제 호출
  - docker compose에 엔진과 엔진 DB 추가 (선택 프로필 `engine`)
- 제외
  - 엔진 코드 수정, 엔진 배포 (T-502)
  - 기업 정보 → 엔진 확인된 사실(`confirmed_facts`) 매핑. 기업 정보 확인 화면이 생기면 함
  - 서류 자동 읽기(OCR, T-117)
  - 처리 경로(treatment)와의 연결. 7장 참고

## 3. 요구사항

1. 모든 `/api/v1/diagnosis/*`는 로그인이 필요함. 기업을 등록하지 않은 사용자는 404 `NOT_FOUND`
2. server는 엔진에 `X-Company-Id = companies.id`(UUID 문자열)를 보냄. 브라우저가 보낸 기업 ID는 쓰지 않음. 엔진은 처음 보는 ID면 기업 행을 자동으로 만듦
3. 요청·응답 본문은 엔진 규약을 그대로 따름. 단, 아래는 server가 정함
   - 건 생성·문진 답변에서 `confirmed_facts`, `company_profile_version`은 받지 않음 (엔진이 "server가 확인한 값"으로 믿는 필드라 브라우저 입력을 그대로 넘기면 안 됨)
   - 서류 값 적용(`values/apply`)의 `reviewer`는 현재 사용자 ID, `reviewed_at`은 server 시각으로 채움. 브라우저가 보낸 값은 무시함
4. 엔진 오류는 같은 HTTP 상태와 엔진의 오류 코드로 돌려줌 (`{code, message, details}`). 엔진 코드 중 프론트가 분기할 것은 오류 코드 목록에 추가함 (4장 표)
   - 서류 값 형식 오류(`details.problems[{key, reason}]`)는 `details[{field: key, message: reason}]`으로 바꿈. 다른 `details`는 버림
   - 엔진 인증 실패(401·`COMPANY_REQUIRED`·`ENDPOINT_DISABLED`), 엔진 5xx, 연결 실패·시간 초과, 주소 미설정은 모두 503 `ENGINE_UNAVAILABLE`. 원인은 server 로그에만 남김
   - 표에 없는 엔진 코드는 HTTP 상태로 처리함 (404 → `NOT_FOUND`, 400·422 → `VALIDATION_ERROR`, 그 외 → 503 `ENGINE_UNAVAILABLE`)
5. 응답 본문은 엔진 것을 가공하지 않고 돌려줌. 엔진이 필드를 추가해도 server를 고치지 않음 (예: 엔진 `feat/interview-assist`의 턴 응답 `assist`, `ui.question.guide`, 사실의 `hedged`)
6. 엔진 호출 제한 시간은 `DIAGNOSIS_ENGINE_TIMEOUT_SECONDS` (기본 200초). 엔진 모델 대기 × 추출·응답 각 최대 2회 + 규칙·DB 여유보다 길어야 함. 운영은 모델 40초(4회 160초)에 200초, 로컬 compose는 모델 60초(240초)에 300초. 운영 값은 App Service 요청 상한(약 230초)과 Front Door 출처 응답 대기(240초)보다 짧게 둠. 이전 값 30초는 2026-11-17 동시 문진 시험에서 시간 초과(503)가 나서 바꿈
7. 서류 업로드는 multipart를 그대로 넘김 (`file`, 선택 `facts`). 크기 제한은 엔진이 검사함. server는 메모리 보호용으로 20MB를 넘으면 먼저 413 `FILE_TOO_LARGE`
8. 경로의 건·서류 ID는 `^[A-Za-z0-9_-]{1,64}$`만 받음 (다른 값은 422, 엔진을 부르지 않음)
9. 탈퇴 purge: 기업을 지우기 전에 엔진 `DELETE /internal/v1/companies/{company_id}/data`를 부름. 실패하면 그 사용자는 이번에 지우지 않고 다음 purge에서 다시 시도함. 엔진 주소가 설정되지 않았으면 엔진 삭제를 건너뛰고 경고 로그를 남김
10. 환경변수: `DIAGNOSIS_ENGINE_URL`(예: `http://localhost:8030`), `ENGINE_SERVICE_TOKEN`(엔진과 같은 값). prod에서 URL이 있는데 토큰이 비어 있으면 시작하지 않음

## 4. API

모두 인증 필요. `{id}`는 엔진의 건 ID, `{doc}`는 서류 ID.

| 메서드 | 경로 | 엔진 경로 (`/internal/v1` 뒤) | 성공 |
| --- | --- | --- | --- |
| POST | `/api/v1/diagnosis/cases` | `POST /cases` `{memo?, quantity?, unit?, period?}` | 201 `{case, turn}` |
| GET | `/api/v1/diagnosis/cases?status=&page=&size=` | `GET /cases` | 200 `{items, pagingInfo}` |
| GET | `/api/v1/diagnosis/cases/{id}` | `GET /cases/{id}` | 200 상세 (`handoff` 포함) |
| POST | `/api/v1/diagnosis/cases/{id}/messages` | `POST /cases/{id}/diagnosis/messages` `{text}` 또는 `{quick_reply}` | 200 `TurnResponse` |
| POST | `/api/v1/diagnosis/cases/{id}/documents` | `POST /cases/{id}/documents` (multipart) | 201 |
| POST | `/api/v1/diagnosis/cases/{id}/documents/{doc}/versions` | 같은 경로 (multipart) | 201 |
| POST | `/api/v1/diagnosis/cases/{id}/documents/{doc}/values/apply` | 같은 경로 | 200 `TurnResponse` |
| POST | `/api/v1/diagnosis/cases/{id}/documents/{doc}/revoke` | 같은 경로 | 200 `TurnResponse` |
| POST | `/api/v1/diagnosis/cases/{id}/confirm` | 같은 경로 `{expected_code?}` | 200 `{case, verdict, handoff, …}` |
| POST | `/api/v1/diagnosis/cases/{id}/reopen` | 같은 경로 `{reason?}` | 200 |
| POST | `/api/v1/diagnosis/cases/{id}/rebase` | 같은 경로 | 200 `TurnResponse` |
| GET | `/api/v1/diagnosis/cases/{id}/trace` | 같은 경로 | 200 |
| GET | `/api/v1/diagnosis/catalog/facts` | `GET /catalog/facts` | 200 |

추가하는 오류 코드 (엔진 코드 그대로):

| HTTP | 코드 | 발생 |
| --- | --- | --- |
| 404 | `CASE_NOT_FOUND` | 건이 없거나 다른 기업의 건 |
| 404 | `DOCUMENT_NOT_FOUND` | 그 건에 없는 서류 |
| 409 | `CASE_NOT_DIAGNOSABLE` | 확정된 건에 답변·서류 등 (reopen 후 진행) |
| 409 | `ALREADY_CONFIRMED` | 이미 확정한 건을 다시 확정 |
| 409 | `NOT_CONFIRMABLE` | 확정 조건을 아직 채우지 못함 |
| 409 | `NOT_REOPENABLE` | 확정되지 않은 건을 reopen |
| 409 | `CODE_MISMATCH` | `expected_code`가 재평가 결론과 다름 |
| 409 | `CONCURRENT_UPDATE` | 다른 요청이 먼저 갱신. 다시 조회 후 재시도 |
| 409 | `KB_CHANGED` | 규칙 버전이 바뀜. rebase 후 진행 |
| 409 | `DOCUMENT_VERSION_MISMATCH` | 서류 파일이 교체됨. 최신 버전으로 다시 검수 |
| 413 | `FILE_TOO_LARGE` | 업로드 크기 초과 (엔진 기본 10MB) |
| 415 | `UNSUPPORTED_DOCUMENT` | 지원하지 않는 서류 형식 |

## 5. 데이터

server DB 변경 없음. 건·사실 이력·판정·Trace는 엔진 DB(`scrap_engine`)에 있음. DB 간 조인 없이 API로만 주고받음 (db-schema-simplify 저장소 구성).

로컬 compose: `docker compose --profile engine up -d --build`로 `engine`(포트 8030)과 `engine-db`(PostgreSQL, 호스트 포트 55432)를 함께 띄움. 엔진 소스 위치는 `ENGINE_REPO_DIR`(기본 `../resource_engine`). 두 서비스의 `ENGINE_SERVICE_TOKEN` 기본값은 `local-engine-token`으로 같음.

ERD v2의 `wastes`(폐기물 건)와 엔진 건을 잇는 것은 이 spec에 넣지 않음 (7장).

## 6. 완료 조건

- [x] 로그인하지 않으면 `/api/v1/diagnosis/cases`가 401 `AUTH_REQUIRED`
- [x] 기업이 없는 사용자는 404 `NOT_FOUND`이고 엔진을 부르지 않음
- [x] 건 생성 시 엔진에 `Authorization: Bearer <토큰>`, `X-Company-Id: <companies.id>`가 가고, 본문의 `confirmed_facts`·`company_profile_version`은 빠짐
- [x] 엔진 응답의 상태 코드와 본문을 그대로 돌려줌 (201 건 생성, 200 목록의 `pagingInfo`)
- [x] 목록 쿼리(`status`, `page`, `size`)가 엔진에 전달됨
- [x] 값 적용 시 `reviewer`가 현재 사용자 ID, `reviewed_at`이 server 시각으로 바뀜
- [x] 서류 업로드 multipart가 파일 내용과 `facts` 그대로 엔진에 전달됨
- [x] 엔진 409 `KB_CHANGED`는 409 `KB_CHANGED`로, 서류 값 형식 오류 422는 `details[{field, message}]`로 바뀜
- [x] 엔진 401·5xx·연결 실패·주소 미설정은 503 `ENGINE_UNAVAILABLE`
- [x] purge 때 엔진 기업 데이터 삭제를 부르고, 실패하면 그 사용자와 기업이 남음
- [x] prod에서 `DIAGNOSIS_ENGINE_URL`만 있고 `ENGINE_SERVICE_TOKEN`이 없으면 설정 오류

## 7. 미정 사항

- **처리 경로(treatment)의 R코드 연결**: 지금 `/api/treatment/next-step`은 `classification_session_id`로 엔진의 옛 API(`/api/classification/sessions/{id}/record`)에서 재활용 유형(R코드)을 읽음. 엔진 develop에는 이 API가 없고, 새 인계 객체(`diagnosis-handoff-v1`)에는 R코드가 없음. 재활용 유형을 엔진이 인계 객체에 넣을지, server가 분류번호로 찾을지 treatment 담당자·엔진 담당자와 정해야 함. 그때까지 `/api/classification/*` 중계와 treatment 코드는 건드리지 않음
- 브라우저가 기업 정보를 확인한 값(`confirmed_facts`)을 보내는 흐름
- 엔진 확정 결과(handoff)를 server `wastes`에 복사하는 시점과 매핑 (문진 건 1개 = 폐기물 건 1개로 볼지)
- 엔진 목록 페이징 형식(`pagingInfo{currentPageNumber, pageSize, totalCount, totalPages}`)은 server 기업 이력 형식(`elementCount`, `totalPageCount`)과 다름. 엔진이 팀 형식으로 맞출 예정이라 server는 그대로 넘김
- 운영 배포 위치(엔진 컨테이너, `scrap_engine` DB 계정)는 T-502에서 정함
