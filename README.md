# SCRAP

**11/18 로컬 지도 전환:** 카카오 지도 SDK·주소 검색·자동차 길찾기를 연결했습니다. 인계 지도에는 직선 대신 길찾기 도로선을 표시합니다. 기업 위치 선택과 업체 지도도 같은 지도 연결을 사용하며, REST 키는 서버에만 둡니다. 실제 차량 GPS 추적을 뜻하지 않습니다.

**업체 반입조건·문의 응답:** 연결된 업체 계정이 자기 사업장의 반입조건을 등록하고, 배출기업과 문의·답변 → 조건부 수락 → 자료 제출·확인 → 최종 수락 → QR 입고로 이어집니다. 업체가 직접 입력한 안내이며 허가 인증이 아닙니다. 적용 전 DB 마이그레이션이 필요합니다. [사용법·검증 범위](docs/supplier-intake-validation-20261117.md)

**11/17 최신 보강:** 사업장 좌표 누락 30곳을 채우고 B 사업장 기준 실제 도로거리·지도 상위 5곳을 연결했습니다. 미가입 업체에는 **업체에 보낼 문의서**를 준비할 수 있습니다. 물량·AI 확인사항·업체별 질문을 복사/저장하며 자동 발송은 하지 않습니다. [사용 흐름·검증·남은 판매 준비](docs/vendor-inquiry-validation-20261117.md)

**2026-11-16 현재:** 실제 문진 → 세부 재질·형태 확인 → 공정·업체 후보 → 후보별 AI 근거 검토 → 수신 기업 수락·QR 흐름입니다.

- 공정 참조: **62개 사업장·69개 공정·129개 연결**. 실제 공정 연결 사업장은 61곳이며, 그중 경기 23곳·인천 5곳입니다. 전국 명부 9,604행과 다른 숫자입니다.
- 일반 PET `51-03-01`과 포장재 PET `51-03-07`을 원래 번호 그대로 연결합니다.
- 일반 플라스틱·금속 14개 번호의 R유형·분석 조건·법령 출처를 문진 → 화면 → 물량 → 후보별 AI에 전달합니다. [전달 구조·팀 적용 순서](docs/r-code-handoff.md)
- 실제 문진 18선택지 중 15개에 후보가 있고, 그 안의 형태 조합 56개 중 53개가 연결됩니다. 미지원·근거 부족은 승인으로 바꾸지 않습니다.
- 기업 위치를 지도에서 저장하고 현재 보유 기업 기준으로 가까운 후보를 표시합니다. 도로 서비스 활성화 시 도로거리 상위 최대 5곳을 표시하고, 미확인 값은 직선거리와 섞지 않습니다. [도로 서비스 설정과 한계](docs/specs/road-distance.md)
- 이번 재검사는 문진·후보·AI·위치 저장 범위입니다. 이전 PP/PET/PE·캔의 7개 합성 QR 완료 시나리오와 구분합니다.
- 추가 근거가 필요했던 12개 연결을 다시 조사하고 **화성 성원산업의 LDPE 필름 → 이중 압출 → 펠릿**을 추가했습니다. PE 경질·베일로 확대하지 않았습니다. [원문 대조·남은 자료](docs/registry-screen/intake-evidence-followup-20261116.md)
- 최신 검사는 문진 18선택지·브라우저 59검사·HTTP 212조회입니다. AI는 첫 공정과 후속 공정의 모든 지원 연결을 포함하는 대표 입력으로 실제 Azure에서 다시 검토했습니다. [최신 검증 결과](docs/intake-evidence-followup-validation-20261116.md)
- 기존 보류 12연결 중 한국철강 1연결의 근거를 보강했고 11연결은 자료 부족이 남았습니다. 일반 PE·PS 베일도 국내 반입 사업장 근거가 부족해 보류합니다. 압축 필름·EPS 인고트와는 다른 입력입니다.
- 앞선 수도권 보강의 Azure 67후보 검토는 공개 근거 확인 21회·부족 46회였습니다. 신규 19연결 중 부족했던 12개가 이번 재조사 대상입니다. [앞선 검사 범위](docs/capital-region-coverage-20261116.md)
- 앞선 전체 53형태·294후보 검사는 공개 근거 확인 56회·부족 238회였습니다. 서로 다른 범위의 검사이므로 두 수치를 정확도처럼 비교하지 않습니다.

