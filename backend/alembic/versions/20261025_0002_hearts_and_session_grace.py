"""Hearts (small ephemeral signals between the two members) and a short grace
period for the session token replaced by the last rotation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("previous_token_hash", sa.String(length=64), nullable=True))
        batch.create_index(
            batch.f("ix_auth_sessions_previous_token_hash"), ["previous_token_hash"]
        )

    op.create_table(
        "hearts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        _ts("created_at"),
        _ts("seen_at", nullable=True),
        sa.CheckConstraint(
            "kind IN ('heart', 'thinking_of_you', 'love_this_song', 'miss_you', 'good_night')",
            name=op.f("ck_hearts_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name=op.f("fk_hearts_recipient_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_hearts_room_id_rooms"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name=op.f("fk_hearts_sender_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hearts")),
    )
    op.create_index(op.f("ix_hearts_recipient_id"), "hearts", ["recipient_id"])
    op.create_index(op.f("ix_hearts_room_id"), "hearts", ["room_id"])
    op.create_index(op.f("ix_hearts_sender_id"), "hearts", ["sender_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_hearts_sender_id"), table_name="hearts")
    op.drop_index(op.f("ix_hearts_room_id"), table_name="hearts")
    op.drop_index(op.f("ix_hearts_recipient_id"), table_name="hearts")
    op.drop_table("hearts")
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_index(batch.f("ix_auth_sessions_previous_token_hash"))
        batch.drop_column("previous_token_hash")
