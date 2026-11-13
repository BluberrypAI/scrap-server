# Spec: 공통 오류 응답 형식

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | API 명세 에러 열(AUTH_REQUIRED, VALIDATION_ERROR 등), team-conventions 1장(API 형식) |
| 관련 todo | T-109 |

## 1. 목적

모든 API의 오류를 같은 형식으로 반환해, 프론트엔드가 상태 코드만이 아니라 **오류 코드**로 오류 종류를 구분할 수 있게 함 (예: 409 중 `VERSION_CONFLICT`와 `COMPANY_ALREADY_EXISTS` 구분).

## 2. 범위

- 포함: 오류 응답 본문 형식, 오류 코드 목록, 요청 검증 오류(422)·없는 경로(404)·허용되지 않은 메서드(405)·처리되지 않은 예외(500)의 변환, 기존 API 전체 적용
- 제외: 오류 메시지 다국어 처리, 오류 추적 ID, 리디렉션으로 오류를 알리는 OAuth 콜백(`/login?error=...`는 그대로)

## 3. 요구사항

1. 모든 오류 응답 본문은 `{"code", "message", "details"}` 형식임
   - `code`: 대문자 스네이크 케이스 오류 코드. 프론트엔드는 이 값으로 분기함
   - `message`: 사람이 읽는 한국어 설명. 화면에 그대로 보여주는 용도가 아니며 바뀔 수 있음
   - `details`: 요청 검증 오류(422)일 때만 `[{"field", "message"}]` 배열, 그 외에는 `null`
2. 요청 검증 오류는 422 `VALIDATION_ERROR`임. `details[].field`는 위치를 점으로 이은 문자열임 (예: `body.contact.name`, `query.pageSize`)
3. 없는 경로는 404 `NOT_FOUND`, 허용되지 않은 메서드는 405 `METHOD_NOT_ALLOWED`임
4. 처리되지 않은 예외는 500 `INTERNAL_ERROR`이며, 예외 내용은 응답에 넣지 않고 서버 로그에만 남김
5. 401 응답은 `WWW-Authenticate: Bearer` 헤더를 유지함
6. 오류 코드는 추가만 할 수 있음. 이미 쓰는 코드의 이름·의미를 바꾸려면 프론트엔드와 합의함 (team-conventions 1장)
7. 기능별 오류 코드(예: 사업장의 `SITE_IN_USE`)는 해당 기능 spec에 적고 아래 목록에 추가함

## 4. 오류 코드

| HTTP | 코드 | 발생 |
| --- | --- | --- |
| 401 | `AUTH_REQUIRED` | 토큰 없음·잘못됨·만료, 탈퇴 사용자, refresh 토큰 없음·잘못됨 |
| 403 | `ACCOUNT_WITHDRAWN` | 탈퇴 처리 중인 사용자의 개발용 로그인 |
| 404 | `NOT_FOUND` | 없는 경로, 등록되지 않은 기업 |
| 404 | `UNSUPPORTED_PROVIDER` | 지원하지 않는 소셜 로그인 제공자 |
| 405 | `METHOD_NOT_ALLOWED` | 경로는 있으나 메서드가 다름 |
| 409 | `COMPANY_ALREADY_EXISTS` | 기업이 있는 사용자가 다시 등록 |
| 409 | `VERSION_CONFLICT` | 기업 수정 시 profile_version 불일치 |
| 400 | `VALIDATION_ERROR` | 요청 본문을 JSON으로 읽을 수 없음 (예: UTF-8이 아닌 본문) |
| 422 | `VALIDATION_ERROR` | 요청 본문·쿼리·경로 값 검증 실패 |
| 422 | `INVALID_FILTER` | 지원하지 않는 문진 유형이거나 유형과 답변이 맞지 않음 (처리 경로 데모) |
| 500 | `INTERNAL_ERROR` | 처리되지 않은 서버 오류 |
| 503 | `PROVIDER_NOT_CONFIGURED` | 클라이언트 ID가 설정되지 않은 소셜 로그인 제공자 |
| 503 | `ENGINE_UNAVAILABLE` | 문진 엔진 주소(CLASSIFICATION_BASE_URL, DIAGNOSIS_ENGINE_URL)가 없거나 연결하지 못함, 엔진 인증 실패·5xx·시간 초과 |
| 404 | `CASE_NOT_FOUND` | 문진 건이 없거나 다른 기업의 건 ([diagnosis-engine-integration.md](diagnosis-engine-integration.md)) |
| 404 | `DOCUMENT_NOT_FOUND` | 그 문진 건에 없는 서류 |
| 409 | `CASE_NOT_DIAGNOSABLE` | 확정된 건에 답변·서류 등. 다시 열기(reopen) 후 진행 |
| 409 | `ALREADY_CONFIRMED` | 이미 확정한 건을 다시 확정 |
| 409 | `NOT_CONFIRMABLE` | 확정 조건을 아직 채우지 못함 |
| 409 | `NOT_REOPENABLE` | 확정되지 않은 건을 다시 열기 |
| 409 | `CODE_MISMATCH` | 확정 요청의 `expected_code`가 엔진 재평가 결론과 다름 |
| 409 | `CONCURRENT_UPDATE` | 같은 건을 다른 요청이 먼저 갱신. 다시 조회 후 재시도 |
| 409 | `KB_CHANGED` | 판정 규칙 버전이 바뀜. rebase 후 다시 요청 |
| 409 | `DOCUMENT_VERSION_MISMATCH` | 서류 파일이 교체됨. 최신 버전으로 다시 검수 |
| 413 | `FILE_TOO_LARGE` | 업로드 파일 크기 초과 (엔진 기본 10MB) |
| 415 | `UNSUPPORTED_DOCUMENT` | 지원하지 않는 서류 형식 |

**예시**

```json
// 409
{ "code": "VERSION_CONFLICT", "message": "다른 곳에서 먼저 수정됨. 다시 조회한 뒤 수정해야 함", "details": null }

// 422
{
  "code": "VALIDATION_ERROR",
  "message": "요청 값이 올바르지 않음",
  "details": [{ "field": "body.site_facilities", "message": "List should have at least 1 item after validation, not 0" }]
}
```

## 5. 데이터

없음.

## 6. 완료 조건

- [x] 토큰 없이 인증 API를 호출하면 401과 `AUTH_REQUIRED`, `WWW-Authenticate: Bearer` 헤더를 반환함
- [x] 요청 검증 실패는 422 `VALIDATION_ERROR`와 `details[].field`(예: `body.contact.name`)를 반환함
- [x] 없는 경로는 404 `NOT_FOUND`, 허용되지 않은 메서드는 405 `METHOD_NOT_ALLOWED`를 반환함
- [x] 기업이 없을 때 GET /companies/me는 404 `NOT_FOUND`를 반환함
- [x] 기업을 다시 등록하면 409 `COMPANY_ALREADY_EXISTS`, 버전이 다르면 409 `VERSION_CONFLICT`를 반환함
- [x] 지원하지 않는 제공자는 404 `UNSUPPORTED_PROVIDER`를 반환함
- [x] 처리되지 않은 예외는 500 `INTERNAL_ERROR`를 반환하고 예외 메시지를 응답에 넣지 않음
- [x] 모든 오류 응답에 code, message, details 키가 있음

## 7. 미정 사항

- 오류 추적 ID(요청 ID)를 응답과 로그에 함께 넣을지
