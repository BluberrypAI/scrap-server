# Runbook: 로컬 DB → Azure Database for PostgreSQL 이전

> 앱 코드는 바꾸지 않음. 환경변수(`DATABASE_URL`, `DB_SSL`)만 바꿔서 이전함.

## 0. 전제

- 제공 Azure 자원 확인 완료 (todolist T-008)
- 로컬 PostgreSQL 기준으로 개발·테스트 완료 (SQLite 데이터는 이전 대상이 아님. 필요한 데이터는 PostgreSQL에서 다시 만듦)

## 1. 서버 생성 (Azure Portal)

| 항목 | 값 (권장) |
| --- | --- |
| 서비스 | Azure Database for PostgreSQL - Flexible Server |
| 버전 | 16 (로컬 docker-compose와 동일) |
| 컴퓨팅 | Burstable B1ms (개발·시연용) |
| 인증 | PostgreSQL 인증 (MVP), 이후 Entra 인증 검토 |
| 네트워크 | 공용 액세스 + 방화벽 규칙 (App Service 아웃바운드 IP, 작업자 IP) |

생성 후 DB `resource`를 만듦.

## 2. 연결 설정

```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<server>.postgres.database.azure.com:5432/resource
DB_SSL=require
APP_ENV=prod
```

- 로컬에서 접속 확인: 위 값을 `backend/.env`에 임시로 넣고 `uv run alembic current`
- 운영 서버에서는 `.env` 파일 대신 App Service 환경변수 또는 Key Vault 참조로 설정함

## 3. 스키마 적용

```bash
cd backend
uv run alembic upgrade head
uv run alembic current        # head 리비전이 나오면 완료
```

배포 컨테이너는 시작할 때 `alembic upgrade head`를 자동 실행함 (Dockerfile CMD).

## 4. 데이터 이전 (필요할 때만)

로컬 Docker DB 데이터를 그대로 옮길 때:

```bash
# 로컬 Docker DB에서 데이터만 덤프 (스키마는 3단계 alembic으로 이미 생성)
docker compose exec -T db pg_dump -U resource --data-only --exclude-table=alembic_version resource > data.sql

# Azure로 복원
psql "host=<server>.postgres.database.azure.com port=5432 dbname=resource user=<user> sslmode=require" -f data.sql
```

## 5. 확인

- [ ] `GET /health` 200
- [ ] 소셜 로그인 후 `users`, `social_accounts`에 행 생성
- [ ] 기업 온보딩 후 `companies`, `waste_profiles`에 행 생성
- [ ] `DOCS_ENABLED`를 운영 정책에 맞게 설정

## 6. 되돌리기

`DATABASE_URL`을 이전 값으로 되돌리고 재시작함. 스키마를 되돌려야 하면 `uv run alembic downgrade <리비전>`.
