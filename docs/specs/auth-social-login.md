# Spec: 소셜 로그인

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | product-plan 3장, ADR 0001 |
| 관련 todo | T-002, T-003, T-007 |

## 1. 목적

별도 가입 절차 없이 Google 또는 Microsoft 계정으로 로그인하고, 첫 로그인 시 계정을 자동 생성함.

## 2. 범위

- 포함: Google OIDC, Microsoft Entra ID(`common` 테넌트: 개인 Outlook 계정과 회사·학교 계정), JWT 쿠키 발급·갱신·삭제, 현재 사용자 조회
- 제외: 이메일·비밀번호 가입, 계정 병합(같은 이메일의 Google·MS 계정은 별개 사용자), 탈퇴

## 3. 요구사항

1. 사용자는 이메일이 아니라 `(provider, provider_subject)`로 식별함. MS 계정은 email 클레임이 비어 있거나 바뀔 수 있음
2. 첫 로그인이면 `users`와 `social_accounts`를 생성하고, 이후에는 기존 사용자를 사용함
3. 토큰은 httpOnly 쿠키로 전달함: `access_token`(30분), `refresh_token`(14일). 쿠키 도메인·Secure·SameSite는 환경변수로 설정함
4. API 호출 시 `access_token` 쿠키 또는 `Authorization: Bearer` 헤더를 허용함
5. 로그인 성공 후 기업 프로필이 없으면 `{FRONTEND_URL}/onboarding`, 있으면 `{FRONTEND_URL}/`로 이동함
6. OAuth 실패 시 `{FRONTEND_URL}/login?error=oauth_failed`로 이동함
7. Microsoft `common` 엔드포인트의 id_token 발급자는 `https://login.microsoftonline.com/{tid}/v2.0` 형식으로 검증함
8. 클라이언트 ID가 설정되지 않은 제공자는 503을 반환함

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| GET | /api/v1/auth/{provider}/login | - | 제공자 동의 화면으로 이동 (provider: google, microsoft) | 302 | 404 미지원, 503 미설정 |
| GET | /api/v1/auth/{provider}/callback | - | 토큰 교환, 사용자 생성·조회, 쿠키 발급 | 302 | 302 (error) |
| POST | /api/v1/auth/refresh | refresh 쿠키 | access 토큰 재발급 | 204 | 401 |
| POST | /api/v1/auth/logout | - | 쿠키 삭제 | 204 | - |
| GET | /api/v1/users/me | access | 현재 사용자, 기업 등록 여부 | 200 | 401 |

**제공자 콘솔에 등록할 리디렉션 URI (로컬)**

- Google: `http://localhost:8000/api/v1/auth/google/callback`
- Microsoft: `http://localhost:8000/api/v1/auth/microsoft/callback` (플랫폼: 웹, 지원 계정 유형: 모든 조직 디렉터리 및 개인 Microsoft 계정)

### 개발용 로그인 (로컬 전용)

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/auth/dev-login | - | OAuth 키 없이 개발용 사용자로 로그인. 쿠키 설정과 함께 access 토큰을 응답 본문으로도 반환 (Swagger Authorize·curl용) | 200 | 422 |

- `APP_ENV`가 `local` 또는 `test`일 때만 라우트를 등록함. `prod`에서는 경로 자체가 없음(404)
- provider는 `dev`, provider_subject는 요청의 email. 같은 email로 다시 호출하면 같은 사용자를 사용함
- 토큰을 응답 본문에 담는 것은 이 엔드포인트만의 예외임

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| users | id, email, name, created_at, updated_at | email은 nullable, unique 아님 |
| social_accounts | id, user_id, provider, provider_subject, email, created_at, updated_at | (provider, provider_subject) unique |

## 6. 완료 조건

- [x] 처음 로그인한 제공자 계정은 사용자 1명과 소셜 계정 1개를 생성함
- [x] 같은 제공자 계정으로 다시 로그인하면 새 사용자를 만들지 않음
- [x] 콜백 성공 시 access·refresh 쿠키를 설정하고, 기업이 없으면 /onboarding으로 이동함
- [x] 지원하지 않는 제공자는 404를 반환함
- [x] 토큰 없이 /users/me를 호출하면 401을 반환함
- [x] refresh 토큰으로 access 토큰을 재발급하고, access 토큰을 refresh에 쓰면 401을 반환함
- [x] Microsoft 발급자 검증은 tid와 일치하는 발급자만 통과시킴
- [x] 개발용 로그인은 토큰을 반환하고, 그 토큰으로 /users/me를 호출할 수 있음
- [x] 같은 email로 개발용 로그인을 반복해도 사용자는 1명임
- [x] APP_ENV=prod 앱에는 개발용 로그인 경로가 없음

## 7. 미정 사항

- 프론트엔드 도메인 확정 시 쿠키 도메인·SameSite 값 (다른 도메인이면 `SameSite=None; Secure` 필요)
- refresh 토큰 폐기(로그아웃 시 서버 측 무효화) 필요 여부
