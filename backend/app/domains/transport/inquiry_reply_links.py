"""Persistence and lifecycle rules for the public vendor reply link."""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.errors import AppError, ErrorCode, NotFoundError
from app.domains.transport.inquiry import review_candidates
from app.domains.transport.models import (
    WorkflowInquiryReply,
    WorkflowInquiryReplyLink,
    WorkflowLot,
)
from app.domains.transport.schemas import (
    InquiryReplyLinkStatus,
    IssuedInquiryReplyLink,
    PublicInquiry,
    PublicInquiryRead,
    PublicInquiryReplyCreated,
)

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


def _inquiry_link_for(lot, capability_key):
    return (
        WorkflowInquiryReplyLink.lot_id == lot.id,
        WorkflowInquiryReplyLink.capability_key == capability_key,
        WorkflowInquiryReplyLink.company_id == lot.current_company_id,
    )


async def issue_link(db, lot, capability_key, inquiry: PublicInquiry):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=14)
    values = {
        "company_id": lot.current_company_id,
        "stage": len(lot.data["completed"]),
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


async def link_status(db, lot, capability_key):
    link = await db.scalar(
        select(WorkflowInquiryReplyLink).where(*_inquiry_link_for(lot, capability_key))
    )
    if link is None:
        return InquiryReplyLinkStatus(status="none", expires_at=None)
    expires_at = _expires_at(link)
    if link.revoked_at or not _eligible(link, lot):
        return InquiryReplyLinkStatus(status="revoked", expires_at=expires_at)
    if expires_at <= datetime.now(UTC):
        return InquiryReplyLinkStatus(status="expired", expires_at=expires_at)
    return InquiryReplyLinkStatus(status="active", expires_at=expires_at)


async def revoke_link(db, lot, capability_key):
    await db.execute(
        update(WorkflowInquiryReplyLink)
        .where(
            *_inquiry_link_for(lot, capability_key),
            WorkflowInquiryReplyLink.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def active_link(db, token: str):
    if not TOKEN_PATTERN.fullmatch(token):
        raise _not_found()
    result = await db.execute(
        select(WorkflowInquiryReplyLink, WorkflowLot)
        .join(WorkflowLot, WorkflowLot.id == WorkflowInquiryReplyLink.lot_id)
        .where(WorkflowInquiryReplyLink.token_hash == token_hash(token))
        .execution_options(populate_existing=True)
    )
    row = result.one_or_none()
    if row is None:
        raise _not_found()
    link, lot = row
    if link.revoked_at or _expires_at(link) <= datetime.now(UTC) or not _eligible(link, lot):
        raise _not_found()
    return link


def public_inquiry(link):
    snapshot = {"summary": None, **link.inquiry}
    return PublicInquiryRead(**snapshot, expires_at=_expires_at(link), reply_count=link.reply_count)


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
