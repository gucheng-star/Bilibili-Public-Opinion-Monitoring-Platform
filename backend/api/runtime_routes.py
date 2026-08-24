"""Small local-only lifecycle API consumed by the desktop shell."""

from __future__ import annotations

import os

from fastapi import APIRouter

from services.auth import credential_reentry_required
from services.runtime_state import current_activity


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/health")
def health():
    """Unauthenticated only so the local shell can wait for first boot.

    The backend is bound to loopback in desktop mode; no user data or secrets
    are returned from this endpoint.
    """
    return {
        "ok": True,
        "version": os.getenv("BILI_APP_VERSION", "0.1.0"),
        "desktop": bool(os.getenv("BILI_LOCAL_TOKEN")),
    }


@router.get("/activity")
def activity():
    value = current_activity()
    value["can_exit"] = not value["active"]
    return value


@router.post("/prepare-exit")
def prepare_exit():
    value = current_activity()
    return {
        "can_exit": not value["active"],
        "activity": value,
        "credential_reentry_required": credential_reentry_required(),
    }
