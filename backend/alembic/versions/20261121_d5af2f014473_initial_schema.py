"""Initial schema: every table of the GateSense data model.

Revision ID: d5af2f014473
Revises:
Create Date: 2026-11-21 14:18:12.815132+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5af2f014473"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "societies",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_societies")),
    )
    op.create_table(
        "flats",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("block", sa.String(length=8), nullable=False),
        sa.Column("number", sa.String(length=8), nullable=False),
        sa.Column("floor", sa.SmallInteger(), nullable=True),
        sa.Column("parking_slots", sa.SmallInteger(), nullable=False),
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
            ["society_id"], ["societies.id"], name=op.f("fk_flats_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flats")),
        sa.UniqueConstraint(
            "society_id", "block", "number", name=op.f("uq_flats_society_id_block_number")
        ),
    )
    op.create_index(op.f("ix_flats_society_id"), "flats", ["society_id"], unique=False)
    op.create_table(
        "gates",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            ["society_id"], ["societies.id"], name=op.f("fk_gates_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gates")),
    )
    op.create_index(op.f("ix_gates_society_id"), "gates", ["society_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "guard",
                "resident",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
            ["society_id"], ["societies.id"], name=op.f("fk_users_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_index(op.f("ix_users_society_id"), "users", ["society_id"], unique=False)
    op.create_table(
        "visitors",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
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
            ["society_id"], ["societies.id"], name=op.f("fk_visitors_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visitors")),
    )
    op.create_index(op.f("ix_visitors_phone"), "visitors", ["phone"], unique=False)
    op.create_index(op.f("ix_visitors_society_id"), "visitors", ["society_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_audit_logs_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_society_created", "audit_logs", ["society_id", "created_at"], unique=False
    )
    op.create_table(
        "devices",
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column(
            "direction",
            sa.Enum(
                "entry",
                "exit",
                name="lane_direction",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("api_key_prefix", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["gate_id"], ["gates.id"], name=op.f("fk_devices_gate_id_gates")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("api_key_hash", name=op.f("uq_devices_api_key_hash")),
    )
    op.create_index(op.f("ix_devices_gate_id"), "devices", ["gate_id"], unique=False)
    op.create_table(
        "guest_passes",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("flat_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("guest_name", sa.String(length=120), nullable=False),
        sa.Column("guest_phone", sa.String(length=20), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "guest",
                "delivery",
                "cab",
                "service",
                name="visit_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("plate_normalized", sa.String(length=12), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "plate_normalized IS NOT NULL OR code_hash IS NOT NULL",
            name=op.f("ck_guest_passes_plate_or_code"),
        ),
        sa.CheckConstraint(
            "use_count <= max_uses", name=op.f("ck_guest_passes_within_usage_limit")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_guest_passes_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["flat_id"], ["flats.id"], name=op.f("fk_guest_passes_flat_id_flats")
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_guest_passes_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_passes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_guest_passes_code_hash")),
    )
    op.create_index(op.f("ix_guest_passes_flat_id"), "guest_passes", ["flat_id"], unique=False)
    op.create_index(
        op.f("ix_guest_passes_plate_normalized"), "guest_passes", ["plate_normalized"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("jti", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "residents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("flat_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resident_type",
            sa.Enum(
                "owner",
                "tenant",
                "family",
                name="resident_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_primary_contact", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["flat_id"], ["flats.id"], name=op.f("fk_residents_flat_id_flats")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_residents_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_residents")),
        sa.UniqueConstraint("user_id", "flat_id", name=op.f("uq_residents_user_id_flat_id")),
    )
    op.create_index(op.f("ix_residents_flat_id"), "residents", ["flat_id"], unique=False)
    op.create_index(op.f("ix_residents_user_id"), "residents", ["user_id"], unique=False)
    op.create_table(
        "vehicles",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("flat_id", sa.Uuid(), nullable=False),
        sa.Column("plate_raw", sa.String(length=20), nullable=False),
        sa.Column("plate_normalized", sa.String(length=12), nullable=False),
        sa.Column(
            "vehicle_type",
            sa.Enum(
                "car",
                "two_wheeler",
                name="vehicle_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("make_model", sa.String(length=60), nullable=True),
        sa.Column("colour", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["flat_id"], ["flats.id"], name=op.f("fk_vehicles_flat_id_flats")),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_vehicles_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicles")),
        sa.UniqueConstraint(
            "society_id", "plate_normalized", name=op.f("uq_vehicles_society_id_plate_normalized")
        ),
    )
    op.create_index(op.f("ix_vehicles_flat_id"), "vehicles", ["flat_id"], unique=False)
    op.create_index(
        op.f("ix_vehicles_plate_normalized"), "vehicles", ["plate_normalized"], unique=False
    )
    op.create_table(
        "watchlist",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("plate_normalized", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("added_by_id", sa.Uuid(), nullable=True),
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
            ["added_by_id"],
            ["users.id"],
            name=op.f("fk_watchlist_added_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_watchlist_society_id_societies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist")),
        sa.UniqueConstraint(
            "society_id", "plate_normalized", name=op.f("uq_watchlist_society_id_plate_normalized")
        ),
    )
    op.create_index(
        op.f("ix_watchlist_plate_normalized"), "watchlist", ["plate_normalized"], unique=False
    )
    op.create_table(
        "gate_events",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum(
                "entry",
                "exit",
                name="lane_direction",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("plate_raw", sa.String(length=32), nullable=False),
        sa.Column("plate_normalized", sa.String(length=12), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("snapshot_path", sa.String(length=255), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "match_result",
            sa.Enum(
                "resident",
                "guest_pass",
                "visitor",
                "watchlist",
                "unknown",
                "low_confidence",
                name="match_result",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("vehicle_id", sa.Uuid(), nullable=True),
        sa.Column("visit_id", sa.Uuid(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_gate_events_device_id_devices")
        ),
        sa.ForeignKeyConstraint(
            ["gate_id"], ["gates.id"], name=op.f("fk_gate_events_gate_id_gates")
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_gate_events_society_id_societies")
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_gate_events_vehicle_id_vehicles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_events")),
        sa.UniqueConstraint("event_hash", name=op.f("uq_gate_events_event_hash")),
    )
    op.create_index(op.f("ix_gate_events_device_id"), "gate_events", ["device_id"], unique=False)
    op.create_index(
        op.f("ix_gate_events_plate_normalized"), "gate_events", ["plate_normalized"], unique=False
    )
    op.create_index(
        "ix_gate_events_society_captured",
        "gate_events",
        ["society_id", "captured_at"],
        unique=False,
    )
    op.create_table(
        "plate_corrections",
        sa.Column("gate_event_id", sa.Uuid(), nullable=False),
        sa.Column("original_plate", sa.String(length=32), nullable=False),
        sa.Column("corrected_plate", sa.String(length=12), nullable=False),
        sa.Column("corrected_by_id", sa.Uuid(), nullable=True),
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
            ["corrected_by_id"],
            ["users.id"],
            name=op.f("fk_plate_corrections_corrected_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["gate_event_id"],
            ["gate_events.id"],
            name=op.f("fk_plate_corrections_gate_event_id_gate_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plate_corrections")),
    )
    op.create_index(
        op.f("ix_plate_corrections_gate_event_id"),
        "plate_corrections",
        ["gate_event_id"],
        unique=False,
    )
    op.create_table(
        "visits",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column("flat_id", sa.Uuid(), nullable=False),
        sa.Column("visitor_id", sa.Uuid(), nullable=True),
        sa.Column("guest_pass_id", sa.Uuid(), nullable=True),
        sa.Column("plate_normalized", sa.String(length=12), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "guest",
                "delivery",
                "cab",
                "service",
                name="visit_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending_approval",
                "approved",
                "inside",
                "overstayed",
                "escalated",
                "exited",
                "denied",
                "expired",
                name="visit_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("registered_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("entry_event_id", sa.Uuid(), nullable=True),
        sa.Column("exit_event_id", sa.Uuid(), nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
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
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_visits_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entry_event_id"],
            ["gate_events.id"],
            name=op.f("fk_visits_entry_event_id_gate_events"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["exit_event_id"],
            ["gate_events.id"],
            name=op.f("fk_visits_exit_event_id_gate_events"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["flat_id"], ["flats.id"], name=op.f("fk_visits_flat_id_flats")),
        sa.ForeignKeyConstraint(
            ["guest_pass_id"],
            ["guest_passes.id"],
            name=op.f("fk_visits_guest_pass_id_guest_passes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["registered_by_id"],
            ["users.id"],
            name=op.f("fk_visits_registered_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["society_id"], ["societies.id"], name=op.f("fk_visits_society_id_societies")
        ),
        sa.ForeignKeyConstraint(
            ["visitor_id"],
            ["visitors.id"],
            name=op.f("fk_visits_visitor_id_visitors"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visits")),
    )
    op.create_index(op.f("ix_visits_flat_id"), "visits", ["flat_id"], unique=False)
    op.create_index(
        op.f("ix_visits_plate_normalized"), "visits", ["plate_normalized"], unique=False
    )
    op.create_index(op.f("ix_visits_status"), "visits", ["status"], unique=False)
    op.create_index(op.f("ix_visits_visitor_id"), "visits", ["visitor_id"], unique=False)
    # gate_events.visit_id and visits.entry/exit_event_id point at each other, so this
    # foreign key can only be added once both tables exist.
    op.create_foreign_key(
        op.f("fk_gate_events_visit_id_visits"),
        "gate_events",
        "visits",
        ["visit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "approvals",
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "denied",
                "timed_out",
                name="approval_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "channel",
            sa.Enum(
                "web",
                "telegram",
                "guard",
                name="approval_channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
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
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_approvals_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            name=op.f("fk_approvals_visit_id_visits"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index(op.f("ix_approvals_visit_id"), "approvals", ["visit_id"], unique=False)
    op.create_table(
        "escalation_tasks",
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "resolved",
                name="escalation_task_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "reached",
                "not_reached",
                "vehicle_left",
                name="escalation_outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_escalation_tasks_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            name=op.f("fk_escalation_tasks_visit_id_visits"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalation_tasks")),
    )
    op.create_index(
        op.f("ix_escalation_tasks_status"), "escalation_tasks", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_escalation_tasks_visit_id"), "escalation_tasks", ["visit_id"], unique=False
    )
    op.create_table(
        "notifications",
        sa.Column("society_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum(
                "email",
                "telegram",
                name="notification_channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("visit_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sent",
                "failed",
                name="notification_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            ["society_id"], ["societies.id"], name=op.f("fk_notifications_society_id_societies")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            name=op.f("fk_notifications_visit_id_visits"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_notifications_idempotency_key")),
    )
    op.create_index(op.f("ix_notifications_status"), "notifications", ["status"], unique=False)
    op.create_index(op.f("ix_notifications_visit_id"), "notifications", ["visit_id"], unique=False)


def downgrade() -> None:
    op.drop_constraint(op.f("fk_gate_events_visit_id_visits"), "gate_events", type_="foreignkey")
    op.drop_index(op.f("ix_notifications_visit_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_status"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_escalation_tasks_visit_id"), table_name="escalation_tasks")
    op.drop_index(op.f("ix_escalation_tasks_status"), table_name="escalation_tasks")
    op.drop_table("escalation_tasks")
    op.drop_index(op.f("ix_approvals_visit_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_visits_visitor_id"), table_name="visits")
    op.drop_index(op.f("ix_visits_status"), table_name="visits")
    op.drop_index(op.f("ix_visits_plate_normalized"), table_name="visits")
    op.drop_index(op.f("ix_visits_flat_id"), table_name="visits")
    op.drop_table("visits")
    op.drop_index(op.f("ix_plate_corrections_gate_event_id"), table_name="plate_corrections")
    op.drop_table("plate_corrections")
    op.drop_index("ix_gate_events_society_captured", table_name="gate_events")
    op.drop_index(op.f("ix_gate_events_plate_normalized"), table_name="gate_events")
    op.drop_index(op.f("ix_gate_events_device_id"), table_name="gate_events")
    op.drop_table("gate_events")
    op.drop_index(op.f("ix_watchlist_plate_normalized"), table_name="watchlist")
    op.drop_table("watchlist")
    op.drop_index(op.f("ix_vehicles_plate_normalized"), table_name="vehicles")
    op.drop_index(op.f("ix_vehicles_flat_id"), table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_index(op.f("ix_residents_user_id"), table_name="residents")
    op.drop_index(op.f("ix_residents_flat_id"), table_name="residents")
    op.drop_table("residents")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_guest_passes_plate_normalized"), table_name="guest_passes")
    op.drop_index(op.f("ix_guest_passes_flat_id"), table_name="guest_passes")
    op.drop_table("guest_passes")
    op.drop_index(op.f("ix_devices_gate_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_audit_logs_society_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_visitors_society_id"), table_name="visitors")
    op.drop_index(op.f("ix_visitors_phone"), table_name="visitors")
    op.drop_table("visitors")
    op.drop_index(op.f("ix_users_society_id"), table_name="users")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_gates_society_id"), table_name="gates")
    op.drop_table("gates")
    op.drop_index(op.f("ix_flats_society_id"), table_name="flats")
    op.drop_table("flats")
    op.drop_table("societies")
