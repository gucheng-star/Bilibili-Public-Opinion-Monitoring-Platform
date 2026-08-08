"""Portable-runtime path helpers.

The browser development server keeps using files next to ``backend``.  The
desktop shell supplies ``BILI_DATA_DIR`` (and, where needed, individual file
paths) so every mutable file can live next to the portable executable.
"""

from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    configured = os.getenv("BILI_DATA_DIR")
    root = Path(configured).expanduser() if configured else BACKEND_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def writable_path(env_name: str, default_name: str) -> Path:
    configured = os.getenv(env_name)
    path = Path(configured).expanduser() if configured else data_dir() / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def database_path() -> Path:
    return writable_path("BILI_DB_PATH", "data.db")


def auth_path() -> Path:
    return writable_path("BILI_AUTH_PATH", "auth.json")


def settings_path() -> Path:
    return writable_path("BILI_SETTINGS_PATH", "settings.json")


def handshake_path() -> Path | None:
    configured = os.getenv("BILI_HANDSHAKE_PATH")
    if not configured:
        return None
    path = Path(configured).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()
