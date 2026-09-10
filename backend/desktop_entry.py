"""PyInstaller entry point for the portable Windows backend."""

from __future__ import annotations

import json
import os
import socket
import sys
import traceback
import uuid
from pathlib import Path

import uvicorn


_SNAPSHOT_BOOTSTRAP_ARGUMENT = "--create-agent-snapshot"
_SNAPSHOT_BOOTSTRAP_RECORD = "latest-bootstrap.json"


def _write_bootstrap_record(snapshot: dict[str, object], nonce: str) -> None:
    """Atomically publish the shell-to-Agent handoff for a windowed EXE.

    A portable Windows GUI EXE has no reliable inherited stdout. The desktop
    shell therefore gives the Agent one deterministic, application-owned file
    to read after it exits. The shell accepts it only when its per-run nonce
    matches, so a stale record cannot be reused after a failed refresh.
    """
    from services.runtime_paths import data_dir

    root = data_dir() / "agent-snapshots"
    record = root / _SNAPSHOT_BOOTSTRAP_RECORD
    temporary = root / f".{_SNAPSHOT_BOOTSTRAP_RECORD}.{uuid.uuid4().hex}.tmp"
    payload = {"schema": 1, "nonce": nonce, "snapshot": snapshot}
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, record)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise RuntimeError("无法写入本地 Agent 接入记录") from exc


def create_agent_snapshot_for_bootstrap() -> int:
    """Create the same validated snapshot as the desktop API, then exit.

    This mode is intentionally invoked only by the signed desktop shell's
    ``--mcp-bootstrap`` command. It never starts HTTP, reads credentials, or
    accepts a caller-selected database path. The shell supplies the portable
    data directory and fixed database location before this process starts.
    """
    if os.getenv("BILI_AGENT_BOOTSTRAP") != "1":
        return 2

    from services.agent_snapshots import AgentSnapshotError, AgentSnapshotService

    try:
        snapshot = AgentSnapshotService().create()
    except AgentSnapshotError:
        return 3
    nonce = os.getenv("BILI_AGENT_BOOTSTRAP_NONCE")
    if not nonce or len(nonce) != 32 or any(character not in "0123456789abcdef" for character in nonce):
        return 2
    _write_bootstrap_record(snapshot, nonce)
    return 0


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
    if sys.argv[1:] == [_SNAPSHOT_BOOTSTRAP_ARGUMENT]:
        raise SystemExit(create_agent_snapshot_for_bootstrap())
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
    except SystemExit:
        raise
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
