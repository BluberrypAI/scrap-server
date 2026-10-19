# AGENTS.md

Re:Source AI 조직의 **server 레포**. 모든 AI 코딩 에이전트(Claude Code, Codex 등)의 공통 진입점임.
AI 기능(에이전트, MCP 도구, 지식 기반)은 ai 레포, Azure 리소스 정의는 infra 레포 담당이므로 이 레포에서 설계·구현하지 않음. ai 쪽 설계는 진행 중이므로 이 레포 문서에 확정된 것처럼 쓰지 않음 ([docs/adr/0002-repo-structure.md](docs/adr/0002-repo-structure.md)).

## 1. 문서 지도 (작업 전에 필요한 것만 읽음)

| 문서 | 언제 읽음 |
| --- | --- |
| [docs/product-plan.md](docs/product-plan.md) | 항상. 범위와 판단 원칙 확인 |
| [docs/folder-architecture.md](docs/folder-architecture.md) | 파일을 만들거나 옮길 때 |
| [docs/todolist.md](docs/todolist.md) | 작업 시작·종료 시 |
| [docs/specs/](docs/specs/) | 기능을 구현하거나 고칠 때 (해당 spec) |
| [docs/adr/](docs/adr/) | 기술 선택을 바꾸려 할 때 |
| [docs/agent-changelog.md](docs/agent-changelog.md) | 에이전트 문서를 고칠 때 |
| [docs/team-conventions.md](docs/team-conventions.md) | 브랜치·커밋·PR을 만들 때, 다른 레포와의 경계·API 형식을 바꿀 때 |
| [docs/git-workflow.md](docs/git-workflow.md) | server 레포의 GitHub 설정을 다룰 때 |
| [backend/README.md](backend/README.md) | 서버·DB를 실행할 때 |
| docs/runbooks/ | 서버 이전·운영 작업을 할 때 |

## 2. 공통 규칙

1. **spec 없이 구현하지 않음.** spec이 없으면 spec-writer 역할로 초안을 먼저 만들고 사용자 확인을 받음
2. **product-plan 범위 밖 요청은 구현하지 않고 사용자에게 확인함.** product-plan.md는 수정하지 않음. 기획서 원본·조사 자료는 레포에 올리지 않음 (docs/planning/, docs/research/는 .gitignore 대상)
3. 파일 위치는 folder-architecture.md를 따름. 구조를 바꿔야 하면 문서를 먼저 고치고 사용자 승인을 받음
4. product-plan 4장 판단 원칙을 코드로 지킴: 확인되지 않은 값은 추정해 채우지 않고 비워 둠
5. 비밀값은 코드에 쓰지 않고 `.env`(로컬) 또는 Key Vault(운영)를 사용함
6. 사용자에게 보이는 문서와 응답은 한국어로 씀. 코드 식별자와 커밋 메시지는 영어로 씀
7. develop·main에 직접 커밋하지 않음. 브랜치·커밋 규칙은 team-conventions.md를 따르고, push·PR·병합은 사용자가 요청할 때만 함
8. 다른 레포(ai, frontend)가 호출하는 API의 필드를 삭제·이름 변경·타입 변경하지 않음. 필요하면 멈추고 사용자에게 확인함 (team-conventions.md 1장)

## 3. 역할 (에이전트)

역할 정의 원본은 `.agents/agents/`에 있음. 해당 작업을 할 때 그 파일을 읽고 따름.

| 역할 | 파일 | 담당 |
| --- | --- | --- |
| backend-architect | .agents/agents/backend-architect.md | 구조, ADR, folder-architecture, 에이전트 문서 |
| spec-writer | .agents/agents/spec-writer.md | spec 초안, todolist 등록 |
| api-developer | .agents/agents/api-developer.md | 라우터·서비스·스키마 구현 |
| auth-specialist | .agents/agents/auth-specialist.md | OAuth, JWT, 보안 |
| db-engineer | .agents/agents/db-engineer.md | 모델, 마이그레이션 |
| test-engineer | .agents/agents/test-engineer.md | spec 완료 조건을 테스트로 작성 |
| code-reviewer | .agents/agents/code-reviewer.md | spec·구조 준수 검토 (수정하지 않음) |

