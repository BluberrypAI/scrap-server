# Spec: 기업 정보 (등록·조회·수정·변경 이력)

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | 기획서 4.1, product-plan 2장·3장, API 명세 CORP-002·CORP-006 |
| 관련 todo | T-002, T-004, T-010, T-111 |

## 1. 목적

첫 로그인 후 기업 정보와 주요 폐기물을 받아, 이후 입력의 기본값과 지역·업종 기반 판단에 사용함. 등록한 정보는 조회·수정할 수 있고, 수정할 때마다 버전과 변경 이력을 남겨 분석 결과가 어느 시점의 기업 정보를 기준으로 했는지 추적할 수 있게 함.

## 2. 범위

- 포함: 기업 등록(온보딩), 내 기업 조회, 내 기업 수정, 변경 이력 조회(페이지네이션)
- 제외: 기업당 복수 담당자, 사업자등록번호 진위 확인(국세청 조회), 회사명·사업자등록번호·대표자명 수정, 변경 전후 값 저장, 기업 삭제(탈퇴 시 삭제는 account-withdrawal), 공통 오류 코드 형식(T-109)

## 3. 요구사항

### 등록

1. 기업과 담당자(사용자)는 1:1임. 이미 기업이 있는 사용자가 다시 등록하면 409를 반환함
2. 사업자등록번호는 숫자 10자리임. 하이픈(`123-45-67890`)을 허용하고 숫자만 저장·반환함 (`1234567890`). 형식이 다르면 422
3. 주요 폐기물(`main_waste_types`)은 0개 이상이며 등록 요청에 함께 담음. 각 항목은 종류(`category`, 자유 문자열), 발생 주기, 월 예상 물량(kg)임
4. 발생 주기는 `daily`, `weekly`, `monthly`, `irregular` 중 하나임
5. 예상 물량은 월 kg 단위이며, 모르면 비워 둠 (값을 추정해 채우지 않음)
6. 등록 시 `profile_version`은 1이며, 등록은 변경 이력에 남기지 않음

### 수정

7. 수정할 수 있는 필드는 `industry`, `head_office_address`, `contact`, `main_waste_types`뿐임. 그 외 필드를 보내면 422
8. 요청에는 화면이 불러온 `profile_version`이 반드시 있어야 함. 현재 버전과 다르면 409 (다른 곳에서 먼저 수정됨)
9. 보내지 않은 필드는 바꾸지 않음. 수정 가능 필드에 `null`을 보내면 422
10. `contact`와 `main_waste_types`는 통째로 교체함 (부분 수정 없음). `main_waste_types`는 종류·주기·물량과 순서가 같으면 바뀌지 않은 것으로 봄
11. 실제로 값이 바뀐 필드가 있으면 `profile_version`을 1 올리고, 바뀐 필드 이름을 `changed_fields`로 반환하며 변경 이력을 1건 남김
12. 바뀐 값이 없으면 버전을 올리지 않고 이력도 남기지 않으며, `changed_fields`는 빈 배열임
13. 같은 버전으로 동시에 수정하면 하나만 성공하고 나머지는 409임

### 변경 이력

14. 최신 버전부터 반환함
15. `pageNumber`는 1부터 시작함 (기본 1), `pageSize`는 1~100 (기본 20)
16. `pagingInfo.elementCount`는 전체 이력 수, `totalPageCount`는 전체 페이지 수(이력이 없으면 0)임. 마지막 페이지를 넘는 번호를 요청하면 빈 `items`와 `isEmpty: true`를 반환함
17. 페이지네이션 필드는 API 명세 형식(camelCase)을 따름. 그 외 필드는 snake_case

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/companies | access | 기업·주요 폐기물 등록 | 201 | 401, 409, 422 |
| GET | /api/v1/companies/me | access | 내 기업 조회 | 200 | 401, 404 |
| PATCH | /api/v1/companies/me | access | 내 기업 수정 | 200 | 401, 404, 409, 422 |
| GET | /api/v1/companies/me/history | access | 변경 이력 조회 | 200 | 401, 404 |

**기업 정보 (`POST` 요청, `GET` 응답)**

```json
{
  "id": "…",
  "company_name": "가상사출(주)",
  "business_registration_no": "1234567890",
  "representative_name": "홍대표",
  "industry": "플라스틱 사출 성형",
  "head_office_address": "경기도 시흥시 정왕동 시화산업단지",
  "contact": { "name": "김담당", "phone": "031-123-4567", "email": null },
  "main_waste_types": [
    { "id": "…", "category": "PP", "generation_cycle": "monthly", "expected_monthly_volume_kg": 3000 }
  ],
  "profile_version": 1
}
```

