"""문진 엔진(scrap-diagnosis) /internal/v1 호출 클라이언트.

엔진 규약: resource_engine docs/api/server-engine-contract.md.
엔진 응답 본문은 가공하지 않고 그대로 돌려줌 (엔진이 필드를 추가해도 server를 고치지 않게).
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import Depends, status

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, ErrorDetail

logger = logging.getLogger(__name__)

INTERNAL_PREFIX = "/internal/v1"

# 엔진 코드 중 그대로 돌려줄 것 (프론트가 분기함)
PASSTHROUGH_CODES = {
    ErrorCode.CASE_NOT_FOUND,
    ErrorCode.DOCUMENT_NOT_FOUND,
    ErrorCode.CASE_NOT_DIAGNOSABLE,
    ErrorCode.ALREADY_CONFIRMED,
    ErrorCode.NOT_CONFIRMABLE,
    ErrorCode.NOT_REOPENABLE,
    ErrorCode.CODE_MISMATCH,
    ErrorCode.CONCURRENT_UPDATE,
    ErrorCode.KB_CHANGED,
    ErrorCode.DOCUMENT_VERSION_MISMATCH,
    ErrorCode.FILE_TOO_LARGE,
    ErrorCode.UNSUPPORTED_DOCUMENT,
    ErrorCode.VALIDATION_ERROR,
}


class EngineUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.ENGINE_UNAVAILABLE,
            "문진 엔진을 사용할 수 없음. 잠시 뒤 다시 시도해 주세요",
        )


@dataclass
class EngineResponse:
    status_code: int
    body: Any


def _problems(details: Any) -> list[ErrorDetail] | None:
    """서류 값 형식 오류 details.problems[{key, reason}] → [{field, message}].

    다른 details는 버림.
    """
    if not isinstance(details, dict) or not isinstance(details.get("problems"), list):
        return None
    out = []
    for item in details["problems"]:
        if isinstance(item, dict):
            out.append(
                ErrorDetail(field=str(item.get("key", "")), message=str(item.get("reason", "")))
            )
    return out or None


def _to_app_error(res: httpx.Response) -> AppError:
    """엔진 오류 응답을 공통 오류 형식으로 바꿈."""
    try:
        detail = res.json().get("detail") or {}
    except (ValueError, AttributeError):
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    code = detail.get("code")
    message = detail.get("message") or "요청을 처리하지 못함"

    # 엔진 인증·설정 문제와 엔진 내부 오류는 브라우저에 원인을 알리지 않음
    if (
        res.status_code in (401, 403)
        or res.status_code >= 500
        or code
        in (
            "COMPANY_REQUIRED",
            "ENDPOINT_DISABLED",
            "AUTH_REQUIRED",
        )
    ):
        logger.error("Diagnosis engine error %s %s: %s", res.status_code, code, message)
        return EngineUnavailableError()

    if code in PASSTHROUGH_CODES:
        details = _problems(detail.get("details")) if code == ErrorCode.VALIDATION_ERROR else None
        return AppError(res.status_code, ErrorCode(code), message, details=details)

    # 표에 없는 코드는 HTTP 상태로 처리
    logger.warning("Unmapped diagnosis engine error %s %s: %s", res.status_code, code, message)
    if res.status_code == 404:
        return AppError(404, ErrorCode.NOT_FOUND, "대상을 찾을 수 없음")
    if res.status_code in (400, 422):
        return AppError(422, ErrorCode.VALIDATION_ERROR, message)
    return EngineUnavailableError()


class EngineClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self, company_id: str | None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        if company_id is not None:
            # server가 인증한 기업 ID만 보냄. 브라우저 입력을 쓰지 않음
            headers["X-Company-Id"] = company_id
        return headers

    async def request(
        self,
        method: str,
        path: str,
        company_id: str | None,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> EngineResponse:
        if not self.configured:
            logger.error("DIAGNOSIS_ENGINE_URL is not set")
            raise EngineUnavailableError
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url + INTERNAL_PREFIX,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                res = await client.request(
                    method,
                    path,
                    headers=self._headers(company_id),
                    json=json,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    files=files,
                    data=data,
                )
        except httpx.HTTPError as exc:
            logger.error("Diagnosis engine request failed %s %s: %r", method, path, exc)
            raise EngineUnavailableError from None
        if res.status_code >= 400:
            raise _to_app_error(res)
        try:
            body = res.json()
        except ValueError:
            logger.error("Diagnosis engine returned non-JSON for %s %s", method, path)
            raise EngineUnavailableError from None
        return EngineResponse(res.status_code, body)

    async def delete_company_data(self, company_id: str) -> None:
        """탈퇴 기업의 엔진 데이터 삭제 (멱등). 실패하면 AppError."""
        await self.request("DELETE", f"/companies/{company_id}/data", None)


def get_engine_client() -> EngineClient:
    settings = get_settings()
    return EngineClient(
        settings.diagnosis_engine_url,
        settings.engine_service_token.get_secret_value(),
        settings.diagnosis_engine_timeout_seconds,
    )


Engine = Annotated[EngineClient, Depends(get_engine_client)]
