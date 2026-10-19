# Re:Source AI Backend

FastAPI 기반 백엔드 API. **팀 표준은 A(Docker)** 이며, B는 Docker 없이 빠르게 확인할 때의 보조 방법임.

| 방식 | 필요한 것 | DB | 용도 |
| --- | --- | --- | --- |
| [A. Docker](#a-docker로-실행) **(표준)** | Docker Desktop | PostgreSQL (컨테이너) | 평소 개발. 운영과 같은 DB |
| [B. 로컬](#b-로컬에서-실행) | Python 3.12, uv | SQLite 또는 직접 설치한 PostgreSQL | Docker 없이 코드만 빠르게 확인 |

이 문서는 **server 단독 실행** 방법임. ai·frontend까지 함께 띄우려면 infra 레포의 통합 실행을 사용함 ([docs/team-conventions.md](../docs/team-conventions.md) 2장).

실행 후 공통 주소:

- API 문서 (Swagger): http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

---

## A. Docker로 실행

Python 설치 없이 API 서버와 PostgreSQL을 함께 띄움.

### 1. 준비

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치 후 실행

### 2. 실행 (저장소 루트에서)

```bash
cp .env.example backend/.env      # 처음 한 번 (Windows PowerShell: Copy-Item .env.example backend\.env)
docker compose up -d --build      # API + DB 실행, 시작 시 마이그레이션 자동 적용
```

- `backend/app/` 코드를 고치면 서버가 자동으로 재시작됨
- `pyproject.toml`(의존성)을 바꾸면 `docker compose up -d --build`로 다시 빌드

### 3. 자주 쓰는 명령

```bash
docker compose logs -f api                          # 서버 로그
docker compose exec api alembic upgrade head        # 마이그레이션 수동 적용
docker compose exec db psql -U resource             # DB 접속
docker compose down                                 # 중지 (데이터 유지)
docker compose down -v                              # 중지 + DB 데이터 삭제
```

### 4. DB 접속 정보 (DBeaver 등 외부 도구)

| 항목 | 값 |
| --- | --- |
| 호스트 / 포트 | localhost / **5433** |
| DB / 사용자 / 비밀번호 | resource / resource / resource |

호스트 포트가 5432가 아닌 이유: PC에 PostgreSQL이 이미 설치돼 있으면 5432가 충돌함. 바꾸려면 루트에 `.env` 파일을 만들고 `POSTGRES_HOST_PORT=원하는포트`를 넣음.

---

## B. 로컬에서 실행

### 1. 준비

- [uv](https://docs.astral.sh/uv/getting-started/installation/) 설치
  - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Python은 uv가 3.12를 자동으로 내려받으므로 따로 설치하지 않아도 됨

### 2. 실행 (backend 폴더에서)

```bash
cd backend
cp ../.env.example .env                   # 처음 한 번 (기본값: SQLite)
uv sync                                   # 의존성 설치
uv run alembic upgrade head               # 테이블 생성 (backend/local.db)
uv run uvicorn app.main:app --reload      # 서버 실행
```

### 3. DB 선택

`backend/.env`의 `DATABASE_URL`을 바꿈.

| DB | DATABASE_URL |
| --- | --- |
| SQLite (기본) | `sqlite+aiosqlite:///./local.db` |
| 직접 설치한 PostgreSQL | `postgresql+asyncpg://<user>:<password>@localhost:5432/<db>` |
| Docker DB만 사용 (`docker compose up -d db`) | `postgresql+asyncpg://resource:resource@localhost:5433/resource` |

SQLite 주의: 운영 DB는 PostgreSQL임. PostgreSQL 전용 기능(JSONB, pgvector 등)을 쓰는 기능은 SQLite에서 동작하지 않음. SQLite에서는 외래키 제약이 검사되지 않는 등 동작이 조금 다르므로, DB 관련 작업은 PR의 CI(PostgreSQL)에서 최종 확인함. SQLite를 초기화하려면 `local.db`를 지우고 `uv run alembic upgrade head`를 다시 실행함.

---

## 개발 명령 (backend 폴더에서)

```bash
uv run pytest                                  # 테스트 (메모리 SQLite)
uv run ruff check . && uv run ruff format .    # 린트·포맷
uv run alembic revision --autogenerate -m "..."  # 마이그레이션 생성 (.agents/skills/db-migration 참고)
```

PostgreSQL로 테스트하려면 (Docker DB 실행 중일 때, 테스트용 DB `resource_test`를 한 번 만들어 둠):

```bash
docker compose exec db psql -U resource -c "CREATE DATABASE resource_test"
TEST_DATABASE_URL=postgresql+asyncpg://resource:resource@localhost:5433/resource_test uv run pytest
```

## Swagger에서 인증이 필요한 API 테스트하기

소셜 로그인은 브라우저가 Google·Microsoft로 이동했다가 돌아오는 방식이라 Swagger 안에서는 실행할 수 없음. 대신 **개발용 로그인**을 사용함 (OAuth 키 불필요).

1. http://localhost:8000/docs 에서 `POST /api/v1/auth/dev-login` → **Try it out** → **Execute**
   - 본문을 비우면 기본 사용자(`dev@example.com`)로 로그인. 다른 사용자가 필요하면 `{"email": "other@example.com"}`
2. 끝. 쿠키가 브라우저에 저장되어 같은 Swagger 화면에서 다른 API가 바로 인증됨
   - Postman·curl에서는 응답의 `access_token`을 `Authorization: Bearer <토큰>` 헤더로 사용

개발용 로그인은 `APP_ENV`가 `local`일 때만 존재하고, 운영(`prod`)에서는 경로 자체가 없음.

실제 소셜 로그인을 확인하려면 `backend/.env`에 Google·Microsoft 키를 설정하고 ([docs/specs/auth-social-login.md](../docs/specs/auth-social-login.md) 4장) 브라우저에서 http://localhost:8000/api/v1/auth/google/login 에 접속함.

## 설정 (환경변수)

전체 목록과 설명은 [.env.example](../.env.example) 참고. 주요 항목:

| 변수 | 설명 |
| --- | --- |
| `DATABASE_URL` | DB 주소. SQLite / PostgreSQL / Azure PostgreSQL |
| `DB_SSL` | Azure PostgreSQL은 `require` |
| `DOCS_ENABLED` | Swagger 노출 여부 |
| `JWT_SECRET`, `SESSION_SECRET` | 운영(`APP_ENV=prod`)에서는 기본값이면 실행되지 않음 |
| `GOOGLE_*`, `MICROSOFT_*` | 소셜 로그인 키 |

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `port is already allocated` (5433 또는 8000) | 다른 프로그램이 포트 사용 중. 루트 `.env`에 `POSTGRES_HOST_PORT` 변경, 또는 8000을 쓰는 프로그램 종료 |
| `connection was closed in the middle of operation` | 다른 PostgreSQL에 접속 중일 가능성. 포트(Docker는 5433) 확인 |
| `/api/v1/auth/google/login`이 503 | `.env`에 `GOOGLE_CLIENT_ID`가 비어 있음 |
| `no such table` | 마이그레이션 미적용. `uv run alembic upgrade head` |
