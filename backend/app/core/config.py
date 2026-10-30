from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 실행환경 설정 (local, test, prod)
    app_env: Literal["local", "test", "prod"] = "local"
    # Swagger UI (/docs) 표시 여부. prod에서는 False로 설정하는 것을 권장.
    docs_enabled: bool = True

    # 기본값 SQLite (개발 환경용)
    database_url: str = "sqlite+aiosqlite:///./local.db"  # Docker/Azure는 postgresql+asyncpg://...
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # DB 연결 암호화 여부(TLS). Azure PostgreSQL은 필수이므로 DB_SSL=require로 설정
    db_ssl: Literal["disable", "require"] = "disable"

    # JWT 설정
    jwt_secret: str = INSECURE_SECRET  # 서명 키
    jwt_algorithm: str = "HS256"  # 서명 알고리즘
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # 탈퇴 후 30일 지나면 영구 삭제
    withdrawal_grace_days: int = 30
    # 소셜 로그인 중 Authlib가 사용하는 임시 세션 쿠키 서명 키
    session_secret: str = INSECURE_SECRET

    # 백엔드 및 프론트엔드 URL 설정
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    # 쿠키 설정 (도메인, 보안, SameSite 정책)
    cookie_domain: str | None = None
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # OAuth 클라이언트 설정 (Google, Microsoft)
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant: str = "common"

    # 업로드 문서 저장 위치(로컬 폴더)와 최대 크기. 운영은 Blob Storage로 바꿀 예정
    upload_dir: str = "./uploads"
    max_upload_mb: int = 20

    # 모델 검증 및 유틸리티
    @model_validator(mode="after")
    def _reject_insecure_secrets_in_prod(self) -> "Settings":
        # prod에서는 비밀키를 change-me로 두거나 SQLite를 사용하면 안 됨
        if self.app_env == "prod":
            if INSECURE_SECRET in (self.jwt_secret, self.session_secret):
                raise ValueError("JWT_SECRET and SESSION_SECRET must be set in prod")
            if not self.is_postgres:
                raise ValueError("DATABASE_URL must point to PostgreSQL in prod")
        if not self.cookie_domain:  # 쿠키 도메인이 설정되지 않은 경우 None으로 둠
            self.cookie_domain = None
        return self

    # PostgreSQL 사용 여부 확인
    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


# 설정 캐시 및 가져오기
@lru_cache
def get_settings() -> Settings:
    return Settings()
