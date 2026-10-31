from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorResponse, register_error_handlers
from app.domains.auth.dev_router import router as dev_auth_router

DESCRIPTION = """
기업 폐기물 처리 의사결정 AI 에이전트 **Re:Source AI**의 백엔드 API.

**인증**: 소셜 로그인 후 발급되는 `access_token` 쿠키 또는 `Authorization: Bearer <token>` 헤더.
Swagger에서는 오른쪽 위 **Authorize**에 access 토큰을 넣으면 됨.
"""

TAGS = [
    {"name": "auth", "description": "Google·Microsoft 소셜 로그인, 토큰 갱신·로그아웃"},
    {"name": "users", "description": "현재 사용자"},
    {"name": "companies", "description": "기업·폐기물 프로필 (온보딩)"},
    {"name": "reviews", "description": "검토 생성·조회, 입력 항목 정리와 보완 질문"},
    {"name": "documents", "description": "증빙 문서 업로드·교체, 측정값 검수"},
    {"name": "health", "description": "서버 상태 확인"},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.docs_enabled
    app = FastAPI(
        title="Re:Source AI API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    if settings.app_env in ("local", "test"):
        app.include_router(dev_auth_router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
