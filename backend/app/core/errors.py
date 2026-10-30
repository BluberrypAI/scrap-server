"""
공통 에러 응답 형식 (docs/specs/error-response.md)
HTTPException 대신 에러 code를 붙인 AppError 계열 사용
"""

import logging
from enum import StrEnum

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ACCOUNT_WITHDRAWN = "ACCOUNT_WITHDRAWN"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    COMPANY_ALREADY_EXISTS = "COMPANY_ALREADY_EXISTS"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    COMPANY_REQUIRED = "COMPANY_REQUIRED"
    EMPTY_INPUT = "EMPTY_INPUT"
    TEXT_TOO_LONG = "TEXT_TOO_LONG"
    FILE_TYPE_UNSUPPORTED = "FILE_TYPE_UNSUPPORTED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNIT_REQUIRED = "UNIT_REQUIRED"
    INTAKE_INCOMPLETE = "INTAKE_INCOMPLETE"
    RUN_IN_PROGRESS = "RUN_IN_PROGRESS"
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    RESULT_NOT_READY = "RESULT_NOT_READY"
    INVALID_FILTER = "INVALID_FILTER"
    DIFFERENT_REVIEW = "DIFFERENT_REVIEW"
    STEP_OUT_OF_ORDER = "STEP_OUT_OF_ORDER"
    RISK_OPTION_REQUIRED = "RISK_OPTION_REQUIRED"
    EVIDENCE_NOT_APPLICABLE = "EVIDENCE_NOT_APPLICABLE"
    MISSING_QUANTITY = "MISSING_QUANTITY"
    NO_APPLICABLE_SUPPLEMENT = "NO_APPLICABLE_SUPPLEMENT"


class ErrorDetail(BaseModel):
    field: str
    message: str


# 에러 응답 모델
class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    details: list[ErrorDetail] | None = None


# 공통 AppError 기반 에러 클래스
class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


class AuthRequiredError(AppError):
    def __init__(self, message: str = "로그인이 필요함"):
        super().__init__(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.AUTH_REQUIRED,
            message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class NotFoundError(AppError):
    def __init__(self, message: str = "대상을 찾을 수 없음"):
        super().__init__(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, message)


class ConflictError(AppError):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(status.HTTP_409_CONFLICT, code, message)


# 형식은 맞지만 업무 규칙에 어긋나는 입력 (422, VALIDATION_ERROR보다 구체적인 코드)
class UnprocessableError(AppError):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def _response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, details=details)
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    return _response(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        ErrorDetail(field=".".join(str(part) for part in err["loc"]), message=err["msg"])
        for err in exc.errors()
    ]
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_ERROR,
        "요청 값이 올바르지 않음",
        details,
    )


_HTTP_CODES = {
    status.HTTP_401_UNAUTHORIZED: (ErrorCode.AUTH_REQUIRED, "로그인이 필요함"),
    status.HTTP_404_NOT_FOUND: (ErrorCode.NOT_FOUND, "대상을 찾을 수 없음"),
    status.HTTP_405_METHOD_NOT_ALLOWED: (ErrorCode.METHOD_NOT_ALLOWED, "허용되지 않은 메서드"),
}


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Errors raised by the framework itself (unknown route, wrong method)."""
    code, message = _HTTP_CODES.get(exc.status_code, (ErrorCode.INTERNAL_ERROR, "요청 처리 실패"))
    return _response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_ERROR, "서버 오류가 발생함"
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error)
