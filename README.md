# SCRAP

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
│  │  └─ domains/            auth, users, companies, wastes, facilities, transport, treatment
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
