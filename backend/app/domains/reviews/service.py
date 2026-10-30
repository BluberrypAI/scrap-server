import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.models import Company
from app.domains.reviews import intake as intake_rules
from app.domains.reviews.models import Review
from app.domains.reviews.schemas import MAX_FREE_TEXT, ReviewCreate


class EmptyInputError(Exception):
    pass


class TextTooLongError(Exception):
    pass


def _company_snapshot(company: Company) -> dict[str, Any]:
    """검토 기본값으로 쓸 기업 정보. 주소·연락처 등 식별 정보는 담지 않음."""
    return {
        "industry": company.industry,
        "main_waste_types": [
            {
                "category": w.category,
                "generation_cycle": w.generation_cycle.value,
                "expected_monthly_volume_kg": w.expected_monthly_volume_kg,
            }
            for w in company.waste_profiles
        ],
    }


def _default_title(free_text: str) -> str:
    return re.sub(r"\s+", " ", free_text)[:30]


async def create_review(db: AsyncSession, company: Company, data: ReviewCreate) -> Review:
    free_text = data.free_text.strip()
    if not free_text:
        raise EmptyInputError
    if len(free_text) > MAX_FREE_TEXT:
        raise TextTooLongError

    snapshot = _company_snapshot(company)
    intake = intake_rules.initial_intake(data.overrides, snapshot)
    review = Review(
        company_id=company.id,
        title=(data.title or "").strip() or _default_title(free_text),
        free_text=free_text,
        status=intake_rules.status_of(intake),
        company_profile_version=company.profile_version,
        company_snapshot=snapshot,
        intake=intake,
        intake_version=1,
        # DB 기본값(SQLite는 초 단위)이 아니라 여기서 넣어 같은 초에 만든 검토도 순서가 유지되게 함
        created_at=datetime.now(UTC),
    )
    db.add(review)
    await db.commit()
    return review


async def get_review(
    db: AsyncSession, company_id: uuid.UUID, review_id: uuid.UUID
) -> Review | None:
    """다른 기업의 검토는 없는 것으로 취급함 (존재 여부를 드러내지 않음)."""
    return await db.scalar(
        select(Review).where(Review.id == review_id, Review.company_id == company_id)
    )


async def list_reviews(
    db: AsyncSession,
    company_id: uuid.UUID,
    page_number: int,
    page_size: int,
    order: Literal["asc", "desc"],
) -> tuple[list[Review], int]:
    total = await db.scalar(
        select(func.count()).select_from(Review).where(Review.company_id == company_id)
    )
    created = Review.created_at.asc() if order == "asc" else Review.created_at.desc()
    rows = await db.scalars(
        select(Review)
        .where(Review.company_id == company_id)
        .order_by(created, Review.id)
        .offset((page_number - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total or 0


async def update_intake(db: AsyncSession, review: Review, answers: dict[str, Any]) -> bool:
    """답변을 반영함. 값이 바뀌면 intake_version을 올리고 True를 돌려줌."""
    updated = intake_rules.apply_answers(review.intake, answers)
    if updated is None:
        return False
    review.intake = updated
    review.intake_version += 1
    review.status = intake_rules.status_of(updated)
    await db.commit()
    return True


def review_ids_of_companies(company_ids: Select[tuple[uuid.UUID]]) -> Select[tuple[uuid.UUID]]:
    return select(Review.id).where(Review.company_id.in_(company_ids))


async def delete_reviews_of_companies(
    db: AsyncSession, company_ids: Select[tuple[uuid.UUID]]
) -> None:
    """탈퇴 사용자 삭제 시 검토를 지움. 커밋은 호출한 쪽에서 함."""
    await db.execute(
        delete(Review)
        .where(Review.company_id.in_(company_ids))
        .execution_options(synchronize_session=False)
    )
