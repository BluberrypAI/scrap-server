# Spec: 소셜 로그인

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | product-plan 3장, ADR 0001 |
| 관련 todo | T-002, T-003, T-007, T-107 |

## 1. 목적

별도 가입 절차 없이 Google 또는 Microsoft 계정으로 로그인하고, 첫 로그인 시 계정을 자동 생성함. 로그인 상태는 서버가 관리하는 refresh 토큰으로 유지하고, 로그아웃 시 서버에서 무효화함.

## 2. 범위

- 포함: Google OIDC, Microsoft Entra ID(`common` 테넌트: 개인 Outlook 계정과 회사·학교 계정), JWT 쿠키 발급, refresh 토큰 회전·폐기, 로그아웃, 현재 사용자 조회
- 제외: 이메일·비밀번호 가입, 계정 병합(같은 이메일의 Google·MS 계정은 별개 사용자), 프론트엔드가 인가 코드를 받아 서버에 넘기는 방식, 토큰을 응답 본문으로 주는 방식(개발용 로그인 제외), 공통 오류 응답 형식([error-response.md](error-response.md))
- 탈퇴는 [account-withdrawal.md](account-withdrawal.md)

## 3. 요구사항

### 로그인

1. 서버가 OAuth 흐름 전체를 처리함 (BFF 방식). 프론트엔드는 `/api/v1/auth/{provider}/login`으로 이동시키기만 함
2. 사용자는 이메일이 아니라 `(provider, provider_subject)`로 식별함. MS 계정은 email 클레임이 비어 있거나 바뀔 수 있음
3. 첫 로그인이면 `users`를 (provider, provider_subject)와 함께 생성하고, 이후에는 기존 사용자를 사용함. 사용자당 로그인 수단은 하나임 (db-schema-simplify)
4. 로그인 성공 후 기업 프로필이 없으면 `{FRONTEND_URL}/onboarding`, 있으면 `{FRONTEND_URL}/`로 이동함
5. OAuth 실패 시 `{FRONTEND_URL}/login?error=oauth_failed`로 이동함
6. 탈퇴 처리 중인 사용자가 로그인하면 쿠키를 발급하지 않고 `{FRONTEND_URL}/login?error=account_withdrawn`으로 이동함
7. Microsoft `common` 엔드포인트의 id_token 발급자는 `https://login.microsoftonline.com/{tid}/v2.0` 형식으로 검증함
8. 클라이언트 ID가 설정되지 않은 제공자는 503을 반환함

### 토큰

9. 토큰은 httpOnly 쿠키로 전달함: `access_token`(30분, path `/`), `refresh_token`(14일, path `/api/v1/auth`). 쿠키 도메인·Secure·SameSite는 환경변수로 설정함
10. API 호출 시 `access_token` 쿠키 또는 `Authorization: Bearer` 헤더를 허용함
11. refresh 토큰은 발급할 때마다 `refresh_tokens` 테이블에 기록하고, JWT의 `jti`에 그 행의 id를 넣음
12. `/auth/refresh`는 **회전** 방식임: 유효한 refresh 토큰이면 그 토큰을 폐기하고 access·refresh 토큰을 새로 발급함
13. 이미 폐기된 refresh 토큰이 다시 쓰이면 탈취로 보고 그 사용자의 유효한 refresh 토큰을 모두 폐기하고 401을 반환함
14. DB에 없는 jti, 만료된 토큰, 탈퇴 처리 중인 사용자의 refresh 토큰은 401을 반환함
15. access 토큰은 DB에 기록하지 않음. 폐기된 세션의 access 토큰도 만료(최대 30분)까지는 유효함. 단 탈퇴 처리 중인 사용자의 access 토큰은 즉시 401임
16. 프론트엔드는 `/auth/refresh`를 동시에 여러 번 호출하지 않음. 동시에 호출하면 두 번째 요청이 재사용으로 판정되어 로그아웃됨

### 로그아웃

17. `/auth/logout`은 인증을 요구하지 않음. access 토큰이 만료된 상태에서도 로그아웃할 수 있어야 하기 때문임
18. refresh 쿠키가 유효하면 그 토큰을 폐기함. 쿠키가 없거나 잘못됐어도 오류 없이 쿠키를 지우고 204를 반환함

### 현재 사용자

19. `/users/me`는 `id, email, name, provider, company_id`를 반환함. 기업이 없으면 `company_id`는 null
20. 이전 응답의 `has_company`는 제거함 (`company_id`로 대체. frontend 미구현 상태에서 사용자 결정, 2026-10-22)

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| GET | /api/v1/auth/{provider}/login | - | 제공자 동의 화면으로 이동 (provider: google, microsoft) | 302 | 404 미지원, 503 미설정 |
| GET | /api/v1/auth/{provider}/callback | - | 토큰 교환, 사용자 생성·조회, 쿠키 발급 | 302 | 302 (`error=oauth_failed`, `error=account_withdrawn`) |
| POST | /api/v1/auth/refresh | refresh 쿠키 | refresh 토큰 회전, access·refresh 재발급 | 204 | 401 |
| POST | /api/v1/auth/logout | - | refresh 토큰 폐기, 쿠키 삭제 | 204 | - |
| GET | /api/v1/users/me | access | 현재 사용자, 제공자, 기업 ID | 200 | 401 |

