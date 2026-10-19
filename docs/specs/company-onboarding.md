# Spec: 기업 온보딩

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 (수정 API는 T-010) |
| 관련 기획 | 기획서 4.1, product-plan 2장 |
| 관련 todo | T-002, T-004, T-010 |

## 1. 목적

첫 로그인 후 기업 정보와 폐기물 프로필을 받아, 이후 입력의 기본값과 지역·업종 기반 판단에 사용함.

## 2. 범위

- 포함: 기업 프로필 생성, 내 기업 조회, 폐기물 프로필(복수) 함께 생성
- 제외: 기업 수정(T-010), 기업당 복수 담당자, 사업자등록번호 검증

## 3. 요구사항

1. 기업과 담당자(사용자)는 1:1임. 이미 기업이 있는 사용자가 다시 생성하면 409를 반환함
2. 폐기물 프로필은 0개 이상이며 기업 생성 요청에 함께 담음
3. 발생 주기는 `daily`, `weekly`, `monthly`, `irregular` 중 하나임
4. 예상 물량은 월 kg 단위이며, 모르면 비워 둠 (값을 추정해 채우지 않음)

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/companies | access | 기업·폐기물 프로필 생성 | 201 | 401, 409, 422 |
| GET | /api/v1/companies/me | access | 내 기업 조회 | 200 | 401, 404 |

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| companies | id, owner_user_id, name, address, industry, manager_name, manager_phone, created_at, updated_at | owner_user_id unique, FK users |
| waste_profiles | id, company_id, category, generation_cycle, expected_monthly_volume_kg, created_at, updated_at | FK companies (cascade 삭제) |

## 6. 완료 조건

- [x] 로그인한 사용자가 기업을 생성하면 201과 폐기물 프로필을 포함한 기업 정보를 반환함
- [x] 같은 사용자가 다시 생성하면 409를 반환함
- [x] 기업이 없을 때 /companies/me는 404를 반환함
- [x] 생성 후 /users/me의 has_company가 true가 됨
- [x] 허용되지 않은 발생 주기 값은 422를 반환함

## 7. 미정 사항

- 폐기물 카테고리를 자유 문자열로 둘지, 코드표(PP, PE 등)로 제한할지
- 사업장 위치를 주소 문자열로 둘지, 좌표(Azure Maps 연계)까지 저장할지
