# Re:Source AI Backend

FastAPI 기반 백엔드 API. **팀 표준은 A(Docker)** 이며, B는 Docker 없이 빠르게 확인할 때의 보조 방법임.

업체별 반입 확인을 추가했습니다. 후보별 질문·답변 → AI 재검토 → 수신 업체 조건 제시 → 발송 업체 자료 제출 → 수신 업체 최종 확인 → QR 입고 순서입니다. 전국 명부의 다른 업체도 조회·확인 목록 저장이 가능합니다. [API 명세](../docs/specs/intake-conditions-local.md)와 [검증 결과·남은 데이터](../docs/verification/intake-conditions-20261114.md)를 참고하세요. AI의 `intake_answers` 지원 버전을 먼저 적용해야 합니다. 기존 JSON 업무 기록에 저장하므로 새 마이그레이션은 없습니다.

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
| `BACKEND_URL` | 소셜 로그인 콜백 주소의 기준 (`{BACKEND_URL}/api/v1/auth/{provider}/callback`). Google·Microsoft 콘솔에 등록한 리디렉션 URI와 똑같아야 함 |
| `FRONTEND_URL` | 로그인 뒤 돌려보낼 화면 주소 (`/onboarding`, `/login?error=...`) |
| `DIAGNOSIS_ENGINE_URL` | 문진 엔진 주소 (예: `http://localhost:8030`). 비우면 `/api/v1/diagnosis/*`는 503, 탈퇴 purge는 엔진 삭제를 건너뜀 |
| `ENGINE_SERVICE_TOKEN` | 엔진 `/internal/v1` Bearer 토큰. 엔진과 같은 값. 운영에서 URL만 있고 토큰이 없으면 시작하지 않음 |
| `AI_BASE_URL` | AI 서버(ai 레포) 주소. 처리 경로 데모(`/api/treatment/*`)가 업체 검토·웹 조사에 씀. Docker에서 PC의 서버를 부르면 `http://host.docker.internal:<포트>` |

## 프론트엔드와 함께 실행

프론트(scrap-web)는 `/api/v1`을 **같은 출처**로 호출함. 로그인 쿠키(httpOnly)가 프론트 주소에 저장되어야 하기 때문임. 개발 중에는 Vite가, 운영에서는 nginx가 `/api/` 요청을 이 서버로 넘김.

1. 이 서버를 8000 포트로 실행 (위 A 또는 B). `BACKEND_URL`, `FRONTEND_URL`은 `.env.example` 기본값 그대로 둠
2. 프론트에서 `npm run dev` (Vite가 `/api/v1`을 `http://127.0.0.1:8000`으로 전달. 바꾸려면 프론트 `.env`의 `SCRAP_SERVER_URL`)
3. 브라우저에서 **`http://localhost:5173`**을 엶. `127.0.0.1:5173`이나 서버 주소(8000)로 열지 않음

**개발용 로그인**: OAuth 키 없이 로그인 화면의 "개발용 로그인" 버튼(프론트 dev 모드에서만 보임)을 누르거나, `POST /api/v1/auth/dev-login`을 프론트 주소로 호출하면 됨 (`APP_ENV=local`에서만 있음).

**실제 소셜 로그인**: 기본값이면 콜백 주소가 `http://localhost:8000/api/v1/auth/{google|microsoft}/callback`이 됨. Google·Microsoft 콘솔에 이 주소를 리디렉션 URI로 등록함 (Microsoft는 앱 등록 > 인증 > 웹).

```env
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173
```

로그인 시작은 프론트(5173)를 거치고 콜백은 서버(8000)로 바로 오지만, 쿠키는 포트를 구분하지 않으므로 호스트(`localhost`)만 같으면 OAuth 상태 쿠키와 로그인 쿠키가 둘 다 프론트에서 보임. 반대로 `localhost`와 `127.0.0.1`은 쿠키가 따로 저장되므로 브라우저 주소, `BACKEND_URL`, `FRONTEND_URL`의 호스트를 모두 `localhost`로 맞춤. 서버는 로그인 뒤 `/onboarding` 같은 일반 경로로 보내고, 프론트가 이를 해시 주소(`/#/onboarding`)로 바꿈.

