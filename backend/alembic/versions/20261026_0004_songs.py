"""Songs shared on purpose: a pick for the other member, a shared playlist,
and answers to the daily question. Additive only: existing rows are untouched.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def _uuid(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.Uuid(), nullable=False)


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"), ondelete="CASCADE"
    )


def _track_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("track_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("artist_names", sa.JSON(), nullable=False),
        sa.Column("artwork_url", sa.String(length=500), nullable=True),
        sa.Column("track_url", sa.String(length=500), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "song_picks",
        _uuid("id"),
        _uuid("room_id"),
        _uuid("sender_id"),
        _uuid("recipient_id"),
        *_track_columns(),
        _ts("created_at"),
        _fk("song_picks", "recipient_id", "users"),
        _fk("song_picks", "room_id", "rooms"),
        _fk("song_picks", "sender_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_song_picks")),
        sa.UniqueConstraint("sender_id", name=op.f("uq_song_picks_sender_id")),
    )
    op.create_index(op.f("ix_song_picks_recipient_id"), "song_picks", ["recipient_id"])
    op.create_index(op.f("ix_song_picks_room_id"), "song_picks", ["room_id"])

    op.create_table(
        "playlist_items",
        _uuid("id"),
        _uuid("room_id"),
        _uuid("added_by"),
        *_track_columns(),
        _ts("created_at"),
        _fk("playlist_items", "added_by", "users"),
        _fk("playlist_items", "room_id", "rooms"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playlist_items")),
        sa.UniqueConstraint(
            "room_id",
            "provider",
            "track_key",
            name=op.f("uq_playlist_items_room_id_provider_track_key"),
        ),
    )
    op.create_index(op.f("ix_playlist_items_added_by"), "playlist_items", ["added_by"])
    op.create_index(op.f("ix_playlist_items_room_id"), "playlist_items", ["room_id"])

    op.create_table(
        "daily_answers",
        _uuid("id"),
        _uuid("room_id"),
        _uuid("user_id"),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("answer", sa.String(length=140), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _fk("daily_answers", "room_id", "rooms"),
        _fk("daily_answers", "user_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_answers")),
        sa.UniqueConstraint("user_id", "day", name=op.f("uq_daily_answers_user_id_day")),
    )
    op.create_index(op.f("ix_daily_answers_room_id"), "daily_answers", ["room_id"])
    op.create_index(op.f("ix_daily_answers_user_id"), "daily_answers", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_answers_user_id"), table_name="daily_answers")
    op.drop_index(op.f("ix_daily_answers_room_id"), table_name="daily_answers")
    op.drop_table("daily_answers")
    op.drop_index(op.f("ix_playlist_items_room_id"), table_name="playlist_items")
    op.drop_index(op.f("ix_playlist_items_added_by"), table_name="playlist_items")
    op.drop_table("playlist_items")
    op.drop_index(op.f("ix_song_picks_room_id"), table_name="song_picks")
    op.drop_index(op.f("ix_song_picks_recipient_id"), table_name="song_picks")
    op.drop_table("song_picks")
