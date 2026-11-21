"""Unauthenticated access to candidate-specific inquiries and reply submission."""

import logging
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import AppError, ErrorCode, ErrorResponse
from app.db.session import DbSession
from app.domains.transport import inquiry_replies, inquiry_reply_links
from app.domains.transport.models import WorkflowInquiryReplyLink
from app.domains.transport.schemas import (
    PublicInquiryRead,
    PublicInquiryReplyCreated,
    ReplyAvailability,
)

PREFIX = "/public/inquiry-replies"
API_PATH_PREFIX = "/api/v1" + PREFIX + "/"
PUBLIC_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}


class PublicInquiryAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # Uvicorn passes the request target as the third access log argument.
        if (
            isinstance(args, tuple)
            and len(args) == 5
            and isinstance(args[2], str)
            and args[2].startswith(API_PATH_PREFIX)
        ):
            record.args = (*args[:2], API_PATH_PREFIX + "{token}", *args[3:])
        return True


PUBLIC_INQUIRY_ACCESS_LOG_FILTER = PublicInquiryAccessLogFilter()


class PublicInquiryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except HTTPException as exc:
                if exc.status_code != 400:
                    raise
                raise AppError(
                    422, ErrorCode.VALIDATION_ERROR, "요청 본문을 읽을 수 없습니다."
                ) from None

        return handle


router = APIRouter(prefix=PREFIX, tags=["public-inquiry-replies"], route_class=PublicInquiryRoute)


class ProtectPublicInquiryReplies:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.window = -1
        self.counts: dict[tuple[str, str], int] = {}
        logging.getLogger("uvicorn.access").addFilter(PUBLIC_INQUIRY_ACCESS_LOG_FILTER)

    def allow(self, ip: str, token: str):
        window = int(monotonic() // 60)
        if window != self.window:
            self.window = window
            self.counts.clear()
        keys = [("ip", ip)]
        if inquiry_reply_links.TOKEN_PATTERN.fullmatch(token):
            keys.append(("token", inquiry_reply_links.token_hash(token)))
        if any(self.counts.get(key, 0) >= 10 for key in keys):
            return False
        # Bound the process memory even when requests present random tokens.
        if len(self.counts) + sum(key not in self.counts for key in keys) > 4096:
            return False
        for key in keys:
            self.counts[key] = self.counts.get(key, 0) + 1
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or not scope["path"].startswith(API_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        async def send_protected(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(PUBLIC_HEADERS)
            await send(message)

        if (
            scope["method"] in {"GET", "POST"}
            and scope["app"].state.inquiry_reply_rate_limit_enabled
            and not self.allow(
                scope["client"][0] if scope.get("client") else "",
                scope["path"].removeprefix(API_PATH_PREFIX),
            )
        ):
            error = ErrorResponse(
                code=ErrorCode.RATE_LIMITED,
                message="요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
            )
            response = JSONResponse(error.model_dump(mode="json"), status_code=429)
            await response(scope, receive, send_protected)
            return
        await self.app(scope, receive, send_protected)


async def get_active_link(token: str, db: DbSession):
    return await inquiry_reply_links.active_link(db, token)


ActiveLink = Annotated[WorkflowInquiryReplyLink, Depends(get_active_link)]


@router.get("/{token}", response_model=PublicInquiryRead)
async def get_inquiry(link: ActiveLink):
    return inquiry_reply_links.public_inquiry(link)


def optional_text(value: str | None):
    if value and "\x00" in value:
        raise AppError(422, ErrorCode.VALIDATION_ERROR, "입력에 사용할 수 없는 문자가 있습니다.")
    return (value or "").strip() or None


@router.post("/{token}", status_code=201, response_model=PublicInquiryReplyCreated)
async def submit_reply(
    token: str,
    link: ActiveLink,
    db: DbSession,
    availability: Annotated[ReplyAvailability, Form()],
    text: Annotated[str | None, Form(max_length=2000)] = None,
    contact_name: Annotated[str | None, Form(max_length=100)] = None,
    contact_info: Annotated[str | None, Form(max_length=200)] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    raw = name = mime = None
    if file is not None and file.filename:
        raw = await file.read(inquiry_replies.MAX_FILE_BYTES + 1)
        if len(raw) > inquiry_replies.MAX_FILE_BYTES:
            raise AppError(422, ErrorCode.VALIDATION_ERROR, "첨부파일은 10MB 이하로 올려 주세요.")
        try:
            name, mime = inquiry_replies.check_file(file.filename, raw)
        except ValueError as exc:
            raise AppError(422, ErrorCode.VALIDATION_ERROR, str(exc)) from None
    return await inquiry_reply_links.record_reply(
        db,
        token,
        link,
        availability=availability,
        text=optional_text(text),
        contact_name=optional_text(contact_name),
        contact_info=optional_text(contact_info),
        file_name=name,
        mime=mime,
        size=len(raw) if raw is not None else None,
        content=raw,
    )
