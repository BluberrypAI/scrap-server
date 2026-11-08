"""align companies with onboarding screen

온보딩 화면에 맞춰 기업·사업장 컬럼을 정리하고 waste_profiles를 companies.main_waste_types
JSON으로 합침 (db-schema-simplify).

- 추가: site_name, site_address, site_facilities, main_products, main_waste_types
- contact_email은 필수로 바꿈
- owner_user_id → user_id
- 삭제: business_registration_no, representative_name, head_office_address, contact_name,
  contact_phone, waste_profiles 테이블

기존 행의 새 필수값은 사업장 이름 = 회사명, 사업장 주소 = 본사 주소, 담당자 이메일 = 기존
담당자 이메일 → 사용자 이메일 → 빈 문자열, 배출시설·주생산품 = 빈 배열로 채움.
downgrade는 지운 컬럼을 빈 문자열(본사 주소는 사업장 주소)로 다시 만듦.

Revision ID: 8d3f6a92c1e7
Revises: 5b1e0c7d2a41
Create Date: 2026-11-09 03:00:00.000000
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d3f6a92c1e7"
down_revision: str | None = "5b1e0c7d2a41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENERATION_CYCLE = sa.Enum(
    "daily", "weekly", "monthly", "irregular", name="generationcycle", native_enum=False, length=20
)

users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("email", sa.String()))
companies = sa.table(
    "companies",
    sa.column("id", sa.Uuid()),
    sa.column("owner_user_id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("company_name", sa.String()),
    sa.column("head_office_address", sa.String()),
    sa.column("contact_email", sa.String()),
    sa.column("site_name", sa.String()),
    sa.column("site_address", sa.String()),
    sa.column("site_facilities", sa.JSON()),
    sa.column("main_products", sa.JSON()),
    sa.column("main_waste_types", sa.JSON()),
)
waste_profiles = sa.table(
    "waste_profiles",
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
    sa.column("category", sa.String()),
    sa.column("generation_cycle", sa.String()),
    sa.column("expected_monthly_volume_kg", sa.Float()),
)


def upgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("site_name", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("site_address", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("site_facilities", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("main_products", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("main_waste_types", sa.JSON(), nullable=True))

    waste_types: dict[uuid.UUID, list[dict]] = defaultdict(list)
    rows = conn.execute(sa.select(waste_profiles).order_by(waste_profiles.c.company_id)).mappings()
    for row in rows:
        waste_types[row["company_id"]].append(
            {
                "id": str(row["id"]),
                "category": row["category"],
                "generation_cycle": row["generation_cycle"],
                "expected_monthly_volume_kg": row["expected_monthly_volume_kg"],
            }
        )

    user_email = (
        sa.select(users.c.email).where(users.c.id == companies.c.owner_user_id).scalar_subquery()
    )
    for company in conn.execute(sa.select(companies.c.id)).all():
        conn.execute(
            companies.update()
            .where(companies.c.id == company.id)
            .values(
                site_name=companies.c.company_name,
                site_address=companies.c.head_office_address,
                contact_email=sa.func.coalesce(companies.c.contact_email, user_email, ""),
                site_facilities=[],
                main_products=[],
                main_waste_types=waste_types.get(company.id, []),
            )
        )

    with op.batch_alter_table("companies") as batch:
        batch.drop_constraint("uq_companies_owner_user_id", type_="unique")
        batch.drop_constraint("fk_companies_owner_user_id_users", type_="foreignkey")
        batch.alter_column("owner_user_id", new_column_name="user_id")
        for name in ("site_name", "site_address", "contact_email"):
            batch.alter_column(name, nullable=False)
        for name in ("site_facilities", "main_products", "main_waste_types"):
            batch.alter_column(name, existing_type=sa.JSON(), nullable=False)
        for name in (
            "business_registration_no",
            "representative_name",
            "head_office_address",
            "contact_name",
            "contact_phone",
        ):
            batch.drop_column(name)

    with op.batch_alter_table("companies") as batch:
        batch.create_unique_constraint(batch.f("uq_companies_user_id"), ["user_id"])
        batch.create_foreign_key(
            batch.f("fk_companies_user_id_users"),
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_index(op.f("ix_waste_profiles_company_id"), table_name="waste_profiles")
    op.drop_table("waste_profiles")


def downgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "waste_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("generation_cycle", GENERATION_CYCLE, nullable=False),
        sa.Column("expected_monthly_volume_kg", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_waste_profiles_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waste_profiles")),
    )
    op.create_index(
        op.f("ix_waste_profiles_company_id"), "waste_profiles", ["company_id"], unique=False
    )
    profiles = [
        {
            "id": uuid.UUID(item["id"]),
            "company_id": row.id,
            "category": item["category"],
            "generation_cycle": item["generation_cycle"],
            "expected_monthly_volume_kg": item.get("expected_monthly_volume_kg"),
        }
        for row in conn.execute(sa.select(companies.c.id, companies.c.main_waste_types))
        for item in row.main_waste_types or []
    ]
    if profiles:
        op.bulk_insert(waste_profiles, profiles)

    with op.batch_alter_table("companies") as batch:
        batch.add_column(
            sa.Column(
                "business_registration_no", sa.String(length=10), server_default="", nullable=False
            )
        )
        batch.add_column(
            sa.Column(
                "representative_name", sa.String(length=100), server_default="", nullable=False
            )
        )
        batch.add_column(sa.Column("head_office_address", sa.String(length=500), nullable=True))
        batch.add_column(
            sa.Column("contact_name", sa.String(length=100), server_default="", nullable=False)
        )
        batch.add_column(sa.Column("contact_phone", sa.String(length=50), nullable=True))

    conn.execute(companies.update().values(head_office_address=companies.c.site_address))

    with op.batch_alter_table("companies") as batch:
        batch.alter_column(
            "head_office_address", existing_type=sa.String(length=500), nullable=False
        )
        for name in ("business_registration_no", "representative_name", "contact_name"):
            batch.alter_column(name, server_default=None)
        batch.alter_column("contact_email", existing_type=sa.String(length=320), nullable=True)
        batch.drop_constraint("uq_companies_user_id", type_="unique")
        batch.drop_constraint("fk_companies_user_id_users", type_="foreignkey")
        batch.alter_column("user_id", new_column_name="owner_user_id")
        for name in (
            "main_waste_types",
            "main_products",
            "site_facilities",
            "site_address",
            "site_name",
        ):
            batch.drop_column(name)

    with op.batch_alter_table("companies") as batch:
        batch.create_unique_constraint(batch.f("uq_companies_owner_user_id"), ["owner_user_id"])
        batch.create_foreign_key(
            batch.f("fk_companies_owner_user_id_users"),
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