`id`, `profile_version`, `main_waste_types[].id`는 응답에만 있음. `contact.name`은 필수, `phone`·`email`은 선택.

**`PATCH /companies/me`**

```json
// 요청
{ "profile_version": 1, "industry": "플라스틱 압출 성형", "contact": { "name": "이담당", "phone": null, "email": "lee@example.com" } }
// 응답
{ "profile_version": 2, "changed_fields": ["industry", "contact"] }
```

**`GET /companies/me/history?pageNumber=1&pageSize=20`**

```json
{
  "items": [
    { "profile_version": 2, "changed_at": "2026-10-23T05:00:00Z", "changed_fields": ["industry", "contact"] }
  ],
  "pagingInfo": {
    "currentPageNumber": 1, "pageSize": 20, "elementCount": 1,
    "totalPageCount": 1, "isLastPage": true, "isEmpty": false
  }
}
```

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| companies | id, owner_user_id, company_name, business_registration_no, representative_name, industry, head_office_address, contact_name, contact_phone, contact_email, profile_version, created_at, updated_at | owner_user_id unique, FK users. profile_version 기본 1 |
| waste_profiles | id, company_id, category, generation_cycle, expected_monthly_volume_kg, created_at, updated_at | FK companies (cascade 삭제). API 이름은 main_waste_types |
| company_profile_history | id, company_id, profile_version, changed_fields(JSON 배열), created_at(= changed_at), updated_at | FK companies (cascade 삭제), (company_id, profile_version) unique |

기존 컬럼 이름 변경: name → company_name, address → head_office_address, manager_name → contact_name, manager_phone → contact_phone. 배포 전이라 기존 데이터가 없다는 전제로 business_registration_no·representative_name은 NOT NULL로 추가함.

## 6. 완료 조건

### 등록·조회

- [x] 로그인한 사용자가 기업을 등록하면 201과 주요 폐기물을 포함한 기업 정보, profile_version 1을 반환함
- [x] 같은 사용자가 다시 등록하면 409를 반환함
- [x] 사업자등록번호는 하이픈이 있어도 숫자 10자리로 저장되고, 10자리가 아니면 422를 반환함
- [x] 허용되지 않은 발생 주기 값은 422를 반환함
- [x] 기업이 없을 때 GET /companies/me는 404를 반환함
- [x] 등록 후 /users/me의 company_id가 등록한 기업 id와 같음

### 수정

- [x] industry와 contact를 수정하면 profile_version이 2가 되고 changed_fields가 두 필드이며, 조회 결과에 반영됨
- [x] main_waste_types를 보내면 목록이 통째로 교체됨
- [x] 현재 값과 같은 값만 보내면 profile_version이 그대로이고 changed_fields가 빈 배열이며 이력이 생기지 않음
- [x] profile_version이 현재 버전과 다르면 409를 반환하고 값이 바뀌지 않음
- [x] profile_version 없이 보내면 422를 반환함
- [x] company_name 등 수정할 수 없는 필드를 보내면 422를 반환함
- [x] 수정 가능 필드에 null을 보내면 422를 반환함
- [x] 기업이 없을 때 PATCH는 404를 반환함

### 변경 이력

- [x] 두 번 수정하면 이력이 최신 버전부터 2건 반환되고 각 항목에 changed_fields가 있음
- [x] pageSize=1, pageNumber=2이면 두 번째로 최신인 이력 1건과 isLastPage true를 반환함
- [x] 이력이 없으면 items가 빈 배열이고 elementCount 0, totalPageCount 0, isEmpty true임
- [x] pageSize가 100을 넘거나 pageNumber가 0이면 422를 반환함
- [x] 기업이 없을 때 이력 조회는 404를 반환함

### 탈퇴 연계

- [x] 탈퇴 사용자 삭제(purge) 시 변경 이력도 함께 삭제됨

## 7. 미정 사항

- 폐기물 종류를 코드표로 제한할지 (제한하면 API 명세의 422 UNSUPPORTED_WASTE_TYPE 적용). 코드표는 ai 팀과 합의 필요
- 같은 사업자등록번호로 여러 사용자가 등록하는 것을 막을지 (진위 확인 없이 막으면 선점 문제가 생김)
- 변경 이력에 변경 전후 값을 저장할지 (CORP-006 "변경 영향 표시"에서 필요하면 추가)
- 사업장 위치를 주소 문자열로 둘지, 좌표(Azure Maps 연계)까지 저장할지
