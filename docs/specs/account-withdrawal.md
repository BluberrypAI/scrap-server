# Spec: 회원 탈퇴

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | 사용자 요청 (2026-10-22, API 명세 AUTH-002). product-plan 3장 회원 범위에 탈퇴 추가 필요 (사람이 수정) |
| 관련 todo | T-108 |

## 1. 목적

사용자가 직접 탈퇴할 수 있게 함. 탈퇴하면 즉시 서비스 이용을 막고, 유예 기간이 지나면 개인정보와 기업 정보를 삭제함.

## 2. 범위

- 포함: 탈퇴 요청, 즉시 비활성화와 세션 폐기, 유예 기간 중 로그인 차단, 유예 기간이 지난 사용자 삭제 함수와 실행 명령
- 제외: 탈퇴 철회(복구), 삭제 작업의 자동 스케줄 등록(배포 시 infra에서 설정), 탈퇴 사유 수집, 개인정보 처리방침 문서

## 3. 요구사항

1. `POST /api/v1/users/me/withdraw`는 본문 `{"confirm": true}`가 있어야 처리함. 없거나 `false`면 422
2. 탈퇴하면 `users.withdrawn_at`을 현재 시각으로, `deletion_scheduled_at`을 `withdrawn_at + WITHDRAWAL_GRACE_DAYS`(기본 30일)로 기록함
3. 탈퇴하면 그 사용자의 refresh 토큰을 모두 폐기하고, 응답에서 인증 쿠키를 삭제함
4. 탈퇴 처리 중인 사용자는 access 토큰이 남아 있어도 모든 인증 API에서 401을 받음. 따라서 탈퇴를 두 번 요청하면 두 번째는 401임 (API 명세의 409 ALREADY_WITHDRAWN은 발생하지 않음)
5. 유예 기간 중 같은 소셜 계정으로 로그인하면 차단함 (`/login?error=account_withdrawn`, [auth-social-login.md](auth-social-login.md) 요구사항 6). 탈퇴는 철회할 수 없음
6. `deletion_scheduled_at`이 지난 사용자는 사용자(로그인 수단 포함), refresh 토큰, 기업을 모두 실제로 삭제함. 삭제 후 같은 소셜 계정으로 로그인하면 새 사용자로 가입됨
7. 삭제는 `uv run python -m app.domains.users.purge`로 실행함. 하루 한 번 실행하는 스케줄은 배포 시 설정함
8. 유예 기간 동안 개인정보를 보관하는 것은 개인정보 처리방침에 보관 기간과 사유를 명시해야 함 (서비스 공개 전 확인)

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/users/me/withdraw | access | 탈퇴 요청. 즉시 비활성화, 삭제 예정일 반환, 쿠키 삭제 | 200 | 401, 422 |

**요청**

```json
{ "confirm": true }
```

**응답**

```json
{ "deletion_scheduled_at": "2026-11-21T09:30:00Z" }
```

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| users | withdrawn_at | DateTime(tz), nullable. null이면 활성 사용자 |
| users | deletion_scheduled_at | DateTime(tz), nullable, index |

설정: `WITHDRAWAL_GRACE_DAYS` (정수, 기본 30)

## 6. 완료 조건

- [x] `{"confirm": true}`로 탈퇴하면 200과 deletion_scheduled_at(탈퇴 시각 + 30일)을 반환함
- [x] 본문이 없거나 confirm이 false면 422를 반환하고 사용자는 탈퇴되지 않음
- [x] 탈퇴 응답은 access·refresh 쿠키를 삭제함
- [x] 탈퇴하면 그 사용자의 refresh 토큰이 모두 폐기되어 /auth/refresh가 401을 반환함
- [x] 탈퇴 후 같은 access 토큰으로 /users/me를 호출하면 401을 반환함
- [x] 삭제 예정일이 지난 사용자는 purge 실행 후 사용자, refresh 토큰, 기업이 모두 사라짐
- [x] 삭제 예정일이 지나지 않은 탈퇴 사용자와 활성 사용자는 purge 후에도 남아 있음
- [x] purge 후 같은 소셜 계정으로 로그인하면 새 사용자가 생성됨

## 7. 미정 사항

- 유예 기간 30일의 법적 근거와 개인정보 처리방침 문구 (서비스 공개 전)
- 유예 기간 중 개인정보(email, name)를 미리 가릴지 여부
- 삭제 작업 스케줄 실행 위치 (App Service WebJob, Azure Functions 타이머 등. infra 레포)
