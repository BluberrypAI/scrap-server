# Spec: 문서 업로드와 측정값 검수

| 항목 | 내용 |
| --- | --- |
| 상태 | 구현 완료 (값 추출 미연결) |
| 관련 기획 | API 명세 v3 API-023~027 (DOC-001~003), 엔진 연동 INT-008, 요구사항 명세 FR-1.2·1.6 |
| 관련 todo | T-113 |

## 1. 목적

시험성적서 등 증빙 문서를 검토에 올리고, 문서에서 나온 측정값을 사람이 검수·수정하게 함. 검수된 값만 실행 근거로 씀. AI 엔진에 OCR이 아직 없으므로(INT-008) 저장·목록·교체·검수 흐름을 먼저 만들고 값 추출은 이후 연결함.

## 2. 범위

- 포함: 업로드, 문서 목록, 측정값 목록, 측정값 검수·수정, 문서 교체, 탈퇴 purge 시 문서·파일 삭제
- 제외: 값 추출(OCR). 추출이 연결되기 전까지 문서는 `uploaded`에 머물고 측정값은 비어 있음. 문서 다운로드, 문서 삭제, Blob Storage 연결(로컬 폴더 저장)

## 3. 요구사항

### 업로드·교체

1. multipart/form-data의 `file`과 `doc_type`(`test_report` 또는 `other`, 기본 `other`)
2. 형식은 확장자로만 판단함: pdf, png, jpg(jpeg), xlsx, csv. 그 외는 415 `FILE_TYPE_UNSUPPORTED`
3. 크기가 `MAX_UPLOAD_MB`(기본 20)를 넘으면 413 `FILE_TOO_LARGE`. 한도보다 1바이트만 더 읽어 판단함
4. 파일은 `UPLOAD_DIR` 아래 `<기업 id>/<검토 id>/<문서 id>/v<버전>.<형식>`에 저장함. 파일 이름은 레코드에만 남기고 경로에 쓰지 않음
5. 교체하면 `file_version`이 1 오르고 새 키로 저장한 뒤 이전 파일을 지움. 기존 측정값은 남기되 검수 상태를 모두 `unverified`로 돌림. status는 다시 `uploaded`

### 측정값

6. 측정값은 항목 이름, 값(없으면 null), 단위, 원문 위치, 측정 기준, 검수 상태를 가짐
7. `verification_status`로 검수함 (`verified`, `unverified`)
8. `value`나 `unit`을 실제로 바꾸면 검수 상태는 `unverified`가 됨. 같은 요청에 `verified`를 보내도 다시 검수해야 함
9. 결과적으로 값은 있는데 단위가 없으면 422 `UNIT_REQUIRED`
10. 빈 요청은 422

### 접근

11. 다른 기업의 검토·문서·측정값은 404
12. 탈퇴 purge 시 측정값, 문서 레코드, 저장 파일을 지움 (검토보다 먼저)

## 4. API

| 메서드 | 경로 | 인증 | 설명 | 성공 | 실패 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/v1/reviews/{reviewId}/documents | access | 문서 업로드 | 201 | 401, 404, 409, 413, 415 |
| GET | /api/v1/reviews/{reviewId}/documents | access | 문서 목록 | 200 | 401, 404, 409 |
| GET | /api/v1/documents/{documentId}/values | access | 측정값 목록 | 200 | 401, 404, 409 |
| PATCH | /api/v1/documents/{documentId}/values/{valueId} | access | 측정값 검수·수정 | 200 | 401, 404, 409, 422 |
| POST | /api/v1/documents/{documentId}/replace | access | 문서 교체 | 200 | 401, 404, 409, 413, 415 |

```json
// POST /reviews/{reviewId}/documents 응답 201
{ "document_id": "…", "format": "pdf", "doc_type": "test_report", "status": "uploaded" }

// GET /documents/{documentId}/values
{
  "items": [
    { "value_id": "…", "name": "함수율", "value": 12.5, "unit": "%", "source_location": "p.1 표1",
      "basis": "건조 기준", "verification_status": "unverified" }
  ],
  "pagingInfo": { "currentPageNumber": 1, "pageSize": 20, "elementCount": 1, "totalPageCount": 1, "isLastPage": true, "isEmpty": false }
}

// PATCH /documents/{documentId}/values/{valueId}
{ "value": 13.0 }  →  { "value_id": "…", "value": 13.0, "unit": "%", "verification_status": "unverified" }

// POST /documents/{documentId}/replace 응답
{ "document_id": "…", "file_version": 2, "status": "uploaded", "values_reset": true }
```

## 5. 데이터

| 테이블 | 필드 | 제약 |
| --- | --- | --- |
| documents | id, review_id, file_name, format, size_bytes, doc_type, status, storage_key, file_version, created_at(= uploaded_at), updated_at | FK reviews (cascade) |
| document_values | id, document_id, name, value, unit, source_location, basis, verification_status, created_at, updated_at | FK documents (cascade) |

환경변수: `UPLOAD_DIR`(기본 `./uploads`), `MAX_UPLOAD_MB`(기본 20). 저장소는 `app/core/storage.py`의 `LocalFileStorage`이며 Blob Storage로 바꿀 때 같은 메서드(save, read, delete)를 가진 클래스로 교체함.

## 6. 완료 조건

- [x] 업로드하면 201과 형식·문서 유형·uploaded를 반환하고 파일이 저장됨
- [x] 허용되지 않은 확장자는 415 FILE_TYPE_UNSUPPORTED
- [x] 한도를 넘는 파일은 413 FILE_TOO_LARGE
- [x] 문서 목록은 업로드 순서이고 jpeg는 jpg로 정규화됨
- [x] 측정값 목록에 원문 위치·단위·측정 기준·검수 상태가 있음
- [x] verified로 검수할 수 있음
- [x] 값을 고치면 verified를 함께 보내도 unverified가 됨
- [x] 단위 없는 값은 422 UNIT_REQUIRED, 빈 요청은 422
- [x] 교체하면 file_version 2, 측정값 검수 상태가 모두 unverified, 새 파일로 바뀌고 이전 파일은 지워짐
- [x] 교체도 허용되지 않은 형식이면 415
- [x] 다른 기업 사용자는 업로드·목록·측정값 조회·수정이 404
- [x] 탈퇴 purge 시 문서·측정값·파일이 삭제됨

## 7. 미정 사항

- 값 추출(OCR): Azure Document Intelligence 직접 연동 / 다른 벤더 / MVP는 수동 입력만 (엔진 연동 INT-008, 결정 필요). 수동 입력이면 측정값 추가 API(POST values)가 필요함
- 운영 저장소를 Blob Storage로 바꾸는 시점 (infra 레포 리소스 확정 후)
- 업로드 파일 바이러스 검사 여부
