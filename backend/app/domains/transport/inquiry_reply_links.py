"""Persistence and lifecycle rules for the public vendor reply link."""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.errors import AppError, ConflictError, ErrorCode, NotFoundError
from app.domains.auth import service as auth_service
from app.domains.companies.models import Company
from app.domains.transport.inquiry import review_candidates
from app.domains.transport.models import (
    WorkflowFacilityAccount,
    WorkflowInquiryReply,
    WorkflowInquiryReplyLink,
    WorkflowLot,
    WorkflowOffer,
)
from app.domains.transport.schemas import (
    InquiryReplyLinkStatus,
    IssuedInquiryReplyLink,
    PublicInquiry,
    PublicInquiryJoin,
    PublicInquiryRead,
    PublicInquiryReplyCreated,
)
from app.domains.users.models import REPLY_LINK_PROVIDER, User

MAX_LINK_REPLIES = 10
REPLYABLE_STATES = {"ready", "processed"}
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def candidate_in_review(lot, capability_key):
    return (
        capability_key in (lot.review or {}).get("results", {})
        and len(review_candidates(lot, capability_key)) == 1
    )


def _eligible(link, lot):
    return (
        lot.current_company_id == link.company_id
        and lot.status in REPLYABLE_STATES
        and len(lot.data["completed"]) == link.stage
        and candidate_in_review(lot, link.capability_key)
    )


def _expires_at(link):
    # SQLite does not preserve the timezone on datetime columns.
    expires_at = link.expires_at
    return expires_at.astimezone(UTC) if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)


def _not_found():
    return NotFoundError("답장 링크를 찾을 수 없습니다.")


def _inquiry_link_for(lot, capability_key, issuer_id):
    return (
        WorkflowInquiryReplyLink.lot_id == lot.id,
        WorkflowInquiryReplyLink.capability_key == capability_key,
        WorkflowInquiryReplyLink.company_id == issuer_id,
    )


async def issue_link(db, lot, capability_key, inquiry: PublicInquiry, *, previous=None):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=14)
    values = {
        "company_id": previous.company_id if previous else lot.current_company_id,
        "stage": previous.stage if previous else len(lot.data["completed"]),
        "token_hash": token_hash(token),
        "expires_at": expires_at,
        "revoked_at": None,
        "reply_count": 0,
        "inquiry": inquiry.model_dump(),
    }
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    stmt = insert(WorkflowInquiryReplyLink).values(
        lot_id=lot.id, capability_key=capability_key, **values
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["lot_id", "capability_key"],
            set_={**values, "updated_at": datetime.now(UTC)},
        )
    )
    await db.commit()
    return IssuedInquiryReplyLink(token=token, path=f"/#/reply/{token}", expires_at=expires_at)


async def issued_link(db, lot, capability_key, issuer_id):
    return await db.scalar(
        select(WorkflowInquiryReplyLink).where(*_inquiry_link_for(lot, capability_key, issuer_id))
    )


async def guest_offer(db, link):
    if link is None or link.guest_company_id is None:
        return None
    return await db.scalar(
        select(WorkflowOffer)
        .where(
            WorkflowOffer.lot_id == link.lot_id,
            WorkflowOffer.sender_id == link.company_id,
            WorkflowOffer.recipient_id == link.guest_company_id,
        )
        .order_by(WorkflowOffer.created_at.desc())
        .limit(1)
    )


def link_status(lot, link, sent_offer):
    if link is None:
        return InquiryReplyLinkStatus(status="none", expires_at=None)
    expires_at = _expires_at(link)
    if link.revoked_at or not (_eligible(link, lot) or sent_offer):
        return InquiryReplyLinkStatus(status="revoked", expires_at=expires_at)
    if expires_at <= datetime.now(UTC):
        return InquiryReplyLinkStatus(status="expired", expires_at=expires_at)
    return InquiryReplyLinkStatus(status="active", expires_at=expires_at)


