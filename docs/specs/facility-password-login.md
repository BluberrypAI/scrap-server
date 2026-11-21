# Spec: 처리업체 아이디·비밀번호 로그인

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | product-plan 3장(회원), [pp-company-workflow.md](pp-company-workflow.md) |
| 관련 todo | T-190 |

## 1. 목적

인계 흐름의 B(중간 처리)·C(다음 공정) 처리업체는 소셜 계정으로 가입해 온보딩하지 않음. 운영자가 배포 DB에 이미 있는 처리업체 정보로 계정을 발급하고, 업체 담당자는 아이디·비밀번호로 로그인해 인수 요청을 받음.

## 2. 범위

- 포함: 아이디·비밀번호 로그인 API(운영 포함), 운영자용 계정 발급 명령(사용자·기업·업체 연결을 한 번에 생성), 비밀번호 재설정(같은 명령 재실행), 웹 로그인 화면의 아이디·비밀번호 폼
- 제외: 회원가입·비밀번호 찾기 화면, 사용자가 직접 바꾸는 비밀번호 변경, 로그인 시도 횟수 제한(아래 7장), 소셜 계정과의 병합

## 3. 요구사항

1. 계정은 `provider="password"`, `provider_subject`=아이디(소문자로 정규화)인 사용자임. 비밀번호는 `users.password_hash`에 scrypt 해시로만 저장함
2. 로그인 성공 시 소셜 로그인과 같은 access·refresh 쿠키와 DB refresh 토큰을 발급함. 이후 refresh·logout·/users/me는 그대로 씀
3. 아이디가 없거나 비밀번호가 틀리면 같은 401 응답을 줌(계정 존재 여부를 드러내지 않음). 없는 아이디에도 해시 계산을 해서 응답 시간도 맞춤
4. 탈퇴 처리 중인 계정은 비밀번호가 맞아도 403
5. 업체 정보는 새로 입력받지 않고 배포 DB의 처리 공정표 스냅샷(`treatment_snapshots` kind=`processes`)의 `facilities`·`organisations`에서 가져옴
   - 기업명 = organisation label, 사업장명 = facility label, 주소 = facility address(없으면 region), 좌표 = facility 좌표
   - 업종·담당 이메일·배출시설은 스냅샷에 없으므로 명령 인자로 받고, 인자를 주지 않은 값은 기본값(업종 `폐기물 처리·재활용업`, 배출시설 `폐기물 처리시설`)을 씀
6. 발급 명령은 지정한 업체 키(1개 이상)를 그 기업에 연결함(`workflow_facility_accounts`). 다른 기업에 이미 연결된 업체는 `--force` 없이 바꾸지 않음
7. 연결은 `synthetic=false`로 저장해서 운영에서 `DEMO_FACILITY_BINDINGS` 설정 없이도 수신 업체로 보임. `verification_reference`에는 팀이 명령으로 발급한 계정임을 기록함(`--verification-reference`로 문구 변경). 운영 화면에서 숨길 시험 계정은 `--synthetic`으로 만듦
8. 같은 아이디로 다시 실행하면 새 사용자를 만들지 않고 비밀번호·연결만 갱신함. 기존 기업 정보는 덮어쓰지 않음
9. 비밀번호는 명령 인자로 받지 않음(셸 기록에 남음). 대화형 입력이나 `--password-stdin`으로 받음. 8자 이상 128자 이하
10. `--all`은 스냅샷의 모든 업체에 아이디 = 업체 키, 공통 비밀번호로 발급함. 스냅샷에 담당 이메일이 없으므로 `<업체키>@facility.scrap.invalid`(메일이 가지 않는 예약 도메인)를 넣음. 다른 기업에 연결된 업체 등 실패한 업체는 건너뛰고 이유를 출력함

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/auth/password-login | - | `{login_id, password}`로 로그인. 쿠키 설정 | 204 | 401 AUTH_REQUIRED(아이디·비밀번호 불일치), 403 ACCOUNT_WITHDRAWN, 422 |

운영자 명령 (backend/에서):

```bash
uv run python -m app.domains.auth.facility_accounts --list                # 업체 키 목록
uv run python -m app.domains.auth.facility_accounts --all --password-stdin  # 전체 업체 일괄 발급
uv run python -m app.domains.auth.facility_accounts \
  --login-id sarom-hwaseong --facility sarom-hwaseong-2 \
  --contact-email manager@example.com                                     # 비밀번호는 입력 프롬프트
```

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| users | password_hash (추가) | String(255), nullable. 소셜·개발용 사용자는 null |

기업·업체 연결은 기존 `companies`, `workflow_facility_accounts`를 그대로 씀.

## 6. 완료 조건

- [x] 발급한 아이디·비밀번호로 로그인하면 204와 쿠키가 설정되고 /users/me의 company_id가 발급된 기업임
- [x] 아이디는 대소문자·앞뒤 공백과 무관하게 같은 계정으로 로그인됨
- [x] 비밀번호가 틀리거나 없는 아이디면 둘 다 401임
- [x] 비밀번호 해시가 없는 사용자(소셜 사용자)는 비밀번호 로그인으로 들어갈 수 없음
- [x] 탈퇴 처리 중인 계정은 403임
- [x] APP_ENV=prod 앱에도 비밀번호 로그인 경로가 있음
- [x] 발급 명령은 스냅샷 업체 정보로 기업을 만들고 지정한 업체 키를 연결함
- [x] 스냅샷에 없는 업체 키는 아무것도 만들지 않고 실패함
- [x] 다른 기업에 연결된 업체 키는 `--force` 없이 바꾸지 않음
- [x] 같은 아이디로 다시 발급하면 사용자는 1명이고 새 비밀번호로만 로그인됨
- [x] `--all`은 업체마다 계정 1개를 발급하고, 다른 기업에 연결된 업체는 건너뛰며, 다시 실행해도 새 사용자를 만들지 않음
- [x] 발급한 업체 연결은 운영 설정(DEMO_FACILITY_BINDINGS 꺼짐)에서도 수신 업체로 보임

## 7. 미정 사항

- 로그인 시도 횟수 제한. 지금은 계정 수가 적고 운영자가 비밀번호를 정하므로 두지 않음. 계정을 넓게 열면 Front Door WAF 속도 제한이나 서버 제한을 추가함
- 업체 담당자가 직접 비밀번호를 바꾸는 화면
