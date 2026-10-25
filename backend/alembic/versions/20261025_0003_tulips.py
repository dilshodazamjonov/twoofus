"""Tulips replace hearts: one kind of signal, so no kind column. Hearts were
kept for at most 7 days and are not carried over.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _signal_table(name: str, *extra: sa.SchemaItem) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        *extra,
        _ts("created_at"),
        _ts("seen_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name=op.f(f"fk_{name}_recipient_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f(f"fk_{name}_room_id_rooms"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name=op.f(f"fk_{name}_sender_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    for column in ("recipient_id", "room_id", "sender_id"):
        op.create_index(op.f(f"ix_{name}_{column}"), name, [column])


def _drop_signal_table(name: str) -> None:
    for column in ("sender_id", "room_id", "recipient_id"):
        op.drop_index(op.f(f"ix_{name}_{column}"), table_name=name)
    op.drop_table(name)


def upgrade() -> None:
    _drop_signal_table("hearts")
    _signal_table("tulips")


def downgrade() -> None:
    _drop_signal_table("tulips")
    _signal_table(
        "hearts",
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "kind IN ('heart', 'thinking_of_you', 'love_this_song', 'miss_you', 'good_night')",
            name=op.f("ck_hearts_kind_valid"),
        ),
    )
