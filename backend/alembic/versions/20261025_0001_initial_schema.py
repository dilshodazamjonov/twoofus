"""Initial schema: users, single room + membership, sessions, invitations,
share preferences, provider connections and pending provider authorisations.

Deliberately absent: any table for playback or listening history.

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton", sa.Integer(), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint("singleton = 1", name=op.f("ck_rooms_single_room")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
        sa.UniqueConstraint("singleton", name=op.f("uq_rooms_singleton")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        _ts("password_changed_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        _ts("created_at"),
        _ts("rotated_at"),
        _ts("last_seen_at"),
        _ts("expires_at"),
        _ts("revoked_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        _ts("created_at"),
        _ts("expires_at"),
        _ts("consumed_at", nullable=True),
        sa.Column("consumed_by_user_id", sa.Uuid(), nullable=True),
        _ts("revoked_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["consumed_by_user_id"],
            ["users.id"],
            name=op.f("fk_invitations_consumed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_invitations_created_by_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_invitations_room_id_rooms"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(op.f("ix_invitations_room_id"), "invitations", ["room_id"])

    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        _ts("token_expires_at", nullable=True),
        sa.Column("scopes", sa.String(length=255), nullable=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        _ts("authorized_at"),
        _ts("last_fetch_at", nullable=True),
        _ts("last_success_at", nullable=True),
        sa.Column("last_error_code", sa.String(length=48), nullable=True),
        _ts("last_error_at", nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        _ts("backoff_until", nullable=True),
        _ts("reauth_required_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "provider IN ('spotify', 'yandex', 'demo')",
            name=op.f("ck_provider_connections_provider_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'reauth_required')",
            name=op.f("ck_provider_connections_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_provider_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint("user_id", name=op.f("uq_provider_connections_user_id")),
    )
    op.create_table(
        "room_members",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        _ts("joined_at"),
        sa.CheckConstraint("role IN ('owner', 'partner')", name=op.f("ck_room_members_role_valid")),
        sa.CheckConstraint("slot IN (1, 2)", name=op.f("ck_room_members_slot_range")),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_room_members_room_id_rooms"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_room_members_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("room_id", "slot", name=op.f("pk_room_members")),
        sa.UniqueConstraint("user_id", name=op.f("uq_room_members_user_id")),
    )
    op.create_index(
        "uq_room_members_one_owner",
        "room_members",
        ["room_id"],
        unique=True,
        sqlite_where=sa.text("role = 'owner'"),
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_table(
        "share_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("share_now_playing", sa.Boolean(), nullable=False),
        sa.Column("notice_version_acknowledged", sa.String(length=32), nullable=True),
        _ts("acknowledged_at", nullable=True),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_share_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_share_preferences")),
    )
    op.create_table(
        "provider_auth_flows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=True),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("user_code", sa.String(length=32), nullable=True),
        sa.Column("verification_url", sa.String(length=255), nullable=True),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=True),
        _ts("next_poll_at", nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        _ts("created_at"),
        _ts("expires_at"),
        _ts("completed_at", nullable=True),
        sa.CheckConstraint(
            "kind IN ('oauth_pkce', 'device_code')", name=op.f("ck_provider_auth_flows_kind_valid")
        ),
        sa.CheckConstraint(
            "provider IN ('spotify', 'yandex', 'demo')",
            name=op.f("ck_provider_auth_flows_provider_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'expired', 'cancelled')",
            name=op.f("ck_provider_auth_flows_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name=op.f("fk_provider_auth_flows_session_id_auth_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_provider_auth_flows_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_auth_flows")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_provider_auth_flows_state_hash")),
    )
    op.create_index(op.f("ix_provider_auth_flows_session_id"), "provider_auth_flows", ["session_id"])
    op.create_index(op.f("ix_provider_auth_flows_user_id"), "provider_auth_flows", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_provider_auth_flows_user_id"), table_name="provider_auth_flows")
    op.drop_index(op.f("ix_provider_auth_flows_session_id"), table_name="provider_auth_flows")
    op.drop_table("provider_auth_flows")
    op.drop_table("share_preferences")
    op.drop_index("uq_room_members_one_owner", table_name="room_members")
    op.drop_table("room_members")
    op.drop_table("provider_connections")
    op.drop_index(op.f("ix_invitations_room_id"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
    op.drop_table("rooms")
