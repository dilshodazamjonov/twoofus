from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel, OutModel


class LoginIn(ApiModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class NewAccountIn(ApiModel):
    username: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=10, max_length=256)


class OwnerSetupIn(NewAccountIn):
    bootstrap_token: str = Field(min_length=32, max_length=256)


class UserOut(OutModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: Literal["owner", "partner"]


class SessionOut(OutModel):
    authenticated: bool
    user: UserOut | None = None
    session_expires_at: datetime | None = None
    csrf_token: str


class CsrfOut(OutModel):
    csrf_token: str


class SetupStatusOut(OutModel):
    owner_exists: bool
    web_bootstrap_enabled: bool