[최신 R코드·화면·AI 연결 검사와 적용 방법](docs/r-code-flow-audit-20261116.md) · [앞선 252회 부족 사유·업체별 표](docs/registry-screen/intake-evidence-gaps-20261116.md) · [공개 근거 보강·남은 소재](docs/registry-screen/remaining-material-evidence-20261116.md)

이전 기록: [11/15 세부 재질·252회 근거 부족](docs/material-detail-e2e-20261115.md) · [7개 기업 인계 시험](docs/full-stack-validation-20261115.md) · [전체 조사 목록](docs/registry-screen/README.md)

사업장에서 나오는 폐기물을 **분류부터 처리업체 인계까지** 이어주는 재활용 자원순환 네비게이터 **SCRAP**의 **server 레포**.
법령 지식이 없는 중소 제조 사업장 담당자도 AI 에이전트 **베리**의 안내를 따라가면 위탁 직전 단계까지 도달할 수 있게 함.

- 팀: 블루베리 파이
- 팀 공통 규칙 (레포 역할, 브랜치, CI/CD, 배포): [docs/team-conventions.md](docs/team-conventions.md)

## 해결하려는 문제

- **분류가 어려움**: 「폐기물관리법 시행규칙」 별표 4의 분류번호는 8자리 약 250종임. 허용 재활용 유형(R유형)과 사전 분석 필요 여부는 분류번호 × R유형 그룹 단위로 따로 규정됨
- **책임은 배출자에게 있음**: 미허가 업체에 위탁하면 배출자도 처벌받음. 하지만 현장에서는 허가증만 보고 허가된 분류번호 범위는 대조하지 않음
- **업체 정보가 흩어져 있음**: 처리업체 3,907곳 중 72%가 단일 분류번호만 허가받음. 중분류가 같아도 세분류가 다르면 처리업체가 거의 겹치지 않음

## 서비스 흐름

| 단계 | 내용 | 서버 상태 |
| --- | --- | --- |
| 온보딩 | 로그인·기업 정보·지도 위치 저장 | 구현 |
| S1·S2 문진 | diagnosis 질문 응답 → 분류 결과 | 연동, 버튼 문진 실제 검사 |
| S3 유형 조회 | 분류번호·보류사항 전달 / R유형·분석 조건 확인 | 일반 14번호 연결. 기존 확정 건 보충 조회. 업체의 실제 허가·반입 승인은 별도 확인 |
| S4 업체 조회 | 재질·현재 형태 → 공정·업체 → AI 근거 검토 | 지원 범위 구현, 공개 근거 부족은 별도 표시 |
| S5 문서 작성 | 문의·위탁 문서 초안 | 예정 |
| S6 결과 보관 | 문진·검토 결과·기업별 인계 저장 | 구현 |
| 추적 | 수신 기업 수락 → QR 입고 → 실제 산출물 → 다음 업체/완료 | 구현, 현재 범위는 검증 보고서 참고 |

문진의 분류 판정과 업체의 반입 승인은 다릅니다. server는 diagnosis의 결과를 보존하고, PostgreSQL의 공정·사업장 자료에서 후보를 찾습니다. route의 AI는 후보별 공개 자료·입력 상태를 검토합니다. 현재 허가·실제 수용 여부는 별도 확인해야 하며 수신 기업의 수락을 대체하지 않습니다.

## 조직 레포 구성

| 레포 | 역할 |
| --- | --- |
| **scrap-server (이 레포)** | API, 인증·회원, 기업 위치, PostgreSQL 공정·사업장 참조, 물량·인계 저장 |
| scrap-diagnosis | 문진·분류 판정, 확정 결과 전달 |
| scrap-route | 후보별 공개 근거·상태·사진 AI 검토 |
| scrap-web | 화면, 기업 지도 위치 입력, 문진·후보·인계 UI |
| scrap-infra | 전체 통합 실행(compose), 서비스 연결·실행 설정 |
| .github | 공통 규칙·템플릿 |

## 빠른 시작

자세한 내용과 문제 해결은 [backend/README.md](backend/README.md).

**A. Docker (팀 표준)** (Docker Desktop만 필요, DB는 PostgreSQL)

```bash
cp .env.example backend/.env
docker compose up -d --build
```

**B. 로컬 (보조)** (uv만 필요, DB는 SQLite)

