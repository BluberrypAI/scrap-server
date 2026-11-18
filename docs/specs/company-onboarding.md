# Spec: 기업 정보 (등록·조회·수정·변경 이력)

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | 기획서 4.1, product-plan 2장·3장, API 명세 CORP-002·CORP-006, 프론트 온보딩 화면 |
| 관련 todo | T-002, T-004, T-010, T-111, T-128 |

## 1. 목적

첫 로그인 후 기업과 사업장 정보를 받아, 이후 입력의 기본값과 업종·배출시설 기반 판단에 사용함. 등록한 정보는 조회·수정할 수 있고, 수정할 때마다 버전과 변경 이력을 남겨 분석 결과가 어느 시점의 기업 정보를 기준으로 했는지 추적할 수 있게 함.

## 2. 범위

- 포함: 기업 등록(온보딩), 내 기업 조회, 내 기업 수정, 변경 이력 조회(페이지네이션), 사용자가 확인한 사업장 좌표 입력
- 제외: 기업당 복수 담당자, 기업당 복수 사업장, 사업자등록번호와 진위 확인(국세청 조회, CORP-012), 변경 전후 값 저장, 기업 삭제(탈퇴 시 삭제는 account-withdrawal), 공통 오류 응답 형식([error-response.md](error-response.md))

## 3. 요구사항

### 등록

1. 기업과 회원(사용자)은 1:1이고, 사업장은 기업당 1곳임. 이미 기업이 있는 사용자가 다시 등록하면 409를 반환함
2. 필수 항목: 회사명(`company_name`), 담당자 이메일(`contact_email`), 업종(`industry`), 사업장 이름(`site_name`), 사업장 주소(`site_address`), 배출시설(`site_facilities`, 1개 이상). 빠지거나 비어 있으면 422. 주생산품(`main_products`)은 선택이며 보내지 않으면 빈 배열임. null을 보내면 422 (DB도 NOT NULL DEFAULT '[]')
3. 담당자 이메일은 `이름@도메인` 형식이어야 함. 아니면 422
4. 주요 폐기물(`main_waste_types`)은 선택이며 0개 이상임. 각 항목은 종류(`category`, 자유 문자열), 월 예상 물량(kg)임
5. 발생 주기는 받지 않음 (2026-11-10 화면에서 뺌). 항목에 `generation_cycle` 등 정의되지 않은 키를 보내면 422
6. 예상 물량은 월 kg 단위이며, 모르면 비워 둠 (값을 추정해 채우지 않음)
7. 정의되지 않은 필드(예: 예전 `business_registration_no`, `contact`)를 보내면 422
8. 등록 시 `profile_version`은 1이며, 등록은 변경 이력에 남기지 않음

### 수정

9. 2번의 필수 항목과 `main_products`, `main_waste_types`, 좌표 쌍(`site_latitude`, `site_longitude`)을 수정할 수 있음. `main_products`는 빈 배열로 비울 수 있음. 그 외 필드를 보내면 422
10. 요청에는 화면이 불러온 `profile_version`이 반드시 있어야 함. 현재 버전과 다르면 409 (다른 곳에서 먼저 수정됨)
11. 보내지 않은 필드는 바꾸지 않음. 좌표 이외의 수정 가능 필드에 `null`을 보내면 422. 좌표는 두 필드에 함께 null을 보내 해제할 수 있음. 주소만 바꾸면 이전 좌표를 지움
12. 목록 필드(`site_facilities`, `main_products`, `main_waste_types`)는 통째로 교체함 (부분 수정 없음). `main_waste_types`는 종류·물량과 순서가 같으면 바뀌지 않은 것으로 봄. 바뀌면 항목 id를 새로 붙임
13. 실제로 값이 바뀐 필드가 있으면 `profile_version`을 1 올리고, 바뀐 필드 이름을 `changed_fields`로 반환하며 변경 이력을 1건 남김
14. 바뀐 값이 없으면 버전을 올리지 않고 이력도 남기지 않으며, `changed_fields`는 빈 배열임
15. 같은 버전으로 동시에 수정하면 하나만 성공하고 나머지는 409임

### 변경 이력

16. 최신 버전부터 반환함
17. `pageNumber`는 1부터 시작함 (기본 1), `pageSize`는 1~100 (기본 20)
18. `pagingInfo.elementCount`는 전체 이력 수, `totalPageCount`는 전체 페이지 수(이력이 없으면 0)임. 마지막 페이지를 넘는 번호를 요청하면 빈 `items`와 `isEmpty: true`를 반환함
19. 페이지네이션 필드는 API 명세 형식(camelCase)을 따름. 그 외 필드는 snake_case

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/companies | access | 기업·사업장 등록 | 201 | 401, 409, 422 |
| GET | /api/v1/companies/me | access | 내 기업 조회 | 200 | 401, 404 |
| PATCH | /api/v1/companies/me | access | 내 기업 수정 | 200 | 401, 404, 409, 422 |
| GET | /api/v1/companies/me/history | access | 변경 이력 조회 | 200 | 401, 404 |

