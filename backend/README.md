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
uv run python -m app.domains.users.purge       # 삭제 예정일이 지난 탈퇴 사용자 삭제 (운영은 하루 1회 스케줄)
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

### AI 서버 없이 전체 흐름 확인하기

`backend/.env`에 `AI_ENGINE_MODE=mock`을 넣고 서버를 다시 시작하면 AI 서버 없이 고정 샘플로 검토 실행이 끝남. 결과의 `limitations` 첫 줄에 가짜 응답이라고 표시됨. 입력이 달라도 후보는 같으므로 판정 내용이 아니라 입출력과 흐름을 확인하는 용도임 ([docs/specs/dev-mock-engine.md](../docs/specs/dev-mock-engine.md)).

Swagger 호출 순서:

1. `POST /auth/dev-login` → `POST /companies`
2. `POST /reviews` → `GET /reviews/{reviewId}/intake` → `PATCH /reviews/{reviewId}/intake` (material, quantity_kg 답변)
3. (선택) `POST /reviews/{reviewId}/documents` → `POST /documents/{documentId}/dev-values` → `PATCH /documents/{documentId}/values/{valueId}`
4. `POST /reviews/{reviewId}/runs` → `GET /reviews/{reviewId}/runs/{runId}`
5. `GET .../candidates`, `GET .../candidates/plan-b`, `GET .../review-queue`, `GET .../tasks`
6. `POST /reviews/{reviewId}/supplements` → `POST .../risks/plan-b-r1/evidence` → `POST .../candidates/plan-b/risk-steps/1/decision`
7. `POST .../runs/{runId}/rerun` → `GET /reviews/{reviewId}/compare`

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
| `WITHDRAWAL_GRACE_DAYS` | 탈퇴 후 실제 삭제까지 유예 일수 (기본 30) |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | 업로드 문서 저장 폴더(기본 `./uploads`)와 최대 크기(기본 20MB) |
| `AI_BASE_URL` | AI 엔진(ai 레포) 주소. 비우면 검토 실행이 503. Docker에서 PC의 엔진을 부르면 `http://host.docker.internal:<포트>` |
| `AI_TIMEOUT_SECONDS` | 엔진 응답 대기 시간 (기본 300초) |
| `AI_ENGINE_MODE` | `http`(기본, 실제 엔진) 또는 `mock`(AI 서버 없이 고정 샘플). prod에서 mock이면 시작되지 않음 |

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `port is already allocated` (5433 또는 8000) | 다른 프로그램이 포트 사용 중. 루트 `.env`에 `POSTGRES_HOST_PORT` 변경, 또는 8000을 쓰는 프로그램 종료 |
| `connection was closed in the middle of operation` | 다른 PostgreSQL에 접속 중일 가능성. 포트(Docker는 5433) 확인 |
| `/api/v1/auth/google/login`이 503 | `.env`에 `GOOGLE_CLIENT_ID`가 비어 있음 |
| `no such table` | 마이그레이션 미적용. `uv run alembic upgrade head` |
## SCRAP 처리경로와 전국 명부

마이그레이션 후 `backend/`에서 `uv run python -m app.domains.treatment.import_catalog`를 실행해 공정 참조 데이터를 적재합니다.

전국 명부는 [공공데이터포털 원본](https://www.data.go.kr/data/15114147/standard.do)의 JSON 배열을 사용합니다. 기록된 스냅샷은 2026-10-21 수집본 9,604행입니다. 새 스냅샷에는 해당 파일의 확인된 SHA-256을 지정합니다.

```bash
uv run python -m app.domains.treatment.import_catalog --registry /path/to/national-facility-registry.json --sha256 b083ea497c37bb11bd9374fc0a5b0850b989d290dbdba9d4a713fef353e79c08
```

`/api/treatment/next-step`과 `/api/treatment/facility-candidates`는 서버 DB를 조회합니다. `CLASSIFICATION_BASE_URL`은 별도 팀 문진 엔진 주소입니다. 다음 공정의 전체 업체 검토(`/api/treatment/intake-reviews`)와 PP 공정의 추가 공개 웹 조사(`/api/treatment/facility-web-search`)는 `AI_BASE_URL`과 두 서비스의 같은 `SCRAP_INTAKE_SERVICE_TOKEN`을 사용합니다.
