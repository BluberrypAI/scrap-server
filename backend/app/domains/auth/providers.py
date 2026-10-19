from typing import Any

from authlib.integrations.starlette_client import OAuth

from app.core.config import get_settings

GOOGLE = "google"
MICROSOFT = "microsoft"
SUPPORTED_PROVIDERS = (GOOGLE, MICROSOFT)

oauth = OAuth()
_settings = get_settings()

oauth.register(
    GOOGLE,
    client_id=_settings.google_client_id,
    client_secret=_settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
oauth.register(
    MICROSOFT,
    client_id=_settings.microsoft_client_id,
    client_secret=_settings.microsoft_client_secret,
    server_metadata_url=(
        f"https://login.microsoftonline.com/{_settings.microsoft_tenant}"
        "/v2.0/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email profile"},
)


def is_configured(provider: str) -> bool:
    settings = get_settings()
    return bool(getattr(settings, f"{provider}_client_id"))


def validate_microsoft_issuer(claims: dict[str, Any], value: str) -> bool:
    """The multi-tenant metadata advertises issuer ".../{tenantid}/v2.0" as a template,
    so Authlib's default exact-match check always fails. Match against the token's tid."""
    tid = claims.get("tid")
    return bool(tid) and value == f"https://login.microsoftonline.com/{tid}/v2.0"


def claims_options(provider: str) -> dict[str, Any] | None:
    if provider == MICROSOFT:
        return {"iss": {"essential": True, "validate": validate_microsoft_issuer}}
    return None  # Authlib validates issuer from discovery metadata


def extract_email(provider: str, userinfo: dict[str, Any]) -> str | None:
    email = userinfo.get("email")
    if provider == MICROSOFT and not email:
        # Personal accounts often omit `email`; preferred_username is the sign-in address.
        email = userinfo.get("preferred_username")
    return email
