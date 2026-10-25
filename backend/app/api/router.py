from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import csrf_protect
from app.api.routes import auth, invitations, me, providers, room, songs, system, tulips

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(csrf_protect)])
for module in (system, auth, invitations, me, room, tulips, songs, providers):
    api_router.include_router(module.router)
