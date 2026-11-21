import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorResponse, register_error_handlers
from app.db import all_models as _all_models  # noqa: F401
from app.domains.auth.dev_router import router as dev_auth_router
from app.domains.transport.public_inquiry_replies import ProtectPublicInquiryReplies
from app.domains.treatment.router import classification_router
from app.domains.treatment.router import router as treatment_router

DESCRIPTION = """
기업 폐기물 처리 의사결정 AI 에이전트 **Re:Source AI**의 백엔드 API.

**인증**: 소셜 로그인 후 발급되는 `access_token` 쿠키 또는 `Authorization: Bearer <token>` 헤더.
Swagger에서는 오른쪽 위 **Authorize**에 access 토큰을 넣으면 됨.
"""

TAGS = [
    {"name": "auth", "description": "Google·Microsoft 소셜 로그인, 토큰 갱신·로그아웃"},
    {"name": "users", "description": "현재 사용자"},
    {"name": "companies", "description": "기업·폐기물 프로필 (온보딩)"},
    {"name": "health", "description": "서버 상태 확인"},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.docs_enabled

    @asynccontextmanager
    async def lifespan(app):
        from app.domains.transport.review_jobs import worker

        task = asyncio.create_task(worker()) if settings.app_env != "test" else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(
        title="Re:Source AI API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        # Replaces FastAPI's default 422 schema in the docs with the common error format.
        responses={422: {"model": ErrorResponse, "description": "요청 값 검증 실패"}},
    )

    # Holds OAuth state/nonce between /login and /callback only.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="oauth_session",
        max_age=600,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.state.inquiry_reply_rate_limit_enabled = settings.app_env != "test"
    app.add_middleware(ProtectPublicInquiryReplies)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(treatment_router)
    app.include_router(classification_router)
    if settings.app_env in ("local", "test"):
        app.include_router(dev_auth_router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
