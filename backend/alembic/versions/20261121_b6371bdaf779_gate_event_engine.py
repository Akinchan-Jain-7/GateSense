"""Gate event engine: alerts, visit status history, review and pairing columns.

Revision ID: b6371bdaf779
Revises: d5af2f014473
Create Date: 2026-11-21 14:56:15.719434+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6371bdaf779"
down_revision: str | None = "d5af2f014473"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "watchlist", name="alert_kind", native_enum=False, create_constraint=True, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "high",
                "normal",
                name="alert_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("gate_event_id", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_id", sa.Uuid(), nullable=True),
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
            ["acknowledged_by_id"],
            ["users.id"],
            name=op.f("fk_alerts_acknowledged_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["gate_event_id"],
            ["gate_events.id"],
            name=op.f("fk_alerts_gate_event_id_gate_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_alerts_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_gate_event_id"), "alerts", ["gate_event_id"], unique=False)
    op.create_index(
        "ix_alerts_society_open", "alerts", ["society_id", "acknowledged_at"], unique=False
    )
    op.create_table(
        "visit_status_changes",
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum(
                "pending_approval",
                "approved",
                "inside",
                "overstayed",
                "escalated",
                "exited",
                "denied",
                "expired",
                name="from_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "pending_approval",
                "approved",
                "inside",
                "overstayed",
                "escalated",
                "exited",
                "denied",
                "expired",
                name="to_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "trigger",
            sa.Enum(
                "approve",
                "deny",
                "enter",
                "overstay",
                "escalate",
                "exit",
                "expire",
                name="visit_trigger",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("gate_event_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_visit_status_changes_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["gate_event_id"],
            ["gate_events.id"],
            name=op.f("fk_visit_status_changes_gate_event_id_gate_events"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            name=op.f("fk_visit_status_changes_visit_id_visits"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visit_status_changes")),
    )
    op.create_index(
        op.f("ix_visit_status_changes_visit_id"), "visit_status_changes", ["visit_id"], unique=False
    )
    op.add_column("gate_events", sa.Column("ocr_fixes", sa.SmallInteger(), nullable=True))
    op.add_column("gate_events", sa.Column("match_distance", sa.SmallInteger(), nullable=True))
    op.add_column("gate_events", sa.Column("paired_event_id", sa.Uuid(), nullable=True))
    op.add_column(
        "gate_events",
        sa.Column(
            "review_reason",
            sa.Enum(
                "low_confidence",
                "unreadable",
                "ambiguous_match",
                name="review_reason",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "gate_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("gate_events", sa.Column("reviewed_by_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_gate_events_review_queue",
        "gate_events",
        ["society_id", "captured_at"],
        unique=False,
        postgresql_where=sa.text("needs_review AND reviewed_at IS NULL"),
    )
    op.create_unique_constraint(
        op.f("uq_gate_events_paired_event_id"), "gate_events", ["paired_event_id"]
    )
    op.create_foreign_key(
        op.f("fk_gate_events_paired_event_id_gate_events"),
        "gate_events",
        "gate_events",
        ["paired_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_gate_events_reviewed_by_id_users"),
        "gate_events",
        "users",
        ["reviewed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_gate_events_reviewed_by_id_users"), "gate_events", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_gate_events_paired_event_id_gate_events"), "gate_events", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_gate_events_paired_event_id"), "gate_events", type_="unique")
    op.drop_index(
        "ix_gate_events_review_queue",
        table_name="gate_events",
        postgresql_where=sa.text("needs_review AND reviewed_at IS NULL"),
    )
    op.drop_column("gate_events", "reviewed_by_id")
    op.drop_column("gate_events", "reviewed_at")
    op.drop_column("gate_events", "review_reason")
    op.drop_column("gate_events", "paired_event_id")
    op.drop_column("gate_events", "match_distance")
    op.drop_column("gate_events", "ocr_fixes")
    op.drop_index(op.f("ix_visit_status_changes_visit_id"), table_name="visit_status_changes")
    op.drop_table("visit_status_changes")
    op.drop_index("ix_alerts_society_open", table_name="alerts")
    op.drop_index(op.f("ix_alerts_gate_event_id"), table_name="alerts")
    op.drop_table("alerts")
