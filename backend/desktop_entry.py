"""PyInstaller entry point for the portable Windows backend."""

from __future__ import annotations

import os
import socket
import sys
import traceback
from pathlib import Path

import uvicorn


def _redirect_windowed_output() -> None:
    """Keep backend diagnostics without opening a console window."""
    data_dir = Path(os.environ["BILI_DATA_DIR"])
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = (log_dir / "backend.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream


def main() -> None:
    os.environ["BILI_DESKTOP_MODE"] = "1"
    _redirect_windowed_output()
    token = os.getenv("BILI_LOCAL_TOKEN")
    if not token:
        raise RuntimeError("桌面后端必须由桌面外壳提供 BILI_LOCAL_TOKEN")
    # Import the app after desktop mode and portable paths are available.
    # Passing the object (instead of the string ``main:app``) also lets
    # PyInstaller discover and bundle the complete application graph.
    from main import app

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(socket.SOMAXCONN)
    os.environ["BILI_BOUND_PORT"] = str(listener.getsockname()[1])
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="info")
    uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # The onefile backend intentionally has no console window. Keep a
        # traceback beside the portable data instead of failing invisibly.
        try:
            data_dir = Path(os.getenv("BILI_DATA_DIR", "."))
            log_path = data_dir / "logs" / "backend-startup-error.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            raise
