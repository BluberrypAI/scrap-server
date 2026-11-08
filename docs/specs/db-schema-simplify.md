# Spec: DB 스키마 간소화 (검토 기능 삭제, 계정·기업 정리)

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | SCRAP 기획서(2026-11-07) 3장 서비스 플로우, product-plan 2장 (관리자 계정 1개 = 기업 1개) |
| 관련 todo | T-128 |

## 1. 목적

기획서에 없는 "검토 → 분석 실행 → 후보 → 리스크·보완 자료" 흐름을 걷어내고, 테이블 수를 줄여 순수 백엔드 범위(엔진·LLM 제외)를 개발할 바탕을 만듦. 온보딩 입력은 프론트 온보딩 화면에 맞춤.

## 2. 범위

- 포함:
  1. 검토 관련 기능과 테이블 삭제: `reviews`, `runs`, `documents`, `document_values`, `supplements`, `risk_step_decisions`, `risk_evidence` 테이블과 `reviews`, `runs`, `documents`, `results`, `risks`, `supplements` 도메인, 가짜 엔진, 업로드 저장소
  2. `social_accounts`를 `users`에, `waste_profiles`를 `companies`에 합침. 사업장은 기업당 1곳으로 보고 `companies` 컬럼에 둠
  3. 온보딩(기업 등록·수정) 입력 항목을 프론트 온보딩 화면에 맞춤
  4. `treatment_facility_listings` → `facility_import_rows` 이름 변경
- 제외:
  - 폐기물 문진·분류 판정 (S1~S3): 문진 로직과 API가 나오면 다룸
  - 업체 조회·추천 (S4): ai 쪽에서 에이전트로 할지 정한 뒤 다룸. 사업장 좌표, 처리 제약 조건, 시설 테이블도 그때 정함
  - 위탁 문서 초안 (S5): LLM 기능이라 제외
  - 폐기물 건 목록, 처리 경로 단계, QR 확인 테이블은 각 기능 spec에서 다룸
  - `transport_*`, `treatment_snapshots`(처리 경로 데모)는 그대로 둠

## 3. 요구사항

1. 1번 범위의 API는 모두 없앰 (기존 API-019~053 구현분). 프론트는 이 API를 호출하지 않음
2. 사용자 한 명은 로그인 수단(provider) 하나, 기업 하나, 사업장 하나만 가짐. `(provider, provider_subject)`는 유일함
3. `users`는 로그인 정보만, `companies`는 기업·사업장 정보를 가짐. `companies.user_id`는 UNIQUE(회원 1명 = 기업 1곳). 온보딩 여부는 지금처럼 `companies` 행이 있는지로 판단함
4. 온보딩 필수 항목: 회사명, 담당자 이메일, 업종, 사업장 이름, 사업장 주소, 배출시설(1개 이상), 주생산품(1개 이상)
5. 온보딩 선택 항목: 주 폐기물 종류(`main_waste_types`). 없으면 빈 배열
6. 사업자등록번호, 대표자, 본사 주소, 담당자 이름·전화는 받지 않고 컬럼도 없앰. 기존 값은 마이그레이션에서 버림
7. 주 폐기물 종류는 `companies.main_waste_types` JSON 배열에 저장하고 항목마다 `id`(UUID)를 붙임 (기존 waste_profiles의 id를 그대로 옮김)
8. 회원 탈퇴 purge는 지금처럼 refresh 토큰 → 기업(변경 이력 포함) → 사용자 순서로 지움
9. 마이그레이션은 데이터를 옮긴 뒤 `social_accounts`, `waste_profiles`를 지움. 소셜 계정이 2개 이상인 사용자가 있으면 데이터를 지우지 않고 마이그레이션을 실패시킴
10. 지운 테이블의 downgrade는 빈 테이블만 다시 만들고 데이터는 되돌리지 않음

## 4. API

