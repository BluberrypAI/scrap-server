---
name: new-endpoint
description: backend에 새 도메인이나 API 엔드포인트를 추가할 때 사용. 라우터·서비스·스키마 작성, 라우터 등록, 테스트까지의 절차.
---
<!-- 생성물: .agents/skills/new-endpoint/SKILL.md 를 수정하고 scripts/sync_agents.py 로 동기화하세요 -->

# new-endpoint

## 전제

확정된 spec이 있어야 함. 없으면 write-spec 스킬부터 수행함.

## 새 도메인 추가 시

```
backend/app/domains/<domain>/
├─ __init__.py
├─ models.py        # 테이블이 있을 때 (db-migration 스킬)
├─ schemas.py
├─ repository.py    # 조회가 단순하면 생략하고 service에서 처리
├─ service.py
└─ router.py
```

folder-architecture.md 2장에 도메인을 추가함 (작업 종료 루프에서 승인 후).

## 절차

1. **schemas.py**: 요청은 `<Name>Create`/`<Name>Update`, 응답은 `<Name>Read`(`model_config = ConfigDict(from_attributes=True)`)
2. **service.py**: 업무 규칙과 예외. HTTP 예외 대신 도메인 예외를 던지거나 None을 반환하고, 상태 코드는 router가 정함
3. **router.py**: `APIRouter(prefix="/<복수형>", tags=["<domain>"])`. 인증이 필요하면 `CurrentUser` 의존성 사용
   ```python
   from app.domains.auth.dependencies import CurrentUser
   from app.db.session import DbSession

   @router.get("/me", response_model=CompanyRead)
   async def read_my_company(user: CurrentUser, db: DbSession) -> Company: ...
   ```
4. **등록**: backend/app/api/v1/router.py에 `api_router.include_router(...)`
5. **테스트**: backend/tests/test_<domain>.py에 spec 완료 조건별 테스트 (`client`, `auth_client` 픽스처 사용)
6. **확인**: `uv run pytest`, `uv run ruff check .`, http://localhost:8000/docs 에서 문서 확인

## 하지 않는 것

- router에서 DB 쿼리 직접 작성
- ORM 객체를 스키마 없이 반환
- 다른 도메인의 router import