**`GET /users/me` 응답**

```json
{
  "id": "7bd91094-c946-4040-8469-a0110c4d5a44",
  "email": "kim@outlook.com",
  "name": "김담당",
  "provider": "microsoft",
  "company_id": null
}
```

**제공자 콘솔에 등록할 리디렉션 URI (로컬)**

- Google: `http://localhost:8000/api/v1/auth/google/callback`
- Microsoft: `http://localhost:8000/api/v1/auth/microsoft/callback` (플랫폼: 웹, 지원 계정 유형: 모든 조직 디렉터리 및 개인 Microsoft 계정)

### 개발용 로그인 (로컬 전용)

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/auth/dev-login | - | OAuth 키 없이 개발용 사용자로 로그인. 쿠키 설정과 함께 access 토큰을 응답 본문으로도 반환 (Swagger Authorize·curl용) | 200 | 403 탈퇴 처리 중, 422 |

- `APP_ENV`가 `local` 또는 `test`일 때만 라우트를 등록함. `prod`에서는 경로 자체가 없음(404)
- provider는 `dev`, provider_subject는 요청의 email. 같은 email로 다시 호출하면 같은 사용자를 사용함
- 토큰을 응답 본문에 담는 것은 이 엔드포인트만의 예외임
- refresh 토큰도 일반 로그인과 같이 DB에 기록함

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| users | id, provider, provider_subject, email, name, withdrawn_at, deletion_scheduled_at, created_at, updated_at | (provider, provider_subject) unique. email은 nullable, unique 아님. 탈퇴 필드는 [account-withdrawal.md](account-withdrawal.md) |
| refresh_tokens | id(= JWT jti), user_id, expires_at, revoked_at, created_at, updated_at | user_id FK(users, CASCADE), index. revoked_at이 null이면 유효 |

## 6. 완료 조건

### 로그인

- [x] 처음 로그인한 제공자 계정은 provider 정보를 가진 사용자 1명을 생성함
- [x] 같은 제공자 계정으로 다시 로그인하면 새 사용자를 만들지 않음
- [x] 콜백 성공 시 access·refresh 쿠키를 설정하고, 기업이 없으면 /onboarding으로 이동함
- [x] 콜백 성공 시 refresh_tokens에 행이 1개 생김
- [x] 탈퇴 처리 중인 사용자가 콜백에 도달하면 쿠키 없이 /login?error=account_withdrawn으로 이동함
- [x] 지원하지 않는 제공자는 404를 반환함
- [x] Microsoft 발급자 검증은 tid와 일치하는 발급자만 통과시킴

### 토큰

- [x] refresh 토큰으로 /auth/refresh를 호출하면 204와 함께 새 access·refresh 쿠키를 설정하고, 이전 refresh 토큰은 폐기됨
- [x] 회전으로 폐기된 refresh 토큰을 다시 쓰면 401을 반환하고, 그 사용자의 유효한 refresh 토큰이 모두 폐기됨
- [x] DB에 없는 jti의 refresh 토큰은 401을 반환함
- [x] access 토큰을 refresh에 쓰면 401을 반환함
- [x] refresh 토큰을 access로 쓰면 401을 반환함

### 로그아웃

- [x] 로그아웃하면 refresh 토큰이 폐기되고, 그 토큰으로 /auth/refresh를 호출하면 401을 반환함
- [x] refresh 쿠키 없이 로그아웃해도 204를 반환함

### 현재 사용자

- [x] 토큰 없이 /users/me를 호출하면 401을 반환함
- [x] /users/me는 provider와 company_id를 반환하고, 기업이 없으면 company_id가 null임
- [x] 기업을 등록한 뒤 /users/me의 company_id는 등록한 기업 id와 같음

### 개발용 로그인

- [x] 개발용 로그인은 토큰을 반환하고, 그 토큰으로 /users/me를 호출할 수 있음
- [x] 같은 email로 개발용 로그인을 반복해도 사용자는 1명임
- [x] APP_ENV=prod 앱에는 개발용 로그인 경로가 없음

## 7. 미정 사항

- 프론트엔드 도메인 확정 시 쿠키 도메인·SameSite 값. 프론트와 API를 같은 상위 도메인(또는 같은 도메인 아래 `/api`)에 두는 것을 전제로 함. 완전히 다른 도메인이면 브라우저의 제3자 쿠키 차단으로 로그인이 유지되지 않을 수 있음
- 오래된 refresh_tokens 행(만료·폐기) 정리 주기
