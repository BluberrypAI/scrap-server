# Spec: ERD v2 반영 (폐기물 건·처리 단계·QR·완료 스냅샷·시설)

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 |
| 관련 기획 | SCRAP 기획서 폐기물 목록·처리 경로·QR·결과지, ERDCloud ERD v2 (2026-11-10) |
| 관련 todo | T-131 |

## 1. 목적

팀이 ERDCloud에서 확정한 ERD v2를 server DB에 그대로 만듦. 테이블과 제약만 만들고, 이 테이블을 쓰는 API(QR 발급·현장 확인, 처리 단계, 결과지, 업체 조회)는 각 기능 spec에서 따로 구현함.

## 2. 범위

- 포함
  - 새 테이블: `wastes`, `route_steps`, `qr_field_checks`, `waste_completion_snapshots`, `facilities`, `facility_waste_codes`, `facility_r_types`
  - `companies`: `site_latitude`, `site_longitude` 추가, `main_products` NOT NULL DEFAULT `'[]'`
  - ERDCloud가 선을 나눠 그리는 복합 제약을 실제 DB 제약으로 구현
- 제외
  - 배출 통계(`emission_site_stats`): ERD에서도 보류. 만들 때 실제 사업장 좌표 + 분류번호 + 출처 기준일로 집계하고 `UNIQUE(waste_code, latitude, longitude, source, as_of)`를 둠
  - 기존 `transport_*`, `treatment_snapshots` 테이블 정리: 처리 경로 담당자와 합의 후 (QR 현장 확인으로 옮길 예정)
  - 지오코딩(사업장 주소 → 좌표). 좌표는 지오코딩 전까지 null
  - 시설 원본(`facility_import_rows`) → `facilities` 적재 스크립트. 업체 조회 방식이 정해지면 함

## 3. 요구사항

1. QR: `qr_field_checks.route_step_id`는 nullable. 채우면 `(route_step_id, waste_id)` → `route_steps(id, waste_id)` 복합 FK로 같은 폐기물의 단계만 가리킴. `route_steps(id, waste_id)` UNIQUE
2. 한 단계에서 같은 역할은 한 번만 확인함: `qr_field_checks(route_step_id, role)` 부분 UNIQUE (`WHERE route_step_id IS NOT NULL`). API에서는 409 `STEP_ALREADY_CHECKED`로 돌려줌 (현장 확인 API 구현 때)
3. 시설 R유형: `facility_r_types(facility_id, waste_code)` → `facility_waste_codes` 복합 FK. 검증된 허가 조합만 적재함
4. 완료 스냅샷: 폐기물 1건당 0..1개 (`waste_id` UNIQUE). 완료 시점의 기업명·사업장명·주소를 저장하고 수정 불가. ORM `before_update`에서 `ImmutableRowError`, PostgreSQL에서는 트리거로 UPDATE를 막음
5. `companies.site_latitude`, `site_longitude`: float, nullable. 기업 조회 응답에 읽기 전용으로 나옴 (입력받지 않음)
6. `companies.main_products`: NOT NULL DEFAULT `'[]'`. 생성·수정 요청에서 null을 보내면 422
7. 기존 UNIQUE 유지: `users(provider, provider_subject)`, `companies(user_id)`, `company_profile_history(company_id, profile_version)`, `route_steps(waste_id, seq)`, `facilities(import_row_id)`
8. enum 컬럼(`wastes.status`, `qr_field_checks.role`)은 DB에 값(소문자)을 저장함
9. 탈퇴 purge로 기업을 지울 때 그 기업의 폐기물 건과 처리 단계·현장 확인·완료 스냅샷도 직접 지움 (SQLite는 FK cascade를 하지 않음)

## 4. API

새 API 없음. 기업 조회 응답(`GET /api/v1/companies/me`, 생성·수정 응답)에 `site_latitude`, `site_longitude` 필드가 추가됨 (기존 필드 변경 없음).

## 5. 데이터

| 테이블 | 주요 컬럼 | 제약 |
| --- | --- | --- |
| wastes | id, company_id, name, status, qr_token_hash, qr_issued_at, qr_expires_at, waste_code, code_name, category, waste_type, r_type, clause_refs, law_version_id, classified_at, quantity_value, quantity_unit, completed_at, share_token_hash, share_expires_at | FK companies CASCADE, status 기본 `diagnosing` (diagnosing, pending_analysis, candidates, confirmed, in_progress, completed) |
| route_steps | id, waste_id, seq, stage, process, output, kind, facility_id, facility_name, r_type, method, status, planned_date, actual_date, manifest_no | UNIQUE(waste_id, seq), UNIQUE(id, waste_id), FK wastes CASCADE, FK facilities SET NULL |
| qr_field_checks | id, waste_id, route_step_id, role, actor_name, checked_at | FK wastes CASCADE, 복합 FK (route_step_id, waste_id), 부분 UNIQUE(route_step_id, role) |
| waste_completion_snapshots | id, waste_id, company_name, site_name, site_address, completed_at, created_at | UNIQUE(waste_id), FK wastes CASCADE, 수정 불가 |
| facilities | id, name, business_type, permit_no, address, latitude, longitude, materials, acceptance_conditions, source, source_date, version, import_row_id | UNIQUE(import_row_id), FK facility_import_rows SET NULL |
| facility_waste_codes | facility_id, waste_code, handling | PK(facility_id, waste_code), FK facilities CASCADE |
| facility_r_types | facility_id, waste_code, r_code, r_name, category | PK(facility_id, waste_code, r_code), 복합 FK → facility_waste_codes CASCADE |
| companies | + site_latitude, site_longitude | main_products NOT NULL DEFAULT '[]' |

마이그레이션: `3045b5da7d75` (이전 `a7c3e91f5b28`).

## 6. 완료 조건

- [x] SQLite·PostgreSQL에서 upgrade → check("No new upgrade operations") → downgrade → upgrade 통과
- [x] 다른 폐기물의 단계를 가리키는 현장 확인은 FK 오류
- [x] 같은 단계·같은 역할의 두 번째 확인은 UNIQUE 오류, 단계 없는 확인은 여러 번 가능
- [x] 완료 스냅샷 두 번째 행은 UNIQUE 오류, 수정은 ORM·PostgreSQL 트리거에서 막힘
- [x] 허가 코드에 없는 (facility_id, waste_code)의 R유형은 FK 오류
- [x] main_products null 요청은 422, 컬럼을 빼고 넣으면 `[]`
- [x] 기업 응답의 좌표는 null
- [x] purge 후 그 기업의 폐기물 건·처리 단계·현장 확인이 남지 않음

## 7. 미정 사항

- 엔진 확정 결과(`diagnosis-handoff-v1`)를 `wastes`의 분류 컬럼으로 복사하는 시점과 매핑 (문진 연동 spec)
- `transport_*` 테이블을 `qr_field_checks`로 옮기는 시점 (처리 경로 담당자)