**기업 정보 (`POST` 요청, `GET` 응답)**

```json
{
  "id": "…",
  "company_name": "(주)가천정밀",
  "contact_email": "manager@example.com",
  "industry": "화학제품 제조업",
  "site_name": "화성 2공장",
  "site_address": "경기도 화성시 팔탄면 산업로 128",
  "site_facilities": ["혼합시설", "세척시설"],
  "main_products": ["산업용 윤활유"],
  "main_waste_types": [
    { "id": "…", "category": "PP", "expected_monthly_volume_kg": 3000 }
  ],
  "profile_version": 1
}
```

`id`, `profile_version`, `main_waste_types[].id`는 응답에만 있음.

**`PATCH /companies/me`**

```json
// 요청
{ "profile_version": 1, "industry": "금속 가공업", "main_products": ["포장 필름"] }
// 응답
{ "profile_version": 2, "changed_fields": ["industry", "main_products"] }
```

**`GET /companies/me/history?pageNumber=1&pageSize=20`**

```json
{
  "items": [
    { "profile_version": 2, "changed_at": "2026-11-09T05:00:00Z", "changed_fields": ["industry", "main_products"] }
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
| companies | id, user_id, company_name, contact_email, industry, site_name, site_address, site_latitude, site_longitude, site_facilities(JSON), main_products(JSON), main_waste_types(JSON), profile_version, created_at, updated_at | user_id unique, FK users (cascade 삭제). profile_version 기본 1. main_products NOT NULL DEFAULT '[]'. 좌표는 지오코딩 전까지 null |
| company_profile_history | id, company_id, profile_version, changed_fields(JSON 배열), created_at(= changed_at), updated_at | FK companies (cascade 삭제), (company_id, profile_version) unique |

`main_waste_types` 항목: `{id, category, expected_monthly_volume_kg}`. 예전 `waste_profiles` 테이블에서 옮겼고 id를 유지함 ([db-schema-simplify.md](db-schema-simplify.md)). 예전에 저장된 `generation_cycle` 키는 마이그레이션 `a7c3e91f5b28`에서 지움.

## 6. 완료 조건

### 등록·조회

- [x] 로그인한 사용자가 기업을 등록하면 201과 사업장·주생산품·주요 폐기물을 포함한 기업 정보, profile_version 1을 반환함
- [x] 주요 폐기물 없이 등록하면 빈 배열로 반환함
- [x] 필수 항목이 하나라도 빠지거나 배출시설이 빈 배열이면 422를 반환함
- [x] 주생산품 없이(또는 빈 배열로) 등록하면 201과 빈 배열을 반환함
- [x] 담당자 이메일 형식이 아니면 422를 반환함
- [x] 없앤 필드(사업자등록번호, 대표자, 본사 주소, contact)를 보내면 422를 반환함
- [x] 같은 사용자가 다시 등록하면 409를 반환함
- [x] 주요 폐기물 항목에 generation_cycle을 보내면 422를 반환함
- [x] 기업이 없을 때 GET /companies/me는 404, /users/me의 company_id는 null임
- [x] 등록 후 /users/me의 company_id가 등록한 기업 id와 같음

### 수정

- [x] industry와 main_products를 수정하면 profile_version이 2가 되고 changed_fields가 두 필드이며, 조회 결과에 반영됨
- [x] main_products를 빈 배열로 보내면 비워지고 changed_fields에 들어감
- [x] main_waste_types를 보내면 목록이 통째로 교체됨
- [x] 현재 값과 같은 값만 보내면 profile_version이 그대로이고 changed_fields가 빈 배열이며 이력이 생기지 않음
- [x] profile_version이 현재 버전과 다르면 409를 반환하고 값이 바뀌지 않음
- [x] profile_version 없이 보내면 422를 반환함
- [x] 정의되지 않은 필드를 보내면 422를 반환함
- [x] 좌표 이외의 수정 가능 필드에 null을 보내면 422를 반환함
- [x] 좌표는 함께 저장·해제하며, 주소 변경 시 이전 좌표를 지우고 변경 이력을 남김
- [x] 기업이 없을 때 PATCH는 404를 반환함

### 변경 이력

- [x] 두 번 수정하면 이력이 최신 버전부터 2건 반환되고 각 항목에 changed_fields가 있음
- [x] pageSize=1, pageNumber=2이면 두 번째로 최신인 이력 1건과 isLastPage true를 반환함
- [x] 이력이 없으면 items가 빈 배열이고 elementCount 0, totalPageCount 0, isEmpty true임
- [x] pageSize가 100을 넘거나 pageNumber가 0이면 422를 반환함
- [x] 기업이 없을 때 이력 조회는 404를 반환함

### 탈퇴 연계

- [x] 탈퇴 사용자 삭제(purge) 시 기업과 변경 이력도 함께 삭제됨

## 사업장 거리 기준점 추가 (2026-11-14, 사용자 요청)

- 기존 주소 입력에 선택 좌표 `site_latitude`, `site_longitude`를 추가한다. 지도에서 사용자가 확인한 사업장 위치이며 단말기 GPS나 시청 좌표로 대신하지 않는다.
- 생성·수정에서 두 좌표를 함께 받는다. 유한한 위도 -90~90, 경도 -180~180만 허용한다. 둘 다 null이면 위치를 해제한다. 기존 클라이언트는 생략할 수 있다.
- 주소만 바뀌면 이전 좌표를 지우고 재확인하도록 한다. 좌표 수정도 기업 버전과 변경 이력에 포함한다.
- A→B는 A 사업장, B→C는 현재 보유 기업 B 사업장을 거리 기준으로 쓴다. 기업 위치가 바뀌면 이전 후보 검토 캐시를 재사용하지 않는다.
- 위치·공정 근거가 확인된 서로 다른 사업장 최대 5곳을 직선거리 순으로 우선 표시한다. 도로 거리·운송비나 반입 승인을 뜻하지 않는다. 나머지 후보·좌표 미확인 후보도 펼쳐 볼 수 있으며 AI 검토 대상에서 제거하지 않는다.

## 7. 미정 사항

- 폐기물 종류를 코드표로 제한할지 (제한하면 API 명세의 422 UNSUPPORTED_WASTE_TYPE 적용). 코드표는 ai 팀과 합의 필요
- 배출시설 이름을 고정 목록(폐수처리시설, 혼합시설 등)으로 제한할지. 지금은 프론트 선택지를 자유 문자열로 받음
- 변경 이력에 변경 전후 값을 저장할지 (CORP-006 "변경 영향 표시"에서 필요하면 추가)


## 주소 검색으로 지도 위치 지정 (2026-11-18, 사용자 요청)
- 카카오 전환 요청에 따라 기존 REST 키가 있으면 카카오 주소 검색을 우선 사용하고, 주소 결과가 없을 때만 장소 검색을 사용한다. 카카오 원문·검색 응답은 캐시에 저장하지 않는다. 검색 실패를 Photon 결과로 위장하지 않는다. 키가 없으면 기존 Photon 경로를 유지한다. 응답 provider·attribution에 사용한 제공자를 표시한다.
- 회원 기업 등록·기업 정보 수정에서 입력한 주소/장소명으로 검색한 뒤 결과를 선택해 지도의 핀을 지정한다. 지도 클릭·드래그로 실제 출입구 조정도 유지한다.
- `POST /api/v1/companies/location-search`, 로그인 필요(기업 등록 전도 허용). 입력 `{query: string(3~200자)}`; 응답 `{provider, attribution, items:[{label,address,latitude,longitude,precision}]}`. precision은 address/place/area. 검색만으로 DB는 바꾸지 않는다.
- 키 없는 Photon(OpenStreetMap) 공개 서비스를 서버에서 호출. 버튼으로만 실행하며 국내 결과 최대5개, 명확히 다른 도로/건물번호는 제외한다. 도로·지역 대표점은 정확한 건물 위치로 표시하지 않는다. 실패/빈 결과는 구별하고 임의 좌표를 채우지 않는다.
- 서버 프로세스당 초당1회 제한, 검색어 캐시 최대512개·24시간. 운영 다중 복제/대규모 이용은 전용 geocoder로 전환해야 한다. `COMPANY_GEOCODING_ENABLED`, `COMPANY_GEOCODING_URL`로 끄거나 자체 Photon으로 변경한다.
- 검색어만 외부 전송하며 기업명/회원정보/쿠키는 전달하지 않는다. 검색어를 URL 접근 로그에 남기지 않도록 POST를 사용한다. 화면에 외부 검색·출처를 안내한다.
- 주소를 수정하거나 다른 검색을 시작하면 예전 검색 결과를 지운다. 지연된 이전 응답으로 새 주소 위치가 덮이지 않게 한다. 선택 좌표는 기존 site_latitude/site_longitude 필드로 저장하고 현재 보유 기업 기준 거리 비교에 연결한다.
- 검증: 인증·입력값·국내/좌표 검사·정밀도·동명이인 후보·빈 결과·장애·캐시·호출 제한·검색→기업 등록/수정·좌표 재조회. 실제 웹에서 주소 검색과 핀 표시/저장 확인.
