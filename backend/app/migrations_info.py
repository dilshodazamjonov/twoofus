"""Expected Alembic head revision (for the readiness probe)."""

from __future__ import annotations

from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import BACKEND_DIR


@lru_cache(maxsize=1)
def expected_head() -> str | None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()