async def revoke_link(db, link):
    if link is not None:
        guest_company_id = await db.scalar(
            update(WorkflowInquiryReplyLink)
            .where(
                WorkflowInquiryReplyLink.id == link.id,
                WorkflowInquiryReplyLink.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
            .returning(WorkflowInquiryReplyLink.guest_company_id)
        )
        if guest_company_id is not None:
            user_id = await db.scalar(select(Company.user_id).where(Company.id == guest_company_id))
            await auth_service.lock_guest_sessions(db, user_id)
            # An old cookie from a stopped link must not revoke a new session after reissue.
            await auth_service.delete_sessions_of_users(db, [user_id])
    await db.commit()


def _valid_token_hash(token):
    if not TOKEN_PATTERN.fullmatch(token):
        raise _not_found()
    return token_hash(token)


async def _active_context(db, token: str, *, participation=False):
    result = await db.execute(
        select(WorkflowInquiryReplyLink, WorkflowLot)
        .join(WorkflowLot, WorkflowLot.id == WorkflowInquiryReplyLink.lot_id)
        .where(WorkflowInquiryReplyLink.token_hash == _valid_token_hash(token))
        .execution_options(populate_existing=True)
    )
    row = result.one_or_none()
    if row is None:
        raise _not_found()
    link, lot = row
    if link.revoked_at or _expires_at(link) <= datetime.now(UTC):
        raise _not_found()
    offer = await guest_offer(db, link) if participation else None
    if _eligible(link, lot):
        option, facility = review_candidates(lot, link.capability_key)[0]
    elif offer is not None:
        option, facility = offer.data["option"], offer.data["facility"]
    else:
        raise _not_found()
    return link, option, facility, offer is not None


async def active_link(db, token: str):
    link, _, _, _ = await _active_context(db, token)
    return link


def inquiry_snapshot(link):
    return PublicInquiry.model_validate({"summary": None, **link.inquiry})


async def public_inquiry(db, token):
    link, _, facility, _ = await _active_context(db, token, participation=True)
    return PublicInquiryRead(
        **inquiry_snapshot(link).model_dump(),
        expires_at=_expires_at(link),
        reply_count=link.reply_count,
        joinable=await db.get(WorkflowFacilityAccount, facility["facility_key"]) is None,
        joined=link.guest_company_id is not None,
    )


async def join(db, token):
    digest = _valid_token_hash(token)
    # Take the same lot lock as offer and reply creation. The conditional write also takes
    # SQLite's write lock before reading or creating the guest, including on the first join.
    lot_id = await db.scalar(
        select(WorkflowLot.id)
        .join(WorkflowInquiryReplyLink, WorkflowInquiryReplyLink.lot_id == WorkflowLot.id)
        .where(WorkflowInquiryReplyLink.token_hash == digest)
        .with_for_update(of=WorkflowLot)
    )
    if lot_id is None:
        raise _not_found()
    await db.execute(
        update(WorkflowInquiryReplyLink)
        .where(WorkflowInquiryReplyLink.token_hash == digest)
        .values(token_hash=digest, updated_at=WorkflowInquiryReplyLink.updated_at)
        .execution_options(synchronize_session=False)
    )
    link, option, facility, lot_visible = await _active_context(db, token, participation=True)
    if await db.get(WorkflowFacilityAccount, facility["facility_key"]) is not None:
        raise ConflictError(
            ErrorCode.ALREADY_CONNECTED, "이미 연결된 업체입니다. 연결된 계정으로 로그인해 주세요."
        )
    if link.guest_company_id is None:
        company = await _create_guest_company(db, link, option, facility)
    else:
        company = await db.get(Company, link.guest_company_id)
    refresh_token = await auth_service.start_session(db, company.user_id)
    joined = PublicInquiryJoin(company_name=company.company_name, lot_visible=lot_visible)
    return company.user_id, refresh_token, joined


async def _create_guest_company(db, link, option, facility):
    label = facility["label"]
    user = User(provider=REPLY_LINK_PROVIDER, provider_subject=str(link.id), name=label[:200])
    db.add(user)
    await db.flush()
    suffix = " (링크 참여)"
    location = facility.get("location") or {}
    company = Company(
        user_id=user.id,
        company_name=label[: 200 - len(suffix)] + suffix,
        guest=True,
        contact_email="",
        industry="폐기물 재활용업",
        site_name=label[:200],
        site_address=(facility.get("address") or "")[:500],
        site_latitude=location.get("latitude"),
        site_longitude=location.get("longitude"),
        site_facilities=[option["label"][:100]],
        main_waste_types=[],
    )
    db.add(company)
    await db.flush()
    link.guest_company_id = company.id
    return company


async def record_reply(db, token, link, **fields):
    # Serialize with workflow changes on PostgreSQL. The conditional counter write also
    # takes SQLite's write lock, so the second eligibility check sees the current state.
    await db.scalar(select(WorkflowLot.id).where(WorkflowLot.id == link.lot_id).with_for_update())
    now = datetime.now(UTC)
    claimed = await db.scalar(
        update(WorkflowInquiryReplyLink)
        .where(
            WorkflowInquiryReplyLink.token_hash == token_hash(token),
            WorkflowInquiryReplyLink.revoked_at.is_(None),
            WorkflowInquiryReplyLink.expires_at > now,
            WorkflowInquiryReplyLink.reply_count < MAX_LINK_REPLIES,
        )
        .values(reply_count=WorkflowInquiryReplyLink.reply_count + 1)
        .returning(WorkflowInquiryReplyLink.id)
        .execution_options(synchronize_session=False)
    )
    link = await active_link(db, token)
    if claimed is None:
        raise AppError(429, ErrorCode.RATE_LIMITED, "이 링크에는 답장이 10건 등록되었습니다.")
    reply = WorkflowInquiryReply(
        lot_id=link.lot_id,
        company_id=link.company_id,
        capability_key=link.capability_key,
        source="vendor_link",
        created_at=now,
        **fields,
    )
    db.add(reply)
    await db.commit()
    return PublicInquiryReplyCreated(id=reply.id, created_at=now)
