"""drop generation_cycle from main_waste_types

온보딩에서 발생 주기를 받지 않기로 해서 companies.main_waste_types JSON 항목의
generation_cycle 키를 지움. 컬럼 구조는 그대로임.

Revision ID: a7c3e91f5b28
Revises: e6a4b2d90f35
Create Date: 2026-11-10 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91f5b28"
down_revision: str | None = "e6a4b2d90f35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

companies = sa.table(
    "companies",
    sa.column("id", sa.Uuid()),
    sa.column("main_waste_types", sa.JSON()),
)


def _rewrite(transform) -> None:
    conn = op.get_bind()
    for row in conn.execute(sa.select(companies.c.id, companies.c.main_waste_types)).all():
        items = row.main_waste_types or []
        new_items = [transform(dict(item)) for item in items]
        if new_items != items:
            conn.execute(
                companies.update()
                .where(companies.c.id == row.id)
                .values(main_waste_types=new_items)
            )


def upgrade() -> None:
    def drop_cycle(item: dict) -> dict:
        item.pop("generation_cycle", None)
        return item

    _rewrite(drop_cycle)


def downgrade() -> None:
    # 원래 값은 남아 있지 않으므로 이전 스키마가 받는 값 중 'irregular'로 채움
    def add_cycle(item: dict) -> dict:
        item.setdefault("generation_cycle", "irregular")
        return item

    _rewrite(add_cycle)
