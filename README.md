# SCRAP

> **최신: 세부 재질 연결 보완(2026-11-15)** — 포장재 PP·PE·PET, PA6 폐어망, SAN·PA66·PC/ABS, 알루미늄 스크랩을 확정 번호 그대로 연결했습니다. 실제 문진 18종 중 13종, 형태 조합 52개 중 49개에 후보가 나옵니다. Azure 290건은 공개 근거 확인 38건·추가 근거 필요 252건입니다. 현재 참조 50곳·60공정·106연결, 역할 추정 11개. 아래 기록은 확장 전 결과입니다. [최신 결과·남은 공백·적용 방법](docs/material-detail-e2e-20261115.md)

> **2026-11-15 실제 문진부터 다시 검사:** 플라스틱·금속 18개 선택지(일반 번호 12개)를 실제 문진으로 확정하고 웹에서 확인했습니다. 업체까지 연결되는 선택지는 9개이며, 그 안의 형태 32개 중 30개에 후보가 있습니다. 포장재·폐어망·기타 수지·일반 비철 등의 세부 재질 연결은 아직 빠져 있습니다. Azure 후보 검토 174건 중 공개 근거 확인 23건, 근거 부족 151건이었습니다. 아래의 공정 직접 조회 검사와 구분해 주세요. [번호별 실제 결과와 남은 작업](docs/classification-route-e2e-20261115.md)

> **2026-11-15 후속 경로 누락 보완:** 현재 로컬 참조는 **50곳·59개 공정·105개 공정–업체 연결**입니다. 지원 소재의 **54개 공정·100개 연결**을 실제 HTTP 198회로 조회했습니다(나머지 5개는 범위 밖 종이). 최종 경로 자료가 끊겨도 바로 다음 공정을 표시하고, 업체 미연결 공정도 근거·확인 조건을 남깁니다. 철스크랩 2곳과 EPS 감용 사업장 1곳을 추가했으며, 지역별 공개 웹 조사를 PP 외 지원 소재에도 연결했습니다. 이것은 등록 자료의 조회 검증이지 모든 업체의 반입 승인 검증이 아닙니다. [현재 범위와 남은 일](docs/route-coverage-20261115.md) · [EPS 연결과 PE·PS 베일 보류 이유](docs/registry-screen/bale-eps-review-20261115.md)

> **2026-11-15 5개 레포 통합 시험 당시 기록(위 확장 전):** PP·PET·PE의 A→B/A→B→C와 알루미늄 음료캔 A→B, 총 7개 합성 기업 시나리오에서 Azure 검토·수락·QR·완료를 확인했습니다. 회사 위치 저장과 직선거리 Top 5, 문진에 빠진 고체 확인을 보완했습니다. 당시 공정 연결은 **102개**, 조회한 것은 **97개**였으며 고철은 위 후속 작업에서 연결했습니다. **최신 develop + 기존 확장 PR + 로컬 수정**의 결과이며 자세한 범위와 재현 방법은 [통합 검증 결과](docs/full-stack-validation-20261115.md)를 보세요.

> **2026-11-14 플라스틱 업체 추가 확장:** 공정 참조는 **47곳·102개 연결**입니다(직전 37곳·81개). 공개 사업장 공정에 근거한 연결 88개와 역할 확인이 남은 14개를 구분합니다. 전국 명부의 재활용업 조사 대상 1,935묶음을 공식 공장등록 220,705행과 대조했고, 이름·주소 일치 323묶음은 조사 목록으로 보존했습니다. 이번에는 그 자료와 기업 원문을 검토해 10곳을 추가했습니다. 일치한 323곳을 전부 검증한 것은 아닙니다. PE·PS 베일 3개 입력 조합은 국내 수령 근거가 부족해 계속 보류합니다. [업체·검증 결과](docs/plastic-facility-expansion.md) · [전체 조사 목록과 남은 일](docs/registry-screen/README.md). 적용: `backend/`에서 `uv run python -m app.domains.treatment.import_catalog`.

> **이번 통합 브랜치의 PP 검증:** 문진 확정 → 상태·사진 → 업체 AI 검토 → 수신 기업 수락 → QR 입고 → 실제 산출물 → 다음 인계/완료를 연결했습니다. 별도 가상 기업 계정으로 A→B와 A→B→C를 웹에서 완료했습니다. 기존 본문의 단계 표는 팀 계획이며 이번 구현 범위·실제 검증·미확인 항목은 [PP 기업별 검증 기록](docs/pp-company-e2e.md)과 [구현 명세](docs/specs/pp-company-workflow.md)를 참고하세요.

> 버려지는 자원을 연결하고 앝태한다

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
| 온보딩 | 소셜 로그인, 기업·사업장 정보 등록 | **구현** |
| S1 품목 입력 | 자유 서술에서 품목 단서 추출 | 설계 중 (ai) |
| S2 문진 | 질문 응답으로 8자리 분류번호 확정 | 설계 중 (ai) |
| S3 허용 유형 조회 | 분류번호 → R유형(그룹별), 사전 분석 필요 여부 | 설계 중 (ai) |
| S4 업체 조회 | 분류번호 허가 범위 + 거리로 처리업체 매칭 | 설계 중 (ai 에이전트 추천 검토) |
| S5 문서 작성 | 문의·위탁 문서 초안 (LLM) | 예정 |
| S6 결과 보관 | 판정 결과와 이력 보관 | 예정 |
| 추적/안내 | 폐기물 건별 QR 발급, 인계 현장 확인 기록 | 예정 (지금은 처리 경로 데모) |

판정 경로(분류번호, 허용 R유형)에는 LLM을 쓰지 않음. 법령은 빌드 타임에 구조화해 두고 런타임에는 조회만 하므로, 같은 입력에는 항상 같은 결과가 나옴. AI는 입력 해석, 문서 초안, 빌드 타임 검증에만 씀.

## 조직 레포 구성

| 레포 | 역할 |
| --- | --- |
| **server (이 레포)** | API, 인증·회원, 기업·사업장 정보, DB 스키마 |
| ai | 문진·판정 엔진, 에이전트, MCP 도구, 지식 기반 |
| frontend | 화면 |
| infra | 전체 통합 실행(compose), Azure 리소스 정의 |
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
| DB | PostgreSQL 16 (로컬 개발은 SQLite도 가능) |
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
| companies | 기업·사업장 정보 (회원당 1곳). 회사명, 담당자 이메일, 업종, 사업장 이름·주소, 배출시설, 주생산품, 주 폐기물 종류 |
| company_profile_history | 기업 정보 변경 이력 |
| facility_import_rows | 전국폐기물처리업소표준데이터 원본 행 |
| treatment_snapshots | 처리 카탈로그 원본 데이터 |

폐기물 건, QR 현장 확인, 처리 경로 단계, 시설 테이블은 문진·업체 추천 로직이 정해진 뒤 추가함 ([docs/specs/db-schema-simplify.md](docs/specs/db-schema-simplify.md)).

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
