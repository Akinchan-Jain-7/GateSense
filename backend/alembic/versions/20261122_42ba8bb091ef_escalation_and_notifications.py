"""Escalation and notifications: rendered messages, retry time, reconciliation flags.

Revision ID: 42ba8bb091ef
Revises: 9b034f1429da
Create Date: 2026-11-22 00:05:00.435994+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "42ba8bb091ef"
down_revision: str | None = "9b034f1429da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_flags",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "exit_without_entry",
                "entry_never_closed",
                "visit_not_closed",
                name="reconciliation_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("gate_event_id", sa.Uuid(), nullable=True),
        sa.Column("visit_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            ["gate_event_id"],
            ["gate_events.id"],
            name=op.f("fk_reconciliation_flags_gate_event_id_gate_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_reconciliation_flags_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["society_id"],
            ["societies.id"],
            name=op.f("fk_reconciliation_flags_society_id_societies"),
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            name=op.f("fk_reconciliation_flags_visit_id_visits"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reconciliation_flags")),
        sa.UniqueConstraint("kind", "subject_id", name="one_flag_per_finding"),
    )
    op.create_index(
        op.f("ix_reconciliation_flags_society_id"),
        "reconciliation_flags",
        ["society_id"],
        unique=False,
    )
    op.drop_index(op.f("ix_escalation_tasks_visit_id"), table_name="escalation_tasks")
    op.create_unique_constraint(
        op.f("uq_escalation_tasks_visit_id"), "escalation_tasks", ["visit_id"]
    )
    op.add_column("notifications", sa.Column("subject", sa.String(length=255), nullable=True))
    op.add_column("notifications", sa.Column("body_text", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("body_html", sa.Text(), nullable=True))
    op.add_column(
        "notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_notifications_next_attempt_at"), "notifications", ["next_attempt_at"], unique=False
    )
    op.add_column(
        "society_settings",
        sa.Column("visitor_retention_days", sa.Integer(), server_default="90", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("society_settings", "visitor_retention_days")
    op.drop_index(op.f("ix_notifications_next_attempt_at"), table_name="notifications")
    op.drop_column("notifications", "next_attempt_at")
    op.drop_column("notifications", "body_html")
    op.drop_column("notifications", "body_text")
    op.drop_column("notifications", "subject")
    op.drop_constraint(op.f("uq_escalation_tasks_visit_id"), "escalation_tasks", type_="unique")
    op.create_index(
        op.f("ix_escalation_tasks_visit_id"), "escalation_tasks", ["visit_id"], unique=False
    )
    op.drop_index(op.f("ix_reconciliation_flags_society_id"), table_name="reconciliation_flags")
    op.drop_table("reconciliation_flags")
