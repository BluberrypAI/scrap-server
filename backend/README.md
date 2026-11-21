# scrap-server backend

[← scrap-server](../README.md)

FastAPI 기반 백엔드 API. **팀 표준은 A(Docker)** 이며, B는 Docker 없이 빠르게 확인할 때의 보조 방법임.

| 방식 | 필요한 것 | DB | 용도 |
| --- | --- | --- | --- |
| [A. Docker](#a-docker로-실행) **(표준)** | Docker Desktop | PostgreSQL (컨테이너) | 평소 개발. 운영과 같은 DB |
| [B. 로컬](#b-로컬에서-실행) | Python 3.12, uv | SQLite 또는 직접 설치한 PostgreSQL | Docker 없이 코드만 빠르게 확인 |

이 문서는 **server 단독 실행** 방법임. web·diagnosis·route까지 함께 띄우려면 scrap-infra의 통합 실행을 사용함 ([docs/team-conventions.md](../docs/team-conventions.md) 2장).

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
- 문진 엔진까지 띄우려면 `ENGINE_REPO_DIR=../scrap-diagnosis docker compose --profile engine up -d --build` (기본 경로 `../resource_engine`은 옛 폴더 이름). 엔진 없이 띄우면 문진 API는 503 `ENGINE_UNAVAILABLE`
- `--profile storage`는 Blob Storage 에뮬레이터(azurite)

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

SQLite 주의: 운영 DB는 PostgreSQL임. SQLite에서는 외래키 제약이 검사되지 않는 등 동작이 조금 다르므로, DB 관련 작업은 PR의 CI(PostgreSQL)에서 최종 확인함. SQLite를 초기화하려면 `local.db`를 지우고 `uv run alembic upgrade head`를 다시 실행함.

---

## 처리 경로 데이터 적재

공정·업체 후보는 DB의 공정 참조 데이터에서 찾으므로, 마이그레이션 후 한 번 적재함. 실행할 때마다 참조 데이터를 갈아끼움.

```bash
uv run python -m app.domains.treatment.import_catalog
```

전국 명부까지 넣으려면 [공공데이터포털 전국폐기물처리업소표준데이터](https://www.data.go.kr/data/15114147/standard.do)의 JSON 배열과 그 파일의 SHA-256을 지정함. 기록된 스냅샷은 2026-10-21 수집본임.

```bash
uv run python -m app.domains.treatment.import_catalog --registry /path/to/national-facility-registry.json --sha256 b083ea497c37bb11bd9374fc0a5b0850b989d290dbdba9d4a713fef353e79c08
```

### 기업 간 인계 시험용 업체 연결

인수 요청은 업체(사업장)에 연결된 수신 기업 계정이 있어야 보낼 수 있음. 웹의 개발용 로그인으로 `pp-sort@example.com`(PP·PE 선별·파쇄), `pp-pellet@example.com`(PP·PE 펠렛·컴파운드), `al-can@example.com`(알루미늄캔)에 각각 로그인해 기업 등록까지 마친 뒤 실행함.

```bash
uv run python -m app.domains.transport.dev_accounts
uv run python -m app.domains.transport.dev_accounts --email b@example.com --facility sarom-hwaseong-2   # 다른 계정·업체
```

`APP_ENV=local`·`test`에서만 동작하고 연결은 시험용(synthetic)으로 표시됨. 운영 시연에서만 `DEMO_FACILITY_BINDINGS=true`로 켬.

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

**처리업체 계정 (B·C)**: 회원가입 없이 팀이 명령으로 발급하고 로그인 화면의 아이디·비밀번호 폼으로 로그인함. 업체 정보는 DB의 처리 공정표 스냅샷에서 가져옴 ([docs/specs/facility-password-login.md](../docs/specs/facility-password-login.md)). 배포 DB에 만들려면 `DATABASE_URL`을 운영 DB로 두고 실행함

```bash
uv run python -m app.domains.auth.facility_accounts --list   # 업체 키 목록
uv run python -m app.domains.auth.facility_accounts --all --password-stdin   # 전체 업체 (아이디 = 업체 키, 비밀번호 공통)
uv run python -m app.domains.auth.facility_accounts --login-id sarom-hwaseong   --facility sarom-hwaseong-2 --contact-email manager@example.com   # 비밀번호는 프롬프트 입력
```

1. http://localhost:8000/docs 에서 `POST /api/v1/auth/dev-login` → **Try it out** → **Execute**
   - 본문을 비우면 기본 사용자(`dev@example.com`)로 로그인. 다른 사용자가 필요하면 `{"email": "other@example.com"}`
2. 쿠키가 브라우저에 저장되어 같은 Swagger 화면에서 다른 API가 바로 인증됨
   - Postman·curl에서는 응답의 `access_token`을 `Authorization: Bearer <토큰>` 헤더로 사용

개발용 로그인은 `APP_ENV`가 `local`·`test`일 때만 존재하고, 운영(`prod`)에서는 경로 자체가 없음.

실제 소셜 로그인을 확인하려면 `backend/.env`에 Google·Microsoft 키를 설정하고 ([docs/specs/auth-social-login.md](../docs/specs/auth-social-login.md) 4장) 브라우저에서 http://localhost:8000/api/v1/auth/google/login 에 접속함.

## 설정 (환경변수)

전체 목록과 설명은 [.env.example](../.env.example) 참고.

| 변수 | 설명 |
| --- | --- |
| `APP_ENV` | `local` · `test` · `prod`. `local`·`test`에서만 개발용 로그인과 시험용 업체 연결이 열림 |
| `DATABASE_URL`, `DB_SSL` | DB 주소. SQLite / PostgreSQL. SSL이 필요한 DB는 `DB_SSL=require` |
| `DOCS_ENABLED` | Swagger 노출 여부 |
| `JWT_SECRET`, `SESSION_SECRET` | 운영(`APP_ENV=prod`)에서는 기본값이면 실행되지 않음 |
| `GOOGLE_*`, `MICROSOFT_*` | 소셜 로그인 키 |
| `BACKEND_URL` | 소셜 로그인 콜백 주소의 기준 (`{BACKEND_URL}/api/v1/auth/{provider}/callback`). 콘솔에 등록한 리디렉션 URI와 같아야 함 |
| `FRONTEND_URL`, `CORS_ORIGINS` | 로그인 뒤 돌려보낼 화면 주소, 허용 출처 |
| `COOKIE_DOMAIN`, `COOKIE_SECURE`, `COOKIE_SAMESITE` | 프론트가 다른 도메인이면 `COOKIE_SAMESITE=none`, `COOKIE_SECURE=true` |
| `WITHDRAWAL_GRACE_DAYS` | 탈퇴 후 실제 삭제까지 유예 일수 (기본 30) |
| `DIAGNOSIS_ENGINE_URL` | 문진 엔진(scrap-diagnosis) 주소 (예: `http://localhost:8030`). 비우면 `/api/v1/diagnosis/*`는 503, 탈퇴 purge는 엔진 삭제를 건너뜀 |
| `ENGINE_SERVICE_TOKEN` | 엔진 `/internal/v1` Bearer 토큰. 엔진과 같은 값. 운영에서 URL만 있고 토큰이 없으면 시작하지 않음 |
| `DIAGNOSIS_ENGINE_TIMEOUT_SECONDS` | 엔진 응답 대기 (코드 기본 200초). 엔진의 모델 대기 × 4보다 커야 함 |
| `AI_BASE_URL` | scrap-route 주소. 업체 AI 검토·공개 웹 조사에 씀. Docker에서 PC의 route를 부르면 `http://host.docker.internal:<포트>` |
| `SCRAP_INTAKE_SERVICE_TOKEN` | scrap-route 호출 토큰. route와 같은 값 |
| `KAKAO_MOBILITY_REST_API_KEY` | 카카오모빌리티 자동차 길찾기 REST 키 (서버 전용). 없으면 도로거리 미확인·직선거리로 명시 |
| `OSRM_DEMO_ENABLED` | 카카오 키 없이 공개 OSRM으로 도로거리 조회 (시연용, 기본 false). 카카오 키가 있으면 카카오 우선 |
| `COMPANY_GEOCODING_ENABLED`, `COMPANY_GEOCODING_URL` | 사업장 주소 검색. 기본 공개 Photon은 소규모·단일 워커용이며 운영은 자체 제공자 권장 |
| `DEMO_FACILITY_BINDINGS` | 시연용(synthetic) 업체 연결을 운영에서도 허용 (기본 false) |
| `CLASSIFICATION_BASE_URL` | 이전 문진 엔진 주소. `/api/classification/*` 호환 경로용, 현재 웹은 쓰지 않음 |

## 프론트엔드와 함께 실행

프론트(scrap-web)는 `/api/v1`과 `/api/treatment`를 **같은 출처**로 호출함. 로그인 쿠키(httpOnly)가 프론트 주소에 저장되어야 하기 때문임. 개발 중에는 Vite가, 운영에서는 nginx가 `/api/` 요청을 이 서버로 넘김.

1. 이 서버를 8000 포트로 실행 (위 A 또는 B). `BACKEND_URL`, `FRONTEND_URL`은 `.env.example` 기본값 그대로 둠
2. 프론트에서 `npm run dev` (Vite가 `/api`를 `http://127.0.0.1:8000`으로 전달. 바꾸려면 프론트 `.env`의 `SCRAP_SERVER_URL`)
3. 브라우저에서 **`http://localhost:5173`**을 엶. `127.0.0.1:5173`이나 서버 주소(8000)로 열지 않음

**개발용 로그인**: OAuth 키 없이 로그인 화면의 "개발용 로그인" 버튼(프론트 dev 모드에서만 보임)을 누르면 됨.

**실제 소셜 로그인**: 기본값이면 콜백 주소가 `http://localhost:8000/api/v1/auth/{google|microsoft}/callback`이 됨. Google·Microsoft 콘솔에 이 주소를 리디렉션 URI로 등록함 (Microsoft는 앱 등록 > 인증 > 웹).

```env
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173
```

쿠키는 포트를 구분하지 않으므로 호스트(`localhost`)만 같으면 OAuth 상태 쿠키와 로그인 쿠키가 둘 다 프론트에서 보임. 반대로 `localhost`와 `127.0.0.1`은 쿠키가 따로 저장되므로 브라우저 주소, `BACKEND_URL`, `FRONTEND_URL`의 호스트를 모두 `localhost`로 맞춤. 서버는 로그인 뒤 `/onboarding` 같은 일반 경로로 보내고, 프론트가 이를 해시 주소(`/#/onboarding`)로 바꿈.

운영처럼 nginx 한 주소로 서비스할 때는 `BACKEND_URL`과 `FRONTEND_URL`을 둘 다 그 주소로 두고, 콘솔에도 `{그 주소}/api/v1/auth/{provider}/callback`을 등록함.

## 동작 메모

- **업체 검토 작업**: `POST /api/v1/workflow/lots/{id}/review-jobs`는 202와 작업을 반환하고, 앱 lifespan의 워커가 DB에 저장된 작업을 처리함 (별도 큐 서비스 없음). 진행은 `GET /lots/{id}`의 `review_progress`(queued·running·completed·failed·interrupted). 재시작으로 lease가 만료된 작업은 interrupted로 남고 재시도 때 완료된 캐시를 재사용함
- **5곳 선정**: 현재 보유 기업 사업장에서 도로거리순으로 가까운 후보부터 공정 관련성을 검토하고, 명시적 제한·공정 연결 불명·AI 미완료 후보가 있으면 다음 사업장으로 채움. 5곳 미만이면 확인된 수만 반환 ([spec](../docs/specs/progressive-candidate-review.md))
- **공개 근거 캐시**: 업체 공개 근거 검토는 `treatment_snapshots.kind=public-intake-cache-v1`에 7일·최대 1024건 저장해 다른 물량에서도 재사용함. 사진·중량·상태 설명·기업별 답변은 저장하지 않음
- **도로거리**: 카카오 키가 있으면 카카오, `OSRM_DEMO_ENABLED=true`면 공개 OSRM. 외부 조회가 실패해도 직선거리를 도로거리로 바꿔 표시하지 않으며, 카카오 응답은 DB에 저장하지 않음 ([spec](../docs/specs/road-distance.md))

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `port is already allocated` (5433 또는 8000) | 다른 프로그램이 포트 사용 중. 루트 `.env`에 `POSTGRES_HOST_PORT` 변경, 또는 8000을 쓰는 프로그램 종료 |
| `connection was closed in the middle of operation` | 다른 PostgreSQL에 접속 중일 가능성. 포트(Docker는 5433) 확인 |
| `/api/v1/auth/google/login`이 503 | `.env`에 `GOOGLE_CLIENT_ID`가 비어 있음 |
| `/api/v1/diagnosis/*`가 503 `ENGINE_UNAVAILABLE` | `DIAGNOSIS_ENGINE_URL`이 비었거나 엔진이 꺼져 있음 |
| `no such table` | 마이그레이션 미적용. `uv run alembic upgrade head` |
| 처리 경로 후보가 비어 있음 | 공정 참조 미적재. `uv run python -m app.domains.treatment.import_catalog` |
| 추천 업체가 0곳 | 기업 좌표가 없거나 도로거리를 못 구함. 기업 정보의 지도 위치와 `KAKAO_MOBILITY_REST_API_KEY` 또는 `OSRM_DEMO_ENABLED` 확인 |
| Microsoft·Google 화면에 `redirect_uri is not valid` | 콘솔에 등록한 리디렉션 URI와 `{BACKEND_URL}/api/v1/auth/{provider}/callback`이 다름 |
| 소셜 로그인 뒤 `/login?error=oauth_failed` | 로그인 시작과 콜백의 호스트가 다름. 브라우저를 `http://localhost:5173`으로 열고 `BACKEND_URL`도 `localhost`로 둠 |
| 로그인했는데 프론트에서 계속 401 | 브라우저 주소와 `FRONTEND_URL`의 호스트가 다름 (`localhost` ↔ `127.0.0.1`) |
