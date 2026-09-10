"""Create validated, user-requested static SQLite snapshots for Agent MCP."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.runtime_paths import data_dir, database_path


MCP_CONTRACT_VERSION = 2
MANIFEST_SCHEMA_VERSION = 1
READ_ONLY_SCHEMA_SIGNATURE = 1
_DATABASE_FILE_NAME = "database.sqlite3"
_MANIFEST_FILE_NAME = "manifest.json"
_MAX_MANIFEST_BYTES = 16 * 1024


class AgentSnapshotError(Exception):
    """A deliberately path-free error suitable for the desktop API."""


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    attributes = getattr(file_stat, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400))


def _has_reparse_component(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            if _is_reparse_point(os.lstat(current)):
                return True
        except OSError:
            return False
    return False


def _regular_file(path: Path) -> bool:
    try:
        value = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(value.st_mode) and not _is_reparse_point(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AgentSnapshotService:
    """Own the application-side write path; MCP imports none of this service."""

    def __init__(self, *, source_path: Path | None = None, root_path: Path | None = None) -> None:
        self.source_path = source_path or database_path()
        self.root_path = root_path or data_dir() / "agent-snapshots"

    def create(self) -> dict[str, Any]:
        source = self._validated_source()
        root = self._prepare_root()
        snapshot_id = str(uuid.uuid4())
        temporary = root / f".tmp-{snapshot_id}"
        published = root / snapshot_id
        try:
            # A UUID collision is extraordinarily unlikely, but never replace an
            # existing snapshot if it somehow occurs.
            temporary.mkdir(mode=0o700)
            if _has_reparse_component(temporary) or published.exists():
                raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")
            database_copy = temporary / _DATABASE_FILE_NAME
            self._backup(source, database_copy)
            database_digest = _sha256(database_copy)
            counts, database_schema = self._snapshot_metadata(database_copy)
            created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            manifest = {
                "schema": MANIFEST_SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "created_at": created_at,
                "application_version": os.getenv("BILI_APP_VERSION", "0.2.4"),
                "mcp_contract_version": MCP_CONTRACT_VERSION,
                "database_file": _DATABASE_FILE_NAME,
                "database_sha256": database_digest,
                "record_counts": counts,
                "database_schema": database_schema,
            }
            manifest_path = temporary / _MANIFEST_FILE_NAME
            self._write_manifest(manifest_path, manifest)
            self._verify_staged_snapshot(database_copy, manifest_path, manifest)
            # Both paths are children created in this operation, so a directory
            # rename publishes the database and its matching manifest together.
            os.replace(temporary, published)
            return {
                "snapshot_id": snapshot_id,
                "created_at": created_at,
                "database_path": str(published / _DATABASE_FILE_NAME),
                "manifest_path": str(published / _MANIFEST_FILE_NAME),
                "database_sha256": database_digest,
                "application_version": manifest["application_version"],
                "mcp_contract_version": MCP_CONTRACT_VERSION,
                "record_counts": counts,
            }
        except AgentSnapshotError:
            self._remove_temporary(temporary)
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError):
            self._remove_temporary(temporary)
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。") from None

    def _validated_source(self) -> Path:
        source = Path(self.source_path)
        if not source.is_absolute() or _has_reparse_component(source) or not _regular_file(source):
            raise AgentSnapshotError("无法生成 Agent 快照，请确认本地分析数据可用。")
        return source

    def _prepare_root(self) -> Path:
        root = Path(self.root_path)
        if not root.is_absolute() or _has_reparse_component(root.parent):
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            details = os.lstat(root)
        except OSError as exc:
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。") from exc
        if not stat.S_ISDIR(details.st_mode) or _is_reparse_point(details) or _has_reparse_component(root):
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")
        return root

    @staticmethod
    def _backup(source: Path, destination: Path) -> None:
        # ``backup`` reads through SQLite, therefore it includes committed WAL
        # data; a byte-for-byte file copy would not provide this guarantee.
        with closing(sqlite3.connect(source, timeout=10)) as source_db:
            with closing(sqlite3.connect(destination)) as target_db:
                source_db.backup(target_db)
                # A read-only immutable client must never need source WAL
                # sidecars.  The copied database is independent, so convert
                # its journal mode before it is hashed and published.
                target_db.execute("PRAGMA journal_mode=DELETE")

    @staticmethod
    def _snapshot_metadata(database_copy: Path) -> tuple[dict[str, int], dict[str, int]]:
        with closing(sqlite3.connect(f"{database_copy.as_uri()}?mode=ro", uri=True)) as connection:
            def count(table: str) -> int:
                row = connection.execute(
                    "SELECT type FROM sqlite_schema WHERE name=? COLLATE BINARY", (table,),
                ).fetchone()
                if row is None or row[0] != "table":
                    raise AgentSnapshotError("无法生成 Agent 快照，当前数据结构不受支持。")
                return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

            return (
                {"analyses": count("analyses"), "comments": count("comments"), "events": count("analysis_groups")},
                {
                    "read_only_schema_signature": READ_ONLY_SCHEMA_SIGNATURE,
                    "sqlite_user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
                },
            )

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_MANIFEST_BYTES:
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _verify_staged_snapshot(database_copy: Path, manifest_path: Path, expected: dict[str, Any]) -> None:
        if not _regular_file(database_copy) or not _regular_file(manifest_path):
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")
        if _sha256(database_copy) != expected["database_sha256"]:
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")
        if json.loads(manifest_path.read_text(encoding="utf-8")) != expected:
            raise AgentSnapshotError("无法生成 Agent 快照，请稍后重试。")

    @staticmethod
    def _remove_temporary(path: Path) -> None:
        """Only remove a known, un-published directory created by this call."""
        try:
            if not path.exists() or _has_reparse_component(path):
                return
            for child in path.iterdir():
                if child.is_file() and not _has_reparse_component(child):
                    child.unlink()
            path.rmdir()
        except OSError:
            # A failed cleanup is harmless: later requests use a different UUID
            # and never interpret ``.tmp-*`` directories as snapshots.
            return