```bash
cd backend
cp ../.env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

실행 후 http://localhost:8000/docs (Swagger) 에서 `POST /api/v1/auth/dev-login`을 실행하면 OAuth 키 없이 로그인된 상태로 모든 API를 시험할 수 있음.

## 기술스택

| 영역 | 선택 |
| --- | --- |
| 언어 / 프레임워크 | Python 3.12 / FastAPI |
| DB | PostgreSQL 17 (로컬 개발은 SQLite도 가능) |
| ORM / 마이그레이션 | SQLAlchemy 2.0 (async) / Alembic |
| 인증 | Google·Microsoft 소셜 로그인 (Authlib), JWT httpOnly 쿠키 |
| 패키지 / 품질 | uv / ruff, pytest |
| 배포 (예정) | Azure Container Apps (리비전 단위 무중단 배포), Azure Database for PostgreSQL (고가용성) |

선정 이유: [docs/adr/0001-backend-stack.md](docs/adr/0001-backend-stack.md)

## 데이터 모델

| 테이블 | 내용 |
| --- | --- |
| users | 로그인 정보 (provider, provider_subject, 탈퇴 정보) |
| refresh_tokens | 로그인 갱신 토큰 (회전·폐기) |
| companies | 기업·사업장 정보 (회원당 1곳). 회사명·담당자·업종·주소·지도 좌표·배출 정보·변경 버전 |
| company_profile_history | 기업 정보 변경 이력 |
| facility_import_rows | 전국폐기물처리업소표준데이터 원본 행 |
| treatment_snapshots | 처리 카탈로그 원본 데이터 |
| workflow_lots | 문진 번호·세부 재질·현재 물량 상태·후보 검토·진행 이력 |
| workflow_offers / workflow_photos | 기업 간 인수 요청·수락·QR 입고 상태와 물량 사진 |
| workflow_facility_accounts | 서비스 기업 계정과 공개 사업장 연결. 시험용 연결은 synthetic으로 구분 |
| wastes / route_steps / qr_field_checks / waste_completion_snapshots | 폐기물 카드·인계 단계·입고 확인·완료 시점 기록 |

공정 후보는 `treatment_snapshots`의 공개 참조와 명부를 조회하고, 실제 진행은 기업 소유 물량·인계 기록에 저장합니다. 문진 판정 원본은 diagnosis에서 관리합니다. 과거 간소화 문서는 당시 설계이며 현재 흐름은 [최신 연결 점검](docs/flow-audit-20261116.md)을 참고합니다.

## 현재 구조

```
scrap-server/
├─ AGENTS.md / CLAUDE.md     AI 코딩 에이전트 진입점 (규칙, 문서 지도, 작업 종료 루프)
├─ .agents/                  에이전트 역할·스킬 원본 (Claude Code·Codex 공용)
├─ .claude/                  Claude Code용 생성물 (scripts/sync_agents.py가 생성)
├─ .github/                  CI, 이슈·PR 템플릿
├─ docs/                     제품 정의, spec, ADR, todo, Git 규칙, 운영 절차
├─ scripts/                  sync_agents.py
├─ backend/                  FastAPI 서비스
│  ├─ app/
│  │  ├─ core/               설정, JWT, 공통 오류 형식
│  │  ├─ db/                 DB 엔진·세션
│  │  ├─ api/v1/             라우터 묶음 (/api/v1)
│  │  └─ domains/            auth, users, companies, diagnosis, wastes, facilities, transport, treatment
│  ├─ alembic/               마이그레이션
│  └─ tests/
└─ docker-compose.yml        api + PostgreSQL (호스트 포트 5433)
```

폴더별 책임과 의존 규칙: [docs/folder-architecture.md](docs/folder-architecture.md)

## 구현된 API

### 인증·회원·기업

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/v1/auth/{google\|microsoft}/login | 소셜 로그인 시작 |
| GET | /api/v1/auth/{provider}/callback | 로그인 완료, 쿠키 발급 |
| POST | /api/v1/auth/refresh | access·refresh 토큰 재발급 (refresh 회전) |
| POST | /api/v1/auth/logout | 로그아웃 (refresh 토큰 폐기) |
| POST | /api/v1/auth/dev-login | 개발용 로그인 (로컬 전용) |
| GET | /api/v1/users/me | 현재 사용자 (제공자, 기업 ID. 온보딩 전이면 기업 ID null) |
| POST | /api/v1/users/me/withdraw | 회원 탈퇴 (30일 뒤 삭제) |
| POST | /api/v1/companies | 기업·사업장 등록 (온보딩) |
| GET | /api/v1/companies/me | 내 기업 조회 |
| PATCH | /api/v1/companies/me | 내 기업 수정 (profile_version으로 충돌 감지) |
| GET | /api/v1/companies/me/history | 기업 정보 변경 이력 (페이지네이션) |

### 문진 (폐기물 분류번호 판정)

로그인한 기업의 요청을 문진 엔진(scrap-diagnosis) `/internal/v1`로 중계함. 응답 본문은 엔진 것 그대로임. spec: [docs/specs/diagnosis-engine-integration.md](docs/specs/diagnosis-engine-integration.md)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | /api/v1/diagnosis/cases | 문진 건 만들기 + 첫 질문 |
| GET | /api/v1/diagnosis/cases | 내 기업의 문진 건 목록 (status, page, size) |
| GET | /api/v1/diagnosis/cases/{id} | 건 상세 (판정, 대화, 서류, 인계 객체) |
| POST | /api/v1/diagnosis/cases/{id}/messages | 문진 답변 (말 또는 버튼) |
| POST | /api/v1/diagnosis/cases/{id}/documents | 서류 업로드 (값은 검수 대기) |
| POST | /api/v1/diagnosis/cases/{id}/documents/{doc}/versions | 서류 파일 교체 |
| POST | /api/v1/diagnosis/cases/{id}/documents/{doc}/values/apply | 검수한 서류 값 반영 |
| POST | /api/v1/diagnosis/cases/{id}/documents/{doc}/revoke | 서류 효력 해제 |
| POST | /api/v1/diagnosis/cases/{id}/confirm | 판정 확정 + 인계 객체(handoff) |
| POST | /api/v1/diagnosis/cases/{id}/reopen | 확정 건 다시 열기 |
| POST | /api/v1/diagnosis/cases/{id}/rebase | 바뀐 규칙으로 다시 평가 |
| GET | /api/v1/diagnosis/cases/{id}/trace | 판정 근거 추적 |
| GET | /api/v1/diagnosis/catalog/facts | 질문 항목·선택지 목록 |

법정 서식 작성본: 확정한 문진 건의 판정과 기업 정보로 현행 서식(HWPX) 칸을 채움. 저장·제출하지 않음. spec: [docs/specs/legal-forms.md](docs/specs/legal-forms.md)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | /api/v1/diagnosis/cases/{id}/legal-forms/{form6\|form12\|form5}/preview | 칸별 값 미리보기, 경고, 입력 문제 |
| POST | /api/v1/diagnosis/cases/{id}/legal-forms/{form6\|form12\|form5}?format=hwpx\|pdf | 작성본 파일 (한글 또는 PDF) |

### 처리 경로 데모

시연용 기능이며 QR 추적·업체 조회 기능을 정식으로 만들면 대체함.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/classification/profiles | 문진 유형 목록 |
| POST | /api/classification/sessions | 문진 세션 시작 |
| POST | /api/classification/sessions/{sessionId}/answer | 문진 답변 |
| POST | /api/classification/sessions/{sessionId}/undo | 문진 답변 되돌리기 |
| POST | /api/treatment/next-step | 다음 처리 공정 조회 |
| POST | /api/treatment/facility-candidates | 처리업체 후보 조회 |
| POST | /api/treatment/intake-review(s) | 업체 반입 검토 |
| POST | /api/treatment/facility-web-search | 업체 공개 웹 조사 |
| GET·PUT·PATCH·POST | /api/v1/transport/** | 현장 인계 기록 |
| POST | /api/v1/workflow/lots/{key}/photo-conflict-resolution | 사진·상태 설명 불일치의 사용자 확인 또는 수정 |

사진과 설명이 다르면 모든 업체 인수 요청을 먼저 막습니다. 사용자는 사유와 기존 문진 내용이 같다는 확인을 남기거나, 설명을 수정한 뒤 AI 검토를 다시 실행할 수 있습니다. 분류번호는 자동 변경하지 않으며 재질·발생 공정·유해성 답변이 달라지면 재문진을 안내합니다. 확인 기록은 수신 업체에 함께 전달되고 최종 수락은 업체가 합니다. [명세](docs/specs/photo-conflict-resolution.md)

오류는 모든 API에서 `{"code", "message", "details"}` 형식으로 반환함. 오류 코드 목록: [docs/specs/error-response.md](docs/specs/error-response.md)

## 문서

| 문서 | 내용 |
| --- | --- |
| [docs/product-plan.md](docs/product-plan.md) | 목적, 사용자, MVP 범위, 판단 원칙 |
| [docs/folder-architecture.md](docs/folder-architecture.md) | 폴더 구조와 책임 |
| [docs/todolist.md](docs/todolist.md) | 할 일과 진행 상태 |
| [docs/specs/](docs/specs/) | 기능 명세 |
| [docs/adr/](docs/adr/) | 기술 결정 기록 |
| [docs/team-conventions.md](docs/team-conventions.md) | 팀 공통 규칙: 레포 역할, 브랜치, PR, CI/CD, 배포, 비밀값 |
| [docs/git-workflow.md](docs/git-workflow.md) | 공통 규칙의 server 레포 적용: 저장소 연결, GitHub 설정 |
| [docs/runbooks/](docs/runbooks/) | 운영 절차 (Azure DB 이전) |
| [docs/agent-changelog.md](docs/agent-changelog.md) | 에이전트 문서 변경 이력 |

## 기여 방법

1. develop에서 `feat/T-xxx-설명` 형식으로 브랜치 생성
2. 작업 후 develop으로 PR (CI 통과 필수, main은 배포 담당자만 병합)
3. AI 에이전트를 쓰면 [AGENTS.md](AGENTS.md)의 규칙과 작업 종료 루프를 따름

자세한 규칙: [docs/team-conventions.md](docs/team-conventions.md)

## 사업장 주소 검색
기업 등록과 수정에서 `POST /api/v1/companies/location-search`로 주소·장소를 검색하고, 선택한 좌표를 기존 기업 정보 API로 저장합니다. 로그인 후 기업 등록 전에도 사용합니다. `COMPANY_GEOCODING_ENABLED=false`로 외부 검색을 끌 수 있고 `COMPANY_GEOCODING_URL`로 자체 Photon을 지정할 수 있습니다. 기본 공개 Photon은 소규모·단일 워커용(초당1회·캐시24시간)이며 국내 주소 누락과 서비스 장애가 가능합니다. 여러 서버로 운영할 때는 자체 서비스와 공유 호출 제한이 필요합니다. 검색 결과는 사용자가 지도에서 확인하며 정확한 건물/출입구를 보장하지 않습니다. [명세](docs/specs/company-onboarding.md).

## 거리순 업체 검토와 진행 상태

새 웹은 `POST /api/v1/workflow/lots/{id}/review-jobs`로 검토를 시작하고 `GET /api/v1/workflow/lots/{id}`의 `review_progress`로 실제 진행 단계를 읽습니다. 서버가 카카오 도로거리로 정렬한 가까운 5곳부터 공정 관련성을 검토하며, 명시적 제한·공정 연결 불명·AI 미완료 후보가 있으면 다음 사업장을 검토합니다. 5곳 미만이면 확인된 수만 반환합니다.

사진 관찰과 후보별 검토는 입력·모델 버전별로 재사용합니다. 인수 요청부터 예정 도로 경로를 표시하며 운송 중·입고와 구분합니다. 기존 동기 `candidates` API는 호환용으로 유지합니다. [명세](docs/specs/progressive-candidate-review.md)

업체의 공개 근거 검토는 PostgreSQL에 7일간(최대 1024건) 저장해 다른 처리 건에서도 재사용합니다. 기존 `treatment_snapshots`의 별도 kind를 사용하므로 마이그레이션은 없습니다. 업체 자료·모델/지침 버전이 바뀌면 다시 검토합니다. 사진·상태 설명·기업별 답변·물량 판단은 공용 캐시에 저장하지 않습니다. 공개 근거가 있는 후보만 이번 물량과 대조하며, 근거 부족 후보는 자료를 보강할 대상으로 남습니다. 캐시 TTL은 원문 사이트를 다시 수집했다는 뜻이 아닙니다.

실제 Azure에서 공용 캐시 초기화85.7초, 설명이 다른 새 물량35.6초(공개 근거9건 재사용·사진1회·물량1회)를 확인했습니다. [측정 범위와 한계](docs/public-review-cache-validation-20261119.md).

현재 검토의 목적은 **공정에 맞는 업체를 찾아 문의하는 것**입니다. 해당 사업장에서 그 재질을 재활용·제조한다는 자료를 확인하며, 세부 투입 규격을 공개하지 않았다고 후보에서 빼지 않습니다. 신규 `process_match`·`process_source`·`process_quote`는 공정 관련성과 그 출처입니다. 실제 반입 승인을 뜻하지 않습니다.

자동 증빙 문진 대신 사진·상태·물량을 B에게 보내고, B가 메신저에서 세부 반입조건을 협의한 뒤 수락합니다. 기존 답변 API와 이력은 호환 보존합니다. 무관 사진·설명 모순·명시적 취급 제외는 계속 검사합니다. [최신 검증 기록](docs/process-discovery-validation-20261119.md).