| 메서드 | 경로 | 변경 |
| --- | --- | --- |
| 전체 | /api/v1/reviews/**, /api/v1/documents/** | 없앰 |
| POST | /api/v1/companies | 요청 필드: `company_name`, `contact_email`, `industry`, `site_name`, `site_address`, `site_facilities`, `main_products`, `main_waste_types`(선택). `business_registration_no`, `representative_name`, `head_office_address`, `contact` 객체는 없앰 |
| GET | /api/v1/companies/me | 응답 필드도 위와 같음 + `id`(기업 id), `profile_version` |
| PATCH | /api/v1/companies/me | 위 필드 수정. 기존처럼 profile_version 충돌이면 409 |

기존처럼 온보딩 전 `GET /companies/me`는 404, 이미 온보딩한 사용자의 `POST /companies`는 409.

## 5. 데이터

| 테이블 / 스키마 | 필드 | 제약 |
| --- | --- | --- |
| users | provider, provider_subject | 추가. NOT NULL, UNIQUE(provider, provider_subject) (기존 social_accounts에서 옮김) |
| users | id, email, name, withdrawn_at, deletion_scheduled_at | 그대로 |
| companies | company_name, contact_email, industry, site_name, site_address | NOT NULL |
| companies | site_facilities, main_products | JSON 문자열 배열, NOT NULL |
| companies | main_waste_types | JSON 배열, 기본값 `[]`. 항목: id, category, generation_cycle, expected_monthly_volume_kg |
| companies | user_id | 기존 owner_user_id에서 이름 변경. FK users.id CASCADE, UNIQUE |
| companies | business_registration_no, representative_name, head_office_address, contact_name, contact_phone | 삭제 |
| company_profile_history | company_id | 그대로 |
| facility_import_rows | (기존 treatment_facility_listings 컬럼) | 이름만 변경 |
| social_accounts, waste_profiles | | 삭제 |
| reviews, runs, documents, document_values, supplements, risk_step_decisions, risk_evidence | | 삭제 |

기존 기업 행에 사업장 이름·주소, 배출시설, 주생산품 값이 없으므로 마이그레이션에서 사업장 이름은 회사명, 사업장 주소는 본사 주소, 담당자 이메일은 기존 담당자 이메일(없으면 사용자 이메일, 그것도 없으면 빈 문자열), 배출시설·주생산품은 빈 배열로 채움. 다음에 기업 정보를 수정할 때 필수 검증을 받음.

## 6. 완료 조건

- [x] 검토·문서·실행·결과·리스크·보완 자료 API와 테이블이 없고, 남은 테스트가 통과함
- [x] 소셜 로그인 첫 로그인 시 `users`에 provider, provider_subject가 있는 행이 생기고, 같은 provider로 다시 로그인하면 같은 사용자로 들어감
- [x] 온보딩 전 `GET /companies/me`는 404, `GET /users/me`의 `company_id`는 null
- [x] 필수 항목(회사명, 담당자 이메일, 업종, 사업장 이름·주소, 배출시설, 주생산품)이 하나라도 빠지면 `POST /companies`는 422
- [x] 주 폐기물 종류 없이도 `POST /companies`가 성공하고 빈 배열로 돌아옴
- [x] 없앤 필드(사업자번호, 대표자, 본사 주소, contact 객체)를 보내면 422
- [x] 온보딩한 사용자의 `POST /companies`는 409
- [x] `PATCH /companies/me`가 profile_version을 올리고 이력을 남기며, 버전이 다르면 409
- [x] 탈퇴 purge 시 사용자, 기업, 변경 이력이 함께 지워짐
- [x] 마이그레이션: upgrade 후 기존 로그인 정보가 `users`에, 기업·주 폐기물 정보가 `companies`에 남음, downgrade로 이전 구조로 돌아감, `alembic check` 통과

## 7. 미정 사항

- 폐기물 건 목록(프론트 6단계 상태: 문진 중, 분석 대기, 후보, 확정, 처리 진행, 완료)을 담을 테이블은 문진 로직이 정해진 뒤 만듦
- 처리 경로 단계(`route_steps`)의 컬럼은 ai 레포와 합의 후 정함
- QR: 폐기물 건마다 하나라서 별도 테이블 없이 폐기물 건 테이블에 QR 컬럼(토큰 해시, 발급·만료 시각)으로 두고, 현장 확인 기록(`qr_field_checks`)은 폐기물 건만 참조함. 단계별 확인이 필요해지면 `route_step_id`(선택)를 추가함
- 사업자등록번호는 사업자 검증(CORP-012)을 할 때, 사업장 좌표는 업체 조회를 할 때 다시 추가함
- 나중에 여러 로그인 수단, 기업당 여러 담당자, 여러 사업장이 필요해지면 `social_accounts`, 기업-회원 소속 테이블, `company_sites`를 추가함
- 수요업체: 1단계로 공개 API 데이터를 외부 업체 목록으로 적재해 추천에 쓰고, 2단계로 가입을 열면 `companies.role`(emitter, buyer)을 추가함
