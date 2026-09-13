"""Strictly read-only domain access for the local Agent MCP PoC."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.comment_quality import annotate_exact_duplicates, build_duplicate_statistics
from services.region import analyze_region

NLP_LABELS = ("positive", "negative", "neutral")
V2_EMOTION_LABELS = ("neutral", "joy", "trust", "anticipation", "surprise", "anger", "sadness", "fear", "disgust")
V2_STYLE_LABELS = ("plain", "sarcasm", "meme", "rhetorical", "hyperbole")
MAX_COMMENT_CHARS = 240
MAX_RESPONSE_CHARS = 12_000
MAX_OFFSET = 100_000
MAX_ANALYSIS_COMMENTS = 10_000
MAX_EVENT_COMMENTS = 10_000
MAX_EVENT_MEMBERS = 50
QUERY_TIMEOUT_SECONDS = 5.0
QUERY_PROGRESS_STEPS = 1_000
SUPPORTED_SCHEMA_SIGNATURE = 1
SERVICE_VERSION = "0.1.0"
MANIFEST_SCHEMA_VERSION = 1
_SNAPSHOT_DATABASE_NAME = "database.sqlite3"
_SNAPSHOT_MANIFEST_NAME = "manifest.json"
_MAX_MANIFEST_BYTES = 16 * 1024
AVAILABLE_TOOLS = (
    "bili_list_analyses",
    "bili_get_analysis_overview",
    "bili_search_comments",
    "bili_get_data_source_info",
    "bili_list_events",
    "bili_get_event_overview",
    "bili_search_event_comments",
)

_WINDOWS_DRIVE_FIXED = 3
_WINDOWS_DRIVE_REMOVABLE = 2
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

ALLOWED_READ_COLUMNS = {
    "analyses": {"id", "bv", "video_title", "status", "mode", "total_comments", "created_at", "sentiment_llm_schema_version", "comment_collection_status"},
    "comments": {
        "id", "analysis_id", "content", "likes", "ip_location", "post_time",
        "sentiment_label", "sentiment_llm_label", "sentiment_llm_style", "sentiment_llm_schema_version", "root_rpid", "parent_rpid",
    },
    "analysis_groups": {"id", "name", "created_at", "updated_at"},
    "analysis_group_items": {"id", "group_id", "analysis_id", "position"},
}

REQUIRED_SCHEMA = {
    "analyses": {
        "id": {"INTEGER"},
        "bv": {"TEXT"},
        "video_title": {"TEXT"},
        "status": {"TEXT"},
        "mode": {"TEXT"},
        "total_comments": {"INTEGER"},
        "created_at": {"TEXT", "NUMERIC"},
        "sentiment_llm_schema_version": {"INTEGER"},
    },
    "comments": {
        "id": {"INTEGER"},
        "analysis_id": {"INTEGER"},
        "content": {"TEXT"},
        "likes": {"INTEGER"},
        "ip_location": {"TEXT"},
        "post_time": {"TEXT", "NUMERIC"},
        "sentiment_label": {"TEXT"},
        "sentiment_llm_label": {"TEXT"},
        "sentiment_llm_style": {"TEXT"},
        "sentiment_llm_schema_version": {"INTEGER"},
        "root_rpid": {"INTEGER"},
        "parent_rpid": {"INTEGER"},
    },
}

REQUIRED_EVENT_SCHEMA = {
    "analyses": {
        "id": {"INTEGER"},
        "comment_collection_status": {"TEXT"},
    },
    "analysis_groups": {
        "id": {"INTEGER"},
        "name": {"TEXT"},
        "created_at": {"TEXT", "NUMERIC"},
        "updated_at": {"TEXT", "NUMERIC"},
    },
    "analysis_group_items": {
        "id": {"INTEGER"},
        "group_id": {"INTEGER"},
        "analysis_id": {"INTEGER"},
        "position": {"INTEGER"},
    },
}


class AgentReadOnlyError(Exception):
    def __init__(self, message: str, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.message, self.code = message, code


class ReadOnlyService:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = self._validate_database_path(database_path)
        self._snapshot = self._load_snapshot_manifest()

    @property
    def snapshot_id(self) -> str | None:
        return self._snapshot["snapshot_id"] if self._snapshot else None

    def _snapshot_limitations(self) -> list[str]:
        if self._snapshot:
            return ["数据源为用户主动生成的静态快照；新数据需要生成新快照并重新连接。"]
        return ["当前未提供可信快照清单；snapshot_id 为 null。"]

    def _load_snapshot_manifest(self) -> dict[str, Any] | None:
        """Recognise only the directory layout emitted by AgentSnapshotService.

        A normal user-supplied database remains a supported static copy.  Its
        adjacent timestamps and arbitrary JSON files are deliberately ignored.
        """
        directory = self.database_path.parent
        trusted_root_raw = os.getenv("BILI_AGENT_SNAPSHOT_ROOT", "").strip()
        if not trusted_root_raw:
            return None
        trusted_root = Path(trusted_root_raw)
        if (
            self.database_path.name != _SNAPSHOT_DATABASE_NAME
            or directory.parent.name != "agent-snapshots"
        ):
            return None
        try:
            if not trusted_root.is_absolute() or self._has_reparse_component(trusted_root):
                raise ValueError
            # The desktop shell and Python backend can describe the same safe
            # directory with different Windows canonical spellings (including
            # long and short path names).  The database and trusted root have
            # both passed reparse-point checks, so identity is safe to compare
            # through the filesystem without resolving an untrusted junction.
            if not os.path.samefile(directory.parent, trusted_root):
                return None
            snapshot_uuid = str(uuid.UUID(directory.name))
        except (OSError, ValueError, AttributeError):
            return None
        manifest_path = directory / _SNAPSHOT_MANIFEST_NAME
        try:
            manifest_stat = os.lstat(manifest_path)
            if (
                not stat.S_ISREG(manifest_stat.st_mode)
                or self._is_reparse_point(manifest_stat)
                or manifest_stat.st_size < 2
                or manifest_stat.st_size > _MAX_MANIFEST_BYTES
            ):
                raise ValueError
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw.decode("utf-8"))
            created_at = str(manifest["created_at"])
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            record_counts = manifest["record_counts"]
            database_schema = manifest["database_schema"]
            digest = str(manifest["database_sha256"])
            if (
                set(manifest) != {
                    "schema", "snapshot_id", "created_at", "application_version",
                    "mcp_contract_version", "database_file", "database_sha256",
                    "record_counts", "database_schema",
                }
                or manifest["schema"] != MANIFEST_SCHEMA_VERSION
                or manifest["snapshot_id"] != snapshot_uuid
                or snapshot_uuid != directory.name.casefold()
                or parsed_created_at.tzinfo is None
                or parsed_created_at.utcoffset() != timezone.utc.utcoffset(parsed_created_at)
                or not created_at.endswith("Z")
                or not isinstance(manifest["application_version"], str)
                or not 1 <= len(manifest["application_version"]) <= 80
                or manifest["mcp_contract_version"] != 2
                or manifest["database_file"] != _SNAPSHOT_DATABASE_NAME
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or set(record_counts) != {"analyses", "comments", "events"}
                or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in record_counts.values())
                or database_schema.get("read_only_schema_signature") != SUPPORTED_SCHEMA_SIGNATURE
                or isinstance(database_schema.get("sqlite_user_version"), bool)
                or not isinstance(database_schema.get("sqlite_user_version"), int)
                or self._sha256(self.database_path) != digest
            ):
                raise ValueError
            return {
                "snapshot_id": snapshot_uuid,
                "created_at": created_at,
                "record_counts": dict(record_counts),
                "application_version": manifest["application_version"],
            }
        except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError, KeyError, json.JSONDecodeError):
            raise AgentReadOnlyError("Agent 快照清单无效或与数据库不匹配。", "invalid_snapshot_manifest") from None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _validate_database_path(cls, database_path: str | Path) -> Path:
        """Accept only a static SQLite copy at an absolute, local regular path.

        ``immutable=1`` is intentionally safe only for a stopped backup.  Do
        not resolve first: resolving would conceal a junction or symbolic-link
        input that must be rejected at this boundary.
        """
        raw_path = os.fspath(database_path).strip()
        if not raw_path:
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        normalized = raw_path.replace("/", "\\")
        if normalized.startswith("\\\\") or normalized.startswith("\\\\?\\") or normalized.startswith("\\\\.\\"):
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        path = Path(raw_path)
        if not path.is_absolute() or not path.drive:
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        if path.name.casefold().endswith(_SIDECAR_SUFFIXES):
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        if not cls._is_local_drive(path.drive):
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        if cls._has_reparse_component(path):
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        try:
            file_stat = os.lstat(path)
        except OSError as exc:
            raise AgentReadOnlyError("本地分析数据库不可用，请确认静态副本存在。", "database_unavailable") from exc
        if not stat.S_ISREG(file_stat.st_mode) or cls._is_reparse_point(file_stat):
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        if any(Path(f"{path}{suffix}").exists() for suffix in _SIDECAR_SUFFIXES):
            raise AgentReadOnlyError("本地分析数据库路径不符合静态副本要求。", "invalid_database_path")
        return path

    @staticmethod
    def _is_local_drive(drive: str) -> bool:
        """Reject UNC, device and mapped remote drives before SQLite sees them."""
        if os.name != "nt":
            return False
        root = drive.rstrip("\\/") + "\\"
        try:
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)
        except (AttributeError, OSError):
            return False
        return drive_type in {_WINDOWS_DRIVE_FIXED, _WINDOWS_DRIVE_REMOVABLE}

    @staticmethod
    def _is_reparse_point(file_stat: os.stat_result) -> bool:
        attributes = getattr(file_stat, "st_file_attributes", 0)
        reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        return bool(attributes & reparse_attribute)

    @classmethod
    def _has_reparse_component(cls, path: Path) -> bool:
        current = Path(path.anchor)
        for component in path.parts[1:]:
            current /= component
            try:
                if cls._is_reparse_point(os.lstat(current)):
                    return True
            except OSError:
                # The final existence check gives the safe, path-free error.
                return False
        return False

    def _connect(self, require_event_schema: bool = False) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"{self.database_path.as_uri()}?mode=ro&immutable=1&cache=private",
                uri=True,
                timeout=5,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA busy_timeout=5000")
            if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
                raise AgentReadOnlyError("数据库只读保护未生效，已拒绝继续读取。", "readonly_unavailable")
            self._validate_schema(connection)
            if require_event_schema:
                self._validate_event_schema(connection)
            connection.set_authorizer(self._authorize)
            connection.execute("BEGIN DEFERRED")
            deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline),
                QUERY_PROGRESS_STEPS,
            )
            return connection
        except AgentReadOnlyError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise AgentReadOnlyError("无法以只读方式打开本地分析数据库。", "database_unavailable") from exc

    @staticmethod
    def _sqlite_affinity(declared_type: str) -> str:
        value = declared_type.upper()
        if "INT" in value:
            return "INTEGER"
        if any(token in value for token in ("CHAR", "CLOB", "TEXT")):
            return "TEXT"
        if any(token in value for token in ("REAL", "FLOA", "DOUB")):
            return "REAL"
        if not value or "BLOB" in value:
            return "BLOB"
        return "NUMERIC"

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        """Validate the fixed stage-A schema signature without mutating it."""
        cls._validate_required_schema(connection, REQUIRED_SCHEMA, "只读 Schema")

    @classmethod
    def _validate_event_schema(cls, connection: sqlite3.Connection) -> None:
        """Validate event tables only when a new R1 event operation needs them."""
        cls._validate_required_schema(connection, REQUIRED_EVENT_SCHEMA, "只读事件 Schema")

    @classmethod
    def _validate_required_schema(
        cls,
        connection: sqlite3.Connection,
        required_schema: dict[str, dict[str, set[str]]],
        schema_name: str,
    ) -> None:
        for table, required_columns in required_schema.items():
            table_row = connection.execute(
                "SELECT type FROM sqlite_schema WHERE name=? COLLATE BINARY",
                (table,),
            ).fetchone()
            if table_row is None or table_row["type"] != "table":
                raise AgentReadOnlyError(
                    f"数据库不符合支持的{schema_name} v{SUPPORTED_SCHEMA_SIGNATURE}。",
                    "unsupported_database_schema",
                )
            columns = {
                row["name"]: (cls._sqlite_affinity(row["type"] or ""), row["pk"])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            if any(
                name not in columns or columns[name][0] not in allowed_affinities
                for name, allowed_affinities in required_columns.items()
            ) or columns.get("id", (None, 0))[1] != 1:
                raise AgentReadOnlyError(
                    f"数据库不符合支持的{schema_name} v{SUPPORTED_SCHEMA_SIGNATURE}。",
                    "unsupported_database_schema",
                )

    @staticmethod
    def _database_read_error(exc: sqlite3.Error, action: str) -> AgentReadOnlyError:
        if "interrupted" in str(exc).casefold():
            return AgentReadOnlyError(
                f"{action}超过 {QUERY_TIMEOUT_SECONDS:g} 秒只读查询时限，已安全取消。",
                "query_timeout",
            )
        return AgentReadOnlyError(f"{action}失败，请稍后重试。", "database_read_failed")

    @staticmethod
    def _paging(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise AgentReadOnlyError("limit 必须是 1 至 50 的整数。", "invalid_paging")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= MAX_OFFSET:
            raise AgentReadOnlyError(f"offset 必须是 0 至 {MAX_OFFSET} 的整数。", "invalid_paging")
        return limit, offset

    @staticmethod
    def _authorize(action: int, argument1: str | None, argument2: str | None, _database: str | None, _source: str | None) -> int:
        if action == sqlite3.SQLITE_READ:
            columns = ALLOWED_READ_COLUMNS.get(argument1 or "")
            # SQLite reports an empty column name for aggregate table reads
            # (for example COUNT(id) on an empty event table).  It conveys no
            # sensitive column and remains constrained to an allowlisted table.
            return sqlite3.SQLITE_OK if columns is not None and (
                argument2 in {None, ""} or argument2 in columns
            ) else sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    @staticmethod
    def _id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AgentReadOnlyError("analysis_id 必须是正整数。", "invalid_analysis_id")
        return value

    @staticmethod
    def _mode(mode: str) -> str:
        if mode not in {"nlp", "llm"}:
            raise AgentReadOnlyError("mode 必须是 nlp 或 llm。", "invalid_mode")
        return mode

    @staticmethod
    def _keyword(keyword: str | None) -> str:
        value = str(keyword or "").strip()
        if value and len(value) > 100:
            raise AgentReadOnlyError("keyword 长度不能超过 100 个字符。", "invalid_keyword")
        return value

    @staticmethod
    def _iso(value: Any) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)

    @staticmethod
    def _comment(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "content": row["content"] or "", "likes": row["likes"] or 0,
                "ip_location": row["ip_location"] or "",
                "post_time": row["post_time"], "sentiment_label": row["sentiment_label"] or "",
                "sentiment_llm_label": row["sentiment_llm_label"] or "", "sentiment_llm_style": row["sentiment_llm_style"] or "",
                "sentiment_llm_schema_version": row["sentiment_llm_schema_version"] or 0, "root_rpid": row["root_rpid"],
                "parent_rpid": row["parent_rpid"]}

    @staticmethod
    def _analysis(connection: sqlite3.Connection, analysis_id: int) -> sqlite3.Row:
        row = connection.execute("SELECT id,bv,video_title,status,mode,total_comments,created_at,sentiment_llm_schema_version FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise AgentReadOnlyError("未找到指定的分析记录。", "analysis_not_found")
        if row["status"] != "done":
            raise AgentReadOnlyError(f"该分析尚未完成（当前状态：{row['status'] or '未知'}）。", "analysis_not_done")
        return row

    def _comments(self, connection: sqlite3.Connection, analysis_id: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT id,content,likes,ip_location,post_time,sentiment_label,"
            "sentiment_llm_label,sentiment_llm_style,sentiment_llm_schema_version,root_rpid,parent_rpid FROM comments "
            "WHERE analysis_id=? ORDER BY id ASC LIMIT ?",
            (analysis_id, MAX_ANALYSIS_COMMENTS + 1),
        ).fetchall()
        if len(rows) > MAX_ANALYSIS_COMMENTS:
            raise AgentReadOnlyError(
                f"该分析超过内部预览的 {MAX_ANALYSIS_COMMENTS} 条评论读取上限。",
                "analysis_too_large",
            )
        return [self._comment(row) for row in rows]

    @staticmethod
    def _v2_llm_ready(comments: list[dict[str, Any]]) -> bool:
        return bool(comments) and all(
            item["sentiment_llm_schema_version"] == 2
            and item["sentiment_llm_label"] in V2_EMOTION_LABELS
            and item["sentiment_llm_style"] in V2_STYLE_LABELS
            for item in comments
        )

    def list_analyses(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        limit, offset = self._paging(limit, offset)
        try:
            with closing(self._connect()) as db:
                total = db.execute("SELECT COUNT(*) FROM analyses WHERE status='done'").fetchone()[0]
                emotion_placeholders = ",".join("?" for _ in V2_EMOTION_LABELS)
                style_placeholders = ",".join("?" for _ in V2_STYLE_LABELS)
                rows = db.execute(
                    "SELECT page.id,page.bv,page.video_title,page.created_at,page.status,page.mode,page.sentiment_llm_schema_version,"
                    "page.total_comments,"
                    "(SELECT COUNT(*) FROM comments c WHERE c.analysis_id=page.id) AS stored_count,"
                    "EXISTS(SELECT 1 FROM comments c WHERE c.analysis_id=page.id) AS has_comments,"
                    "NOT EXISTS(SELECT 1 FROM comments c WHERE c.analysis_id=page.id AND "
                    f"(c.sentiment_llm_schema_version != 2 OR c.sentiment_llm_label IS NULL OR c.sentiment_llm_label NOT IN ({emotion_placeholders}) OR c.sentiment_llm_style IS NULL OR c.sentiment_llm_style NOT IN ({style_placeholders}))) "
                    "AS labels_valid FROM (SELECT id,bv,video_title,created_at,status,mode,total_comments,sentiment_llm_schema_version "
                    "FROM analyses WHERE status='done' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?) page",
                    (*V2_EMOTION_LABELS, *V2_STYLE_LABELS, limit, offset),
                ).fetchall()
                values = []
                for row in rows:
                    values.append({"analysis_id": row["id"], "bv": row["bv"], "video_title": row["video_title"] or "",
                                   "created_at": self._iso(row["created_at"]), "status": row["status"],
                                   "analysis_mode": row["mode"] or "nlp", "total_comments": row["stored_count"],
                                   "llm_schema_version": row["sentiment_llm_schema_version"] if row["sentiment_llm_schema_version"] in {0, 1, 2} else 0,
                                   "has_v2_llm_labels": bool(row["has_comments"] and row["labels_valid"])})
                return {
                    "mcp_contract_version": 2,
                    "items": values,
                    "total_count": total,
                    "has_more": offset + len(values) < total,
                    "limit": limit,
                    "offset": offset,
                }
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "读取分析记录") from exc

    def get_analysis_overview(self, analysis_id: int, mode: str = "nlp") -> dict[str, Any]:
        analysis_id, mode = self._id(analysis_id), self._mode(mode)
        try:
            with closing(self._connect()) as db:
                row = self._analysis(db, analysis_id)
                comments = self._comments(db, analysis_id)
                schema_version = row["sentiment_llm_schema_version"] if row["sentiment_llm_schema_version"] in {0, 1, 2} else 0
                ready = schema_version == 2 and self._v2_llm_ready(comments)
                if mode == "llm" and not ready:
                    raise AgentReadOnlyError("该分析尚未完成大模型情绪分析。", "llm_not_ready")
                labels, field = (V2_EMOTION_LABELS, "sentiment_llm_label") if mode == "llm" else (NLP_LABELS, "sentiment_label")
                counts = {label: sum(item[field] == label for item in comments) for label in labels}
                styles = {label: sum(item["sentiment_llm_style"] == label for item in comments) for label in V2_STYLE_LABELS} if mode == "llm" else None
                sentiment_denominator = sum(counts.values())
                times = [item["post_time"] for item in comments if item.get("post_time")]
                annotated = annotate_exact_duplicates(comments)
                actual, declared = len(comments), row["total_comments"] or 0
                limitations = ["地域占比的分母是有地域信息的评论数。"]
                if actual != declared:
                    limitations.append("分析记录声明的评论数与实际保存行数不一致。")
                if sentiment_denominator != actual:
                    limitations.append("部分评论缺少当前模式的合法情绪标签，未计入情绪分母。")
                return {"mcp_contract_version": 2, "analysis_id": row["id"], "bv": row["bv"], "video_title": row["video_title"] or "",
                        "created_at": self._iso(row["created_at"]), "status": row["status"],
                        "analysis_mode": row["mode"] if row["mode"] in {"nlp", "llm"} else "nlp", "llm_schema_version": schema_version, "mode": mode,
                        "declared_total_comments": declared, "stored_comment_count": actual,
                        "sentiment_distribution": counts, "style_distribution": styles, "sentiment_denominator": sentiment_denominator,
                        "time_range": {"earliest": min(times) if times else None, "latest": max(times) if times else None},
                        "top_regions": analyze_region(annotated)[:8], "duplicate_statistics": build_duplicate_statistics(annotated),
                        "data_complete": actual == declared and sentiment_denominator == actual and (mode == "nlp" or ready),
                        "limitations": limitations}
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "读取分析概览") from exc

    def search_comments(self, analysis_id: int, mode: str = "nlp", keyword: str | None = None, sentiment: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        analysis_id, mode = self._id(analysis_id), self._mode(mode)
        keyword, (limit, offset) = self._keyword(keyword), self._paging(limit, offset)
        allowed = set(V2_EMOTION_LABELS if mode == "llm" else NLP_LABELS)
        sentiment = str(sentiment or "").strip()
        if sentiment and sentiment not in allowed:
            raise AgentReadOnlyError("sentiment 与当前分析模式不匹配。", "invalid_sentiment")
        try:
            with closing(self._connect()) as db:
                self._analysis(db, analysis_id)
                all_comments = annotate_exact_duplicates(self._comments(db, analysis_id))
                schema_version = self._analysis(db, analysis_id)["sentiment_llm_schema_version"]
                schema_version = schema_version if schema_version in {0, 1, 2} else 0
                if mode == "llm" and (schema_version != 2 or not self._v2_llm_ready(all_comments)):
                    raise AgentReadOnlyError("该分析尚未完成大模型情绪分析。", "llm_not_ready")
                field = "sentiment_llm_label" if mode == "llm" else "sentiment_label"
                matched = [item for item in all_comments if (not keyword or keyword in item["content"]) and (not sentiment or item[field] == sentiment)]
                output, used = [], 0
                for item in matched[offset:offset + limit]:
                    content = item["content"][:MAX_COMMENT_CHARS]
                    if used + len(content) > MAX_RESPONSE_CHARS:
                        break
                    used += len(content)
                    output.append({"content": content, "post_time": self._iso(item["post_time"]),
                                   "likes": max(0, int(item["likes"] or 0)),
                                   "sentiment": item[field] or "unclassified", "style": item["sentiment_llm_style"] if mode == "llm" else None,
                                   "llm_schema_version": schema_version, "is_exact_duplicate": bool(item["is_exact_duplicate"]),
                                   "has_context": bool(item["root_rpid"] or item["parent_rpid"])})
                return {"mcp_contract_version": 2, "analysis_id": analysis_id, "mode": mode, "llm_schema_version": schema_version, "matched_count": len(matched),
                        "returned_count": len(output), "has_more": offset + len(output) < len(matched),
                        "comments": output,
                        "limitations": ["评论正文单条最多返回 240 字符，单次响应正文合计最多 12000 字符。"]}
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "检索评论") from exc

    @staticmethod
    def _event_id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AgentReadOnlyError("event_id 必须是正整数。", "invalid_event_id")
        return value

    @staticmethod
    def _source_analysis_id(value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AgentReadOnlyError("source_analysis_id 必须是正整数。", "invalid_source_analysis_id")
        return value

    @staticmethod
    def _schema_version(value: Any) -> int:
        return value if value in {0, 1, 2} else 0

    def _event(self, connection: sqlite3.Connection, event_id: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT id,name FROM analysis_groups WHERE id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AgentReadOnlyError("未找到指定的舆情事件。", "event_not_found")
        return row

    def _event_members(self, connection: sqlite3.Connection, event_id: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT i.analysis_id,i.position,a.bv,a.video_title,a.status,a.comment_collection_status "
            "FROM analysis_group_items i "
            "LEFT JOIN analyses a ON a.id=i.analysis_id "
            "WHERE i.group_id=? ORDER BY i.position ASC,i.id ASC LIMIT ?",
            (event_id, MAX_EVENT_MEMBERS + 1),
        ).fetchall()
        if len(rows) > MAX_EVENT_MEMBERS:
            raise AgentReadOnlyError(
                f"该舆情事件超过只读查询的 {MAX_EVENT_MEMBERS} 个来源上限。",
                "event_too_large",
            )
        values: list[dict[str, Any]] = []
        for row in rows:
            status = str(row["status"] or "missing") if row["bv"] is not None else "missing"
            collection_status = (
                str(row["comment_collection_status"] or "missing")[:40]
                if row["bv"] is not None else "missing"
            )
            values.append({
                "analysis_id": int(row["analysis_id"]),
                "bv": str(row["bv"]) if row["bv"] is not None else None,
                "video_title": str(row["video_title"]) if row["video_title"] is not None else None,
                "position": max(0, int(row["position"] or 0)),
                "status": status[:40],
                "comment_collection_status": collection_status,
                "is_available": status == "done" and collection_status == "completed",
            })
        return values

    def _event_comments(self, connection: sqlite3.Connection, event_id: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT c.id,c.analysis_id,a.bv AS source_bv,c.content,c.likes,c.post_time,"
            "c.sentiment_label,c.sentiment_llm_label,c.sentiment_llm_style,"
            "c.sentiment_llm_schema_version,c.root_rpid,c.parent_rpid "
            "FROM analysis_group_items i "
            "JOIN analyses a ON a.id=i.analysis_id "
            "JOIN comments c ON c.analysis_id=a.id "
            "WHERE i.group_id=? AND a.status='done' AND a.comment_collection_status='completed' "
            "ORDER BY i.position ASC,c.id ASC LIMIT ?",
            (event_id, MAX_EVENT_COMMENTS + 1),
        ).fetchall()
        if len(rows) > MAX_EVENT_COMMENTS:
            raise AgentReadOnlyError(
                f"该舆情事件超过内部预览的 {MAX_EVENT_COMMENTS} 条评论读取上限。",
                "event_too_large",
            )
        return [{
            "id": row["id"],
            "source_analysis_id": row["analysis_id"],
            "source_bv": str(row["source_bv"]) if row["source_bv"] is not None else None,
            "content": row["content"] or "",
            "likes": row["likes"] or 0,
            "post_time": row["post_time"],
            "sentiment_label": row["sentiment_label"] or "",
            "sentiment_llm_label": row["sentiment_llm_label"] or "",
            "sentiment_llm_style": row["sentiment_llm_style"] or "",
            "sentiment_llm_schema_version": self._schema_version(row["sentiment_llm_schema_version"]),
            "root_rpid": row["root_rpid"],
            "parent_rpid": row["parent_rpid"],
        } for row in rows]

    @staticmethod
    def _event_llm_coverage(comments: list[dict[str, Any]]) -> dict[str, Any]:
        covered = sum(ReadOnlyService._v2_llm_ready([comment]) for comment in comments)
        total = len(comments)
        return {
            "total_comments": total,
            "covered_comments": covered,
            "pending_or_legacy_comments": total - covered,
            "coverage": covered / total if total else 1.0,
            "fully_covered": covered == total,
        }

    @staticmethod
    def _event_limitations(
        members: list[dict[str, Any]],
        comments: list[dict[str, Any]],
        mode: str,
        sentiment_denominator: int,
    ) -> list[str]:
        limitations = ["精确重复仅在同一来源视频内按非空正文计算。"]
        unavailable = sum(not member["is_available"] for member in members)
        if unavailable:
            limitations.append(f"有 {unavailable} 个事件成员缺失、未完成或评论采集未完成，未将其视为零评论来源。")
        if mode == "llm":
            coverage = ReadOnlyService._event_llm_coverage(comments)
            if not coverage["fully_covered"]:
                limitations.append("LLM 仅统计具备完整 V2 情绪和表达风格标签的评论，未回退为 NLP。")
        elif sentiment_denominator != len(comments):
            limitations.append("部分评论缺少合法 NLP 情绪标签，未计入情绪分母。")
        return limitations

    def get_data_source_info(self) -> dict[str, Any]:
        """Describe a verified Agent snapshot or a manual static copy."""
        compatibility = "compatible"
        if self._snapshot:
            limitations = ["此数据源为用户主动生成的静态快照；新数据需要生成新快照并重新连接。"]
            snapshot_created_at = self._snapshot["created_at"]
            snapshot_time_source = "manifest"
            data_scope = "用户主动生成的本地 SQLite 静态快照中的已保存分析、事件成员与评论。"
            record_counts = self._snapshot["record_counts"]
        else:
            limitations = ["当前未提供可信快照清单；snapshot_created_at 为 null，未使用文件 mtime。"]
            snapshot_created_at = None
            snapshot_time_source = "unknown"
            data_scope = "用户明确指定的静态 SQLite 副本中的已保存分析、事件成员与评论。"
            record_counts = None
        with closing(self._connect()):
            pass
        try:
            with closing(self._connect(require_event_schema=True)):
                pass
        except AgentReadOnlyError as exc:
            if exc.code != "unsupported_database_schema":
                raise
            compatibility = "event_schema_missing"
            limitations.append("事件表缺失或不兼容；事件工具会明确拒绝调用。")
        return {
            "mcp_contract_version": 2,
            "service_version": SERVICE_VERSION,
            "snapshot_id": self.snapshot_id,
            "snapshot_created_at": snapshot_created_at,
            "snapshot_time_source": snapshot_time_source,
            "schema_compatibility": compatibility,
            "available_tools": list(AVAILABLE_TOOLS),
            "data_scope": data_scope,
            "record_counts": record_counts,
            "limitations": limitations,
        }

    def list_events(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        limit, offset = self._paging(limit, offset)
        try:
            with closing(self._connect(require_event_schema=True)) as db:
                total = db.execute("SELECT COUNT(id) FROM analysis_groups").fetchone()[0]
                rows = db.execute(
                    "SELECT page.id,page.name,page.created_at,page.updated_at,"
                    "COUNT(DISTINCT i.id) AS source_count,MIN(c.post_time) AS earliest_comment_at,MAX(c.post_time) AS latest_comment_at "
                    "FROM (SELECT id,name,created_at,updated_at FROM analysis_groups "
                    "ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?) page "
                    "LEFT JOIN analysis_group_items i ON i.group_id=page.id "
                    "LEFT JOIN comments c ON c.analysis_id=i.analysis_id "
                    "GROUP BY page.id,page.name,page.created_at,page.updated_at "
                    "ORDER BY page.updated_at DESC,page.id DESC",
                    (limit, offset),
                ).fetchall()
                values = [{
                    "event_id": int(row["id"]),
                    "name": str(row["name"] or "")[:200],
                    "source_count": int(row["source_count"] or 0),
                    "created_at": self._iso(row["created_at"]),
                    "updated_at": self._iso(row["updated_at"]),
                    "earliest_comment_at": self._iso(row["earliest_comment_at"]),
                    "latest_comment_at": self._iso(row["latest_comment_at"]),
                } for row in rows]
                return {
                    "mcp_contract_version": 2,
                    "snapshot_id": self.snapshot_id,
                    "items": values,
                    "total_count": int(total),
                    "has_more": offset + len(values) < total,
                    "limit": limit,
                    "offset": offset,
                    "limitations": self._snapshot_limitations(),
                }
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "读取舆情事件") from exc

    def get_event_overview(self, event_id: int, mode: str = "nlp") -> dict[str, Any]:
        event_id, mode = self._event_id(event_id), self._mode(mode)
        try:
            with closing(self._connect(require_event_schema=True)) as db:
                event = self._event(db, event_id)
                members = self._event_members(db, event_id)
                comments = annotate_exact_duplicates(self._event_comments(db, event_id), scope_field="source_analysis_id")
                coverage = self._event_llm_coverage(comments)
                eligible = [comment for comment in comments if mode != "llm" or self._v2_llm_ready([comment])]
                labels, field = (
                    (V2_EMOTION_LABELS, "sentiment_llm_label") if mode == "llm"
                    else (NLP_LABELS, "sentiment_label")
                )
                counts = {label: sum(comment[field] == label for comment in eligible) for label in labels}
                denominator = sum(counts.values())
                styles = (
                    {label: sum(comment["sentiment_llm_style"] == label for comment in eligible) for label in V2_STYLE_LABELS}
                    if mode == "llm" else None
                )
                source_rows = []
                raw_total, matched_total = len(comments), len(eligible)
                for member in members:
                    source_comments = [comment for comment in comments if comment["source_analysis_id"] == member["analysis_id"]]
                    source_matched = [comment for comment in eligible if comment["source_analysis_id"] == member["analysis_id"]]
                    source_covered = sum(self._v2_llm_ready([comment]) for comment in source_comments)
                    source_rows.append({
                        "analysis_id": member["analysis_id"], "bv": member["bv"],
                        "raw_count": len(source_comments), "matched_count": len(source_matched),
                        "raw_share": len(source_comments) / raw_total if raw_total else 0.0,
                        "matched_share": len(source_matched) / matched_total if matched_total else 0.0,
                        "llm_covered_count": source_covered, "llm_total_count": len(source_comments),
                        "llm_coverage": source_covered / len(source_comments) if source_comments else 1.0,
                    })
                times = [comment["post_time"] for comment in comments if comment.get("post_time")]
                limitations = self._event_limitations(members, comments, mode, denominator)
                return {
                    "mcp_contract_version": 2, "snapshot_id": self.snapshot_id,
                    "event_id": event_id, "name": str(event["name"] or "")[:200], "mode": mode,
                    "members": members, "source_distribution": source_rows,
                    "raw_comment_count": raw_total, "sentiment_distribution": counts,
                    "style_distribution": styles, "sentiment_denominator": denominator,
                    "llm_coverage": coverage,
                    "time_range": {"earliest": self._iso(min(times)) if times else None, "latest": self._iso(max(times)) if times else None},
                    "duplicate_statistics": build_duplicate_statistics(comments),
                    "data_complete": (
                        all(member["is_available"] for member in members)
                        and denominator == len(eligible)
                        and (mode != "llm" or coverage["fully_covered"])
                    ),
                    "limitations": limitations,
                }
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "读取舆情事件概览") from exc

    def search_event_comments(
        self,
        event_id: int,
        mode: str = "nlp",
        source_analysis_id: int | None = None,
        keyword: str | None = None,
        sentiment: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        event_id, mode = self._event_id(event_id), self._mode(mode)
        source_analysis_id = self._source_analysis_id(source_analysis_id)
        keyword, (limit, offset) = self._keyword(keyword), self._paging(limit, offset)
        allowed = set(V2_EMOTION_LABELS if mode == "llm" else NLP_LABELS)
        sentiment = str(sentiment or "").strip()
        if sentiment and sentiment not in allowed:
            raise AgentReadOnlyError("sentiment 与当前分析模式不匹配。", "invalid_sentiment")
        try:
            with closing(self._connect(require_event_schema=True)) as db:
                self._event(db, event_id)
                members = self._event_members(db, event_id)
                if source_analysis_id is not None and source_analysis_id not in {member["analysis_id"] for member in members}:
                    raise AgentReadOnlyError("指定来源不属于该舆情事件。", "source_not_in_event")
                comments = annotate_exact_duplicates(self._event_comments(db, event_id), scope_field="source_analysis_id")
                coverage = self._event_llm_coverage(comments)
                field = "sentiment_llm_label" if mode == "llm" else "sentiment_label"
                matched = [
                    comment for comment in comments
                    if (mode != "llm" or self._v2_llm_ready([comment]))
                    and (source_analysis_id is None or comment["source_analysis_id"] == source_analysis_id)
                    and (not keyword or keyword in comment["content"])
                    and (not sentiment or comment[field] == sentiment)
                ]
                output, used = [], 0
                for comment in matched[offset:offset + limit]:
                    content = comment["content"][:MAX_COMMENT_CHARS]
                    if used + len(content) > MAX_RESPONSE_CHARS:
                        break
                    used += len(content)
                    output.append({
                        "source_analysis_id": comment["source_analysis_id"], "source_bv": comment["source_bv"],
                        "content": content, "post_time": self._iso(comment["post_time"]),
                        "likes": max(0, int(comment["likes"] or 0)), "sentiment": comment[field] or "unclassified",
                        "style": comment["sentiment_llm_style"] if mode == "llm" else None,
                        "llm_schema_version": comment["sentiment_llm_schema_version"],
                        "is_exact_duplicate": bool(comment["is_exact_duplicate"]),
                        "has_context": bool(comment["root_rpid"] or comment["parent_rpid"]),
                    })
                limitations = ["评论正文单条最多返回 240 字符，单次响应正文合计最多 12000 字符。"]
                limitations.extend(self._event_limitations(members, comments, mode, sum(comment[field] in allowed for comment in matched)))
                return {
                    "mcp_contract_version": 2, "snapshot_id": self.snapshot_id,
                    "event_id": event_id, "mode": mode, "source_analysis_id": source_analysis_id,
                    "matched_count": len(matched), "returned_count": len(output),
                    "has_more": offset + len(output) < len(matched), "llm_coverage": coverage,
                    "comments": output, "limitations": limitations,
                }
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "检索舆情事件评论") from exc
