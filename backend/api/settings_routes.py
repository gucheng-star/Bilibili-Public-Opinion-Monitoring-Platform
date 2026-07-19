"""API Key management routes"""

import json
import os
from fastapi import APIRouter

router = APIRouter(prefix="/api")

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")


def _read_settings() -> dict:
    """Read settings from JSON file."""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_settings(data: dict) -> None:
    """Write settings to JSON file."""
    current = _read_settings()
    current.update(data)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


@router.get("/settings")
async def get_settings():
    """Return current settings (excluding sensitive full key)."""
    settings = _read_settings()
    api_key = settings.get("api_key", "")
    return {
        "has_api_key": bool(api_key),
        "api_key_preview": (api_key[:4] + "****" + api_key[-4:]) if len(api_key) > 8 else "",
        "analysis_mode": settings.get("analysis_mode", "nlp"),
    }


@router.put("/settings")
async def update_settings(req: dict):
    """Update settings (api_key, analysis_mode)."""
    updates = {}
    if "api_key" in req:
        updates["api_key"] = req["api_key"]
    if "analysis_mode" in req:
        updates["analysis_mode"] = req["analysis_mode"]
    _write_settings(updates)
    return {"ok": True}
