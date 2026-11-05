from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import UUID4

from app.db.session import DbSession
from app.domains.auth.cookies import ACCESS_COOKIE
from app.domains.auth.dependencies import CurrentUser, get_current_user
from app.domains.transport import service, shared
from app.domains.transport.models import TransportSharedCase
from app.domains.transport.schemas import (
    SharedCaseUpdate,
    TransportCreate,
    TransportEvent,
    TransportRead,
)

router = APIRouter(prefix="/transport", tags=["transport"])


@router.get("/inbox")
async def inbox(user: CurrentUser, db: DbSession, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await shared.inbox(db, user.id)


@router.get("/cases/{key}")
async def case(key: UUID4, user: CurrentUser, db: DbSession, response: Response):
    response.headers["Cache-Control"] = "no-store"
    value = await db.get(TransportSharedCase, key)
    result = await shared.case_view(db, value, user.id) if value else None
    if not result:
        raise HTTPException(404, "공유된 처리 기록을 찾을 수 없습니다.")
    return result


@router.patch("/cases/{key}")
async def update_case(key: UUID4, data: SharedCaseUpdate, user: CurrentUser, db: DbSession):
    result = await shared.update_case(db, key, user.id, data)
    if not result:
        raise HTTPException(409, "현재 처리업체나 최신 기록을 다시 확인해 주세요.")
    return result


@router.put("/{key}", response_model=TransportRead)
async def register(key: UUID4, data: TransportCreate, user: CurrentUser, db: DbSession):
    value = await service.register(db, key, user.id, data)
    if value is None:
        raise HTTPException(409, "이미 등록된 인계 구간입니다.")
    return value


@router.get("/{key}", response_model=TransportRead)
async def read(key: UUID4, db: DbSession, response: Response):
    response.headers["Cache-Control"] = "no-store"
    value = await service.read(db, key)
    if value is None:
        raise HTTPException(404, "유효한 인계 구간을 찾을 수 없습니다.")
    return value


@router.post("/{key}/events", response_model=TransportRead)
async def record(
    key: UUID4, data: TransportEvent, db: DbSession, response: Response, request: Request
):
    response.headers["Cache-Control"] = "no-store"
    handoff = await service.read(db, key)
    if handoff and handoff.account_required and data.role == "recipient":
        user = await get_current_user(
            db, credentials=None, access_cookie=request.cookies.get(ACCESS_COOKIE)
        )
        if user.id != handoff.recipient_id:
            raise HTTPException(403, "이 인계에 지정된 업체 계정으로 확인해 주세요.")
    value = await service.record_event(db, key, data)
    if value is None:
        raise HTTPException(404, "유효한 인계 구간을 찾을 수 없습니다.")
    return value
