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
| 409 | `COMPANY_REQUIRED` | 기업 정보 없이 검토 API 호출 |
| 422 | `VALIDATION_ERROR` | 요청 본문·쿼리·경로 값 검증 실패 |
| 422 | `EMPTY_INPUT` | 검토 생성 시 상황 설명이 비어 있음 |
| 422 | `TEXT_TOO_LONG` | 검토 생성 시 상황 설명이 5000자 초과 |
| 500 | `INTERNAL_ERROR` | 처리되지 않은 서버 오류 |
| 503 | `PROVIDER_NOT_CONFIGURED` | 클라이언트 ID가 설정되지 않은 소셜 로그인 제공자 |

**예시**

```json
// 409
{ "code": "VERSION_CONFLICT", "message": "다른 곳에서 먼저 수정됨. 다시 조회한 뒤 수정해야 함", "details": null }

// 422
{
  "code": "VALIDATION_ERROR",
  "message": "요청 값이 올바르지 않음",
  "details": [{ "field": "body.business_registration_no", "message": "Value error, 사업자등록번호는 숫자 10자리여야 함" }]
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
