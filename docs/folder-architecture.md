# Folder Architecture

> 폴더 구조와 폴더별 책임을 정하는 문서. 구조가 바뀌면 이 문서를 먼저 고치고 구현함 (담당: backend-architect).

## 0. 조직 레포 구성

이 레포는 조직의 **server** 레포임. 레포별 역할은 [adr/0002-repo-structure.md](adr/0002-repo-structure.md), 공통 규칙은 [team-conventions.md](team-conventions.md).

| 레포 | 이 레포와의 관계 |
| --- | --- |
| `.github` | 공통 규칙(CONTRIBUTING)과 이슈·PR 템플릿의 원본. 조직 기본 이슈 템플릿이 Private 레포에 적용되지 않아 이 레포에도 같은 이슈 템플릿을 복사해 둠. PR 템플릿은 server용으로 덮어씀 |
| `infra` | 이 레포를 `../server`로 참조해 전체를 compose로 실행 |
| `ai` | 에이전트, MCP 도구, 지식 기반 (설계 중). server는 `AI_BASE_URL`로 HTTP 호출함 (`domains/treatment/`) |
| `frontend` | server API를 호출. CORS·쿠키 설정 대상 |

## 1. 전체 구조

```
ReSource/
├─ README.md                   # 사람용 진입점: 소개, 빠른 시작, 현재 구조, 문서 목록
├─ AGENTS.md                   # 모든 AI 에이전트의 진입점: 문서 지도, 공통 규칙, 작업 종료 루프
├─ CLAUDE.md                   # @AGENTS.md + Claude Code 전용 설정
│
├─ docs/
│  ├─ product-plan.md          # 목적, 사용자, MVP 범위, 판단 원칙 (사람만 수정)
│  ├─ folder-architecture.md   # 이 문서
│  ├─ todolist.md              # 할 일과 진행 상태
│  ├─ agent-changelog.md       # 에이전트 문서 변경 이력 (루프 기록)
│  ├─ team-conventions.md      # 조직 공통 규칙 (레포 역할, 브랜치, CI/CD, 배포). .github 레포의 CONTRIBUTING 원본
│  ├─ git-workflow.md          # 공통 규칙의 server 레포 적용 (저장소 연결, GitHub 설정)
│  ├─ specs/                   # 기능 명세 (기능 1개 = 파일 1개)
│  ├─ adr/                     # 되돌리기 어려운 결정과 이유
│  ├─ runbooks/                # 운영 절차 (Azure DB 이전 등)
│
├─ .agents/                    # 에이전트·스킬 원본 (도구 공용, 여기만 수정)
│  ├─ agents/*.md              # 역할 정의
│  └─ skills/<name>/SKILL.md   # 스킬 (Agent Skills 표준, Codex가 직접 읽음)
├─ .claude/                    # Claude Code용 생성물 (직접 수정 금지)
│  ├─ agents/                  # scripts/sync_agents.py가 생성
│  ├─ skills/                  # scripts/sync_agents.py가 생성
│  └─ settings.json            # Claude Code 권한 설정 (직접 수정 가능)
├─ scripts/
│  └─ sync_agents.py           # .agents → .claude 동기화, --check로 검사
├─ .github/
│  ├─ workflows/ci.yml         # 린트, 동기화 검사, 마이그레이션, PostgreSQL 테스트
│  ├─ ISSUE_TEMPLATE/          # 기능, 버그, 작업 (조직 .github 레포와 같은 내용)
│  └─ pull_request_template.md
│
├─ backend/                    # FastAPI 서비스 (실행 방법: backend/README.md)
├─ docker-compose.yml          # server 단독 개발용: api + PostgreSQL(호스트 포트 5433), storage 프로필로 Azurite
├─ .env.example
└─ .gitignore
```

AI 기능(에이전트, MCP 도구, 지식 기반)은 ai 레포, Azure 리소스 정의(Bicep)는 infra 레포에 둠. 이 레포에 해당 폴더를 만들지 않음.

## 2. backend 구조

```
backend/
├─ README.md                   # 실행 방법 (Docker / 로컬)
├─ pyproject.toml / uv.lock
├─ Dockerfile
├─ alembic.ini
├─ alembic/                    # 마이그레이션 (versions/에 이력)
├─ app/
│  ├─ main.py                  # 앱 생성, 미들웨어, 라우터 등록
│  ├─ core/
│  │  ├─ config.py             # 환경변수 (pydantic-settings)
│  │  ├─ security.py           # JWT 발급·검증
│  │  └─ errors.py             # 공통 오류 응답 형식, 오류 코드, 예외 핸들러
│  ├─ db/
│  │  ├─ base.py               # DeclarativeBase, 공통 컬럼
│  │  ├─ session.py            # 엔진, 세션, get_db
│  │  └─ all_models.py         # Alembic이 읽을 모델 등록
│  ├─ api/v1/router.py         # 도메인 라우터 묶음 (/api/v1)
│  └─ domains/
│     ├─ auth/                 # 소셜 로그인, 토큰 쿠키, 현재 사용자 의존성
│     ├─ users/                # 사용자 (로그인 수단 provider, provider_subject 포함)
│     ├─ companies/            # 기업 프로필, 폐기물 프로필 (온보딩)
│     ├─ transport/            # 현장 인계 기록 (QR 확인 기능으로 옮길 예정)
│     └─ treatment/            # 처리 경로 데모: 처리 카탈로그, 업체 후보 조회 (/api/treatment, /api/classification)
└─ tests/
```

### 도메인 폴더 내부 규칙

| 파일 | 책임 | 의존 가능 대상 |
| --- | --- | --- |
| router.py | HTTP 입출력, 상태 코드, 의존성 주입 | service, schemas, dependencies |
| service.py | 업무 규칙 | repository, models |
| repository.py | DB 조회·저장 (선택, 조회가 단순하면 생략) | models |
| models.py | SQLAlchemy 테이블 | db.base |
| schemas.py | Pydantic 입출력 스키마 | (없음) |

### 의존 방향

```
api → domains/*/router → service → repository → models → db
                       ↘ schemas
core는 어디서든 사용 가능, domains는 서로의 router를 import하지 않음
```

## 3. 폴더별 책임 요약

| 폴더 | 책임 | 수정 주체 |
| --- | --- | --- |
| docs/product-plan.md | 제품 정의 | 사람 |
| README.md, backend/README.md | 사람용 소개·실행 방법 | 구조·실행 방법·API가 바뀐 작업의 담당 에이전트 |
| docs/specs/ | 기능 요구사항과 완료 조건 | spec-writer 초안 → 사람 확정 |
| docs/todolist.md | 작업 상태 | 작업한 에이전트 |
| docs/adr/, folder-architecture.md | 구조·기술 결정 | backend-architect (사용자 승인 후) |
| .agents/ | 에이전트·스킬 정의 | 사용자 승인 후에만 수정 (AGENTS.md 작업 종료 루프) |
| .claude/agents, .claude/skills | 생성물 | sync_agents.py만 |
| backend/ | API 구현 | api-developer, auth-specialist, db-engineer, test-engineer |
