"""Migrations: full down/up round trip, and no drift between models and migrations.

Runs against SQLite by default and against PostgreSQL when
TWOOFUS_TEST_DATABASE_URL is set (see tests/conftest.py).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.core.config import BACKEND_DIR
from app.db.base import Base

EXPECTED_TABLES = {
    "alembic_version",
    "auth_sessions",
    "daily_answers",
    "invitations",
    "playlist_items",
    "provider_auth_flows",
    "provider_connections",
    "room_members",
    "rooms",
    "share_preferences",
    "song_picks",
    "tulips",
    "users",
}


def _sync_url(url: str) -> str:
    return url.replace("sqlite+aiosqlite", "sqlite").replace("+asyncpg", "+psycopg")


def _alembic(url: str, *args: Any) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    fn = getattr(command, args[0])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(fn, cfg, *args[1:]).result()


def test_round_trip_and_no_model_drift(database_url: str) -> None:
    engine = create_engine(_sync_url(database_url))
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
        _alembic(database_url, "downgrade", "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        _alembic(database_url, "upgrade", "head")
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(context, Base.metadata)
        assert diff == []
    finally:
        engine.dispose()


def test_no_playback_history_table(database_url: str) -> None:
    engine = create_engine(_sync_url(database_url))
    try:
        columns = {
            (table, column["name"])
            for table in inspect(engine).get_table_names()
            for column in inspect(engine).get_columns(table)
        }
    finally:
        engine.dispose()
    # Privacy by design: no listening history. Song details exist only for songs
    # a member chose to share (a pick, the playlist), and never when or how long
    # anyone listened.
    track_fields = {"track_title", "artist_names", "track_url", "artwork_url", "album"}
    assert {table for table, name in columns if name in track_fields} <= {
        "song_picks",
        "playlist_items",
    }
    listening_fields = {"played_at", "progress_ms", "duration_ms", "is_playing", "listened_at"}
    assert not {name for _, name in columns} & listening_fields