운영처럼 nginx 한 주소로 서비스할 때는 `BACKEND_URL`과 `FRONTEND_URL`을 둘 다 그 주소로 두고, 콘솔에도 `{그 주소}/api/v1/auth/{provider}/callback`을 등록함.

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `port is already allocated` (5433 또는 8000) | 다른 프로그램이 포트 사용 중. 루트 `.env`에 `POSTGRES_HOST_PORT` 변경, 또는 8000을 쓰는 프로그램 종료 |
| `connection was closed in the middle of operation` | 다른 PostgreSQL에 접속 중일 가능성. 포트(Docker는 5433) 확인 |
| `/api/v1/auth/google/login`이 503 | `.env`에 `GOOGLE_CLIENT_ID`가 비어 있음 |
| `no such table` | 마이그레이션 미적용. `uv run alembic upgrade head` |
| Microsoft·Google 화면에 `redirect_uri is not valid` | 콘솔에 등록한 리디렉션 URI와 `{BACKEND_URL}/api/v1/auth/{provider}/callback`이 다름. 기본값이면 `http://localhost:8000/...`을 등록 |
| 소셜 로그인 뒤 `/login?error=oauth_failed` | 로그인 시작과 콜백의 호스트가 다름. 브라우저를 `http://localhost:5173`으로 열고 `BACKEND_URL`도 `localhost`로 둠 |
| 로그인했는데 프론트에서 계속 401 | 브라우저 주소와 `FRONTEND_URL`의 호스트가 다름 (`localhost` ↔ `127.0.0.1`) |
## SCRAP 처리경로와 전국 명부

2026-11-14 참조는 29개 사업장·68개 공정 연결입니다. 공개 사업장 공정에 근거한 연결 47개와 역할 확인이 필요한 21개를 구분합니다. 소재·형태별 조회와 합성 기업 인계 검증은 [확장 기록](../docs/plastic-facility-expansion.md)을 참고하세요. 문진 엔진의 신규 소재 분류 지원을 뜻하지 않습니다.

마이그레이션 후 `backend/`에서 `uv run python -m app.domains.treatment.import_catalog`를 실행해 공정 참조 데이터를 적재합니다.

전국 명부는 [공공데이터포털 원본](https://www.data.go.kr/data/15114147/standard.do)의 JSON 배열을 사용합니다. 기록된 스냅샷은 2026-10-21 수집본 9,604행입니다. 새 스냅샷에는 해당 파일의 확인된 SHA-256을 지정합니다.

```bash
uv run python -m app.domains.treatment.import_catalog --registry /path/to/national-facility-registry.json --sha256 b083ea497c37bb11bd9374fc0a5b0850b989d290dbdba9d4a713fef353e79c08
```

`/api/treatment/next-step`과 `/api/treatment/facility-candidates`는 서버 DB를 조회합니다. `CLASSIFICATION_BASE_URL`은 별도 팀 문진 엔진 주소입니다. 신규 로트 문진 유형은 GET /api/classification/profiles에서 조회합니다. 문진을 마친 뒤 첫 공정 조회에 classification_session_id를 보내면 서버가 분류 기록을 대조합니다. 다음 공정의 전체 업체 검토(`/api/treatment/intake-reviews`)와 지원 소재 공정의 추가 공개 웹 조사(`/api/treatment/facility-web-search`)는 `AI_BASE_URL`과 두 서비스의 같은 `SCRAP_INTAKE_SERVICE_TOKEN`을 사용합니다.

웹 조사에는 `transition_key`, `input_form`, `region`을 보냅니다. 서버가 등록 공정의 재질·공정명·단계를 붙여 AI에 전달하며, 기업 정보·사진·좌표는 이 호출에 포함하지 않습니다. 검색 결과는 조사 단서이며 업체 연결이나 인수 승인으로 자동 저장하지 않습니다. 다음 공정 응답의 `process_previews_truncated`는 후속 미리보기 생략 여부입니다. 현재 상태의 직접 공정 후보는 미리보기 한도 때문에 빠지지 않습니다.

기업 간 인계(`/api/v1/workflow/*`)를 로컬에서 시험하려면 업체에 수신 기업 계정이 연결돼 있어야 인수 요청을 보낼 수 있습니다. 웹의 개발용 로그인으로 `pp-sort@example.com`(PP·PE 선별·파쇄), `pp-pellet@example.com`(PP·PE 펠렛·컴파운드), `al-can@example.com`(알루미늄캔 판재·잉곳)에 각각 로그인해 기업을 등록한 뒤 아래를 실행합니다. `APP_ENV=local`·`test`에서만 동작하며, 연결은 실제 업체 확인이 아닌 시험용(synthetic)으로 표시됩니다.

```bash
uv run python -m app.domains.transport.dev_accounts
```
# 2026-11-15 로컬 통합 변경

- 기업 생성·수정은 선택 필드 `site_latitude`, `site_longitude`를 함께 받습니다. 함께 null로 보내면 해제되며, 주소만 바꾸면 이전 좌표는 지워집니다.
- 확정 문진의 경로 조회·AI 검토와 `/api/v1/workflow/lots` 등록은 선택 boolean `solid_confirmed`(기본 false)를 받습니다. 문진에 고체 여부가 없는 경우에만 사용자 확인을 보완하며, 액체·슬러지 응답을 덮어쓰지 않습니다.
- 경로 응답의 `requires_solid_confirmation`이 true이면 화면에서 고체 상태를 확인받습니다. 좌표로 비교하는 거리는 직선거리입니다.
- 실행 구성, 7개 합성 기업 인계 시험과 소재별 한계: [통합 검증 결과](../docs/full-stack-validation-20261115.md).
