"""Visitors, approvals and real time: society settings, Telegram link, visit duration.

Revision ID: 9b034f1429da
Revises: b6371bdaf779
Create Date: 2026-11-21 23:36:26.250625+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b034f1429da"
down_revision: str | None = "b6371bdaf779"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "society_settings",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("guest_minutes", sa.Integer(), nullable=False),
        sa.Column("delivery_minutes", sa.Integer(), nullable=False),
        sa.Column("cab_minutes", sa.Integer(), nullable=False),
        sa.Column("service_minutes", sa.Integer(), nullable=False),
        sa.Column("approval_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_society_settings_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("society_id", name=op.f("pk_society_settings")),
    )
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(op.f("uq_users_telegram_chat_id"), "users", ["telegram_chat_id"])
    op.add_column("visits", sa.Column("duration_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("visits", "duration_minutes")
    op.drop_constraint(op.f("uq_users_telegram_chat_id"), "users", type_="unique")
    op.drop_column("users", "telegram_chat_id")
    op.drop_table("society_settings")
