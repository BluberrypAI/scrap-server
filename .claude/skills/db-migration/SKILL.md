---
name: db-migration
description: SQLAlchemy 모델을 추가·변경한 뒤 Alembic 마이그레이션을 생성·검토·적용할 때 사용.
---
<!-- 생성물: .agents/skills/db-migration/SKILL.md 를 수정하고 scripts/sync_agents.py 로 동기화하세요 -->

# db-migration

## 절차

1. 모델 작성·수정 (`backend/app/domains/<domain>/models.py`)
   - `Base`, `TimestampMixin`(created_at, updated_at) 상속
   - PK는 `uuid.UUID` (`default=uuid.uuid4`)
   - 문자열은 길이 지정 (`String(200)`)
   - 열거형은 `Enum(<StrEnum>, native_enum=False)` (SQLite 테스트 호환)
2. 새 모델 파일이면 `backend/app/db/all_models.py`에 import 추가
3. 로컬 DB 실행 확인: `docker compose up -d db` (호스트에서 접속할 때 포트는 **5433**. 5432는 PC에 설치된 다른 PostgreSQL일 수 있음)
4. 생성:
   ```bash
   cd backend
   uv run alembic revision --autogenerate -m "<무엇을 바꿨는지 영어로>"
   ```
5. **생성된 파일을 반드시 읽고 검토함**
   - 의도하지 않은 `drop_table`, `drop_column`이 없는가
   - 컬럼 이름 변경이 삭제+추가로 잡히지 않았는가 (그렇다면 `op.alter_column`으로 고침)
   - 기존 데이터가 있는 테이블에 NOT NULL 컬럼을 추가하면 `server_default`가 있는가
   - 시간 기본값이 `server_default=sa.func.now()`인가. SQLite를 기준으로 생성하면 `sa.text('(CURRENT_TIMESTAMP)')`처럼 SQLite 표현이 들어가므로 고침
   - `uv run alembic check`가 "No new upgrade operations detected."를 출력하는가 (모델과 마이그레이션 일치)
6. 적용과 되돌리기 확인:
   ```bash
   uv run alembic upgrade head
   uv run alembic downgrade -1
   uv run alembic upgrade head
   ```
7. `uv run pytest` (테스트는 메타데이터로 SQLite에 테이블을 만들므로 마이그레이션과 별개로 확인)

## 주의

- 데이터가 사라지는 변경은 사용자 확인 후에만 진행
- 이미 공유된 마이그레이션 파일은 수정하지 않고 새 마이그레이션을 만듦
