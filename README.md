# Re:Source AI

중소 제조기업 폐기물 담당자를 위한 **폐기물 처리 의사결정 AI 에이전트**의 **server 레포**.
폐기물 정보를 자연어·문서로 입력하면 리스크를 반영한 경제성·환경성 기준으로 처리 방식을 비교하고, 근거가 담긴 보고서를 만듦.

- 제품 목적과 범위: [docs/product-plan.md](docs/product-plan.md)
- **팀 공통 규칙 (레포 역할, 브랜치, CI/CD, 배포): [docs/team-conventions.md](docs/team-conventions.md)**

## 조직 레포 구성

| 레포 | 역할 |
| --- | --- |
| **server (이 레포)** | API, 인증·회원, 기업 정보, DB 스키마 |
| ai | 에이전트, MCP 도구, 지식 기반 |
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
| 인프라 (예정) | Azure (App Service, Azure Database for PostgreSQL, Azure OpenAI 등) |

선정 이유: [docs/adr/0001-backend-stack.md](docs/adr/0001-backend-stack.md)

## 현재 구조

```
ReSource/
├─ AGENTS.md / CLAUDE.md     AI 코딩 에이전트 진입점 (규칙, 문서 지도, 작업 종료 루프)
├─ .agents/                  에이전트 역할·스킬 원본 (Claude Code·Codex 공용)
├─ .claude/                  Claude Code용 생성물 (scripts/sync_agents.py가 생성)
├─ .github/                  CI, 이슈·PR 템플릿
├─ docs/                     제품 정의, spec, ADR, todo, Git 규칙, 운영 절차
├─ scripts/                  sync_agents.py
├─ backend/                  FastAPI 서비스
│  ├─ app/
│  │  ├─ core/               설정, JWT
│  │  ├─ db/                 DB 엔진·세션
│  │  ├─ api/v1/             라우터 묶음 (/api/v1)
│  │  └─ domains/            auth, users, companies (도메인 단위)
│  ├─ alembic/               마이그레이션
│  └─ tests/
└─ docker-compose.yml        api + PostgreSQL (호스트 포트 5433)
```

폴더별 책임과 의존 규칙: [docs/folder-architecture.md](docs/folder-architecture.md)

### 구현된 API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/v1/auth/{google\|microsoft}/login | 소셜 로그인 시작 |
| GET | /api/v1/auth/{provider}/callback | 로그인 완료, 쿠키 발급 |
| POST | /api/v1/auth/refresh | access·refresh 토큰 재발급 (refresh 회전) |
| POST | /api/v1/auth/logout | 로그아웃 (refresh 토큰 폐기) |
| POST | /api/v1/auth/dev-login | 개발용 로그인 (로컬 전용) |
| GET | /api/v1/users/me | 현재 사용자 (제공자, 기업 ID) |
| POST | /api/v1/users/me/withdraw | 회원 탈퇴 (30일 뒤 삭제) |
| POST | /api/v1/companies | 기업·사업장 등록 (온보딩) |
| GET | /api/v1/companies/me | 내 기업 조회 |
| PATCH | /api/v1/companies/me | 내 기업 수정 (profile_version으로 충돌 감지) |
| GET | /api/v1/companies/me/history | 기업 정보 변경 이력 (페이지네이션) |

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
