"""merge social accounts into users

사용자당 로그인 수단은 하나이므로 social_accounts의 provider, provider_subject를 users로 옮기고
social_accounts를 지움 (db-schema-simplify).

Revision ID: 5b1e0c7d2a41
Revises: c42145780ae9
Create Date: 2026-11-09 02:00:00.000000
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b1e0c7d2a41"
down_revision: str | None = "c42145780ae9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

users = sa.table(
    "users",
    sa.column("id", sa.Uuid()),
    sa.column("email", sa.String()),
    sa.column("provider", sa.String()),
    sa.column("provider_subject", sa.String()),
)
social_accounts = sa.table(
    "social_accounts",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("provider", sa.String()),
    sa.column("provider_subject", sa.String()),
    sa.column("email", sa.String()),
)


def upgrade() -> None:
    conn = op.get_bind()
    # 계정을 하나로 고를 수 없으면 데이터를 지우지 않고 멈춤
    multi = conn.execute(
        sa.select(social_accounts.c.user_id)
        .group_by(social_accounts.c.user_id)
        .having(sa.func.count() > 1)
    ).first()
    if multi:
        raise RuntimeError(f"user {multi.user_id} has more than one social account")

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("provider", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("provider_subject", sa.String(length=255), nullable=True))

    for column in ("provider", "provider_subject"):
        conn.execute(
            users.update().values(
                {
                    column: sa.select(social_accounts.c[column])
                    .where(social_accounts.c.user_id == users.c.id)
                    .scalar_subquery()
                }
            )
        )
    orphan = conn.execute(sa.select(users.c.id).where(users.c.provider.is_(None))).first()
    if orphan:
        raise RuntimeError(f"user {orphan.id} has no social account")

    with op.batch_alter_table("users") as batch:
        batch.alter_column("provider", existing_type=sa.String(length=20), nullable=False)
        batch.alter_column("provider_subject", existing_type=sa.String(length=255), nullable=False)
        batch.create_unique_constraint(
            batch.f("uq_users_provider"), ["provider", "provider_subject"]
        )

    op.drop_index(op.f("ix_social_accounts_user_id"), table_name="social_accounts")
    op.drop_table("social_accounts")


def downgrade() -> None:
    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_social_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_accounts")),
        sa.UniqueConstraint(
            "provider", "provider_subject", name=op.f("uq_social_accounts_provider")
        ),
    )
    op.create_index(
        op.f("ix_social_accounts_user_id"), "social_accounts", ["user_id"], unique=False
    )
    rows = op.get_bind().execute(
        sa.select(users.c.id, users.c.provider, users.c.provider_subject, users.c.email)
    )
    op.bulk_insert(
        social_accounts,
        [
            {
                "id": uuid.uuid4(),
                "user_id": row.id,
                "provider": row.provider,
                "provider_subject": row.provider_subject,
                "email": row.email,
            }
            for row in rows
        ],
    )
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint(batch.f("uq_users_provider"), type_="unique")
        batch.drop_column("provider_subject")
        batch.drop_column("provider")
