import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import LocalFileStorage
from app.domains.documents import service as document_service
from app.domains.documents.models import VerificationStatus
from app.domains.reviews import intake as intake_rules
from app.domains.reviews.models import Review
from app.domains.supplements.models import Applicability, Supplement, SupplementType

QUANTITY_UNITS = {"kg": 1.0, "t": 1000.0}


def applicability_of(review: Review, quantity_kg: float) -> tuple[Applicability, str | None]:
    """적용 물량이 검토에서 확인된 물량과 같으면 matched. 다르면 mismatch와 이유."""
    confirmed = intake_rules.confirmed_values(review.intake).get("quantity_kg")
    if confirmed is None:
        return Applicability.MISMATCH, "검토 물량이 확인되지 않아 비교할 수 없음"
    if not math.isclose(confirmed, quantity_kg, rel_tol=1e-9):
        return (
            Applicability.MISMATCH,
            f"적용 물량 {quantity_kg:g} kg가 검토 물량 {confirmed:g} kg와 다름",
        )
    return Applicability.MATCHED, None


async def create(
    db: AsyncSession,
    storage: LocalFileStorage,
    review: Review,
    type_: SupplementType,
    quantity_kg: float,
    effective_date: date,
    verification_status: VerificationStatus,
    value: float | None,
    file: tuple[str, bytes] | None,
) -> Supplement:
    applicability, reason = applicability_of(review, quantity_kg)
    supplement = Supplement(
        id=uuid.uuid4(),
        review_id=review.id,
        type=type_,
        value=value,
        applied_quantity_kg=quantity_kg,
        effective_date=effective_date,
        verification_status=verification_status,
        applicability=applicability,
        mismatch_reason=reason,
        created_at=datetime.now(UTC),
    )
    if file is not None:
        file_name, data = file
        fmt = document_service.file_format(file_name)
        supplement.file_name = file_name[:255]
        supplement.storage_key = (
            f"{review.company_id}/{review.id}/supplements/{supplement.id}.{fmt}"
        )
        storage.save(supplement.storage_key, data)
    db.add(supplement)
    await db.commit()
    return supplement


def counted_in_judgment(supplement: Supplement) -> bool:
    """판정·증빙에 쓸 수 있는 자료: 물량이 맞고 사람이 검수함."""
    return (
        supplement.applicability == Applicability.MATCHED
        and supplement.verification_status == VerificationStatus.VERIFIED
    )


async def get(
    db: AsyncSession, review_id: uuid.UUID, supplement_id: uuid.UUID
) -> Supplement | None:
    return await db.scalar(
        select(Supplement).where(Supplement.id == supplement_id, Supplement.review_id == review_id)
    )


async def get_many(
    db: AsyncSession, review_id: uuid.UUID, supplement_ids: Sequence[uuid.UUID]
) -> list[Supplement]:
    if not supplement_ids:
        return []
    return list(
        await db.scalars(
            select(Supplement).where(
                Supplement.id.in_(supplement_ids), Supplement.review_id == review_id
            )
        )
    )


async def list_page(
    db: AsyncSession, review_id: uuid.UUID, page_number: int, page_size: int
) -> tuple[list[Supplement], int]:
    where = Supplement.review_id == review_id
    total = await db.scalar(select(func.count()).select_from(Supplement).where(where))
    rows = await db.scalars(
        select(Supplement)
        .where(where)
        .order_by(Supplement.created_at, Supplement.id)
        .offset((page_number - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total or 0


async def delete_supplements_of_reviews(
    db: AsyncSession, storage: LocalFileStorage, review_ids: Select[tuple[uuid.UUID]]
) -> None:
    """탈퇴 사용자 삭제 시 추가 자료와 파일을 지움. 커밋은 호출한 쪽에서 함."""
    rows = list(await db.scalars(select(Supplement).where(Supplement.review_id.in_(review_ids))))
    if not rows:
        return
    await db.execute(
        delete(Supplement)
        .where(Supplement.id.in_([s.id for s in rows]))
        .execution_options(synchronize_session=False)
    )
    for supplement in rows:
        if supplement.storage_key:
            storage.delete(supplement.storage_key)