## 4. 스킬

원본은 `.agents/skills/<name>/SKILL.md`. Codex는 이 위치를 직접 읽고, Claude Code는 `.claude/skills/`로 동기화된 사본을 읽음.

| 스킬 | 용도 |
| --- | --- |
| write-spec | spec 작성 |
| update-todo | todolist 갱신 |
| new-endpoint | 도메인 엔드포인트 추가 |
| db-migration | 모델 변경과 마이그레이션 |
| sync-agent-docs | 작업 종료 시 문서 영향 점검과 업데이트 질문 |

## 5. 작업 종료 루프 (모든 작업 끝에 반드시 수행)

루프 엔지니어링: 작업에서 얻은 변화를 에이전트 문서로 되돌려, 다음 작업의 에이전트가 더 정확하게 일하게 함.

1. **검증**: `uv run pytest`, `uv run ruff check .`를 backend/에서 실행하고 결과를 그대로 보고함
2. **todolist 갱신**: 작업한 항목의 상태를 바꾸고, 새로 생긴 할 일을 추가함
3. **문서 영향 점검**: 아래 표로 이번 작업이 어떤 문서에 영향을 주는지 판단함

   | 이번 작업에서 생긴 일 | 갱신 후보 |
   | --- | --- |
   | 폴더·파일 위치 규칙이 바뀌거나 새 도메인이 생김 | docs/folder-architecture.md, README.md(현재 구조) |
   | API가 추가·변경됨, 실행 방법·환경변수가 바뀜 | README.md(구현된 API), backend/README.md, .env.example |
   | 기술·라이브러리·구조 결정을 내리거나 바꿈 | docs/adr/ (새 ADR) |
   | 구현이 spec과 달라졌거나 spec에 없던 결정을 함 | docs/specs/해당 파일 |
   | 같은 절차를 두 번 이상 반복함, 에이전트가 실수한 패턴을 발견함 | .agents/skills/ (스킬 추가·보완) |
   | 역할 경계가 모호했거나 새 역할이 필요함 | .agents/agents/, AGENTS.md 3장 |
   | 공통 규칙이 부족해 잘못된 방향으로 작업함 | AGENTS.md 2장 |

4. **보고와 질문**: 점검 결과는 항상 보고함. **제안할 변경이 있을 때만** 아래 형식으로 묻고, **승인 전에는 에이전트 문서를 수정하지 않음**

   - 제안할 변경이 없으면: `문서 영향 점검: 영향 없음` 한 줄만 보고하고 질문하지 않음
   - 제안할 변경이 있으면:

   ```
   [에이전트 문서 업데이트 확인]
   - 점검 결과: (영향 있는 문서와 이유)
   - 제안 변경: (파일별 한 줄 요약)
   에이전트 문서를 업데이트할까요?
   ```

   사용자가 작업 지시와 함께 문서 변경을 직접 요청한 경우는 그 요청을 승인으로 봄

5. **승인 후 반영**: 문서를 고치고 `docs/agent-changelog.md`에 한 줄 기록함. `.agents/`를 바꿨으면 `uv run --project backend python scripts/sync_agents.py`로 `.claude/`를 동기화함

자세한 절차는 sync-agent-docs 스킬을 따름.

## 6. 명령어

실행 방법 전체는 [backend/README.md](backend/README.md) 참고.

```bash
docker compose up -d --build                  # Docker: API + PostgreSQL (DB 호스트 포트 5433)
cd backend
uv sync                                       # 로컬: 의존성 설치 (기본 DB는 SQLite)
uv run alembic upgrade head                   # 마이그레이션 적용
uv run uvicorn app.main:app --reload          # 개발 서버 (http://localhost:8000/docs)
uv run pytest                                 # 테스트
uv run ruff check . && uv run ruff format .   # 린트·포맷
uv run python ../scripts/sync_agents.py       # .agents → .claude 동기화 (--check: 검사만)
```

CI(.github/workflows/ci.yml)는 PR마다 위 검사를 PostgreSQL 기준으로 실행함.
