"""rename facility listings to import rows

공공데이터에서 가져온 시설 원본 행이라는 뜻이 드러나게 treatment_facility_listings를
facility_import_rows로 바꿈. 데이터는 유지함 (db-schema-simplify).

Revision ID: e6a4b2d90f35
Revises: 8d3f6a92c1e7
Create Date: 2026-11-09 04:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6a4b2d90f35"
down_revision: str | None = "8d3f6a92c1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(old: str, new: str) -> None:
    op.rename_table(old, new)
    with op.batch_alter_table(new) as batch:
        batch.drop_constraint(f"uq_{old}_source_row", type_="unique")
        batch.create_unique_constraint(f"uq_{new}_source_row", ["source_row"])
    op.drop_index(f"ix_{old}_is_treatment", table_name=new)
    op.create_index(f"ix_{new}_is_treatment", new, ["is_treatment"], unique=False)
    # SQLite는 PK 이름을 따로 보관하지 않으므로 PostgreSQL에서만 바꿈
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {new} RENAME CONSTRAINT pk_{old} TO pk_{new}")


def upgrade() -> None:
    _rename("treatment_facility_listings", "facility_import_rows")


def downgrade() -> None:
    _rename("facility_import_rows", "treatment_facility_listings")
