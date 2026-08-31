"""Strictly read-only domain access for the local Agent MCP PoC."""
from __future__ import annotations
import ctypes
import os
import sqlite3
import stat
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from services.comment_quality import annotate_exact_duplicates, build_duplicate_statistics
from services.region import analyze_region

NLP_LABELS = ("positive", "negative", "neutral")
LLM_LABELS = ("neutral", "joy", "support", "anticipation", "surprise", "anger", "sadness", "concern", "disgust", "sarcasm")
MAX_COMMENT_CHARS = 240
MAX_RESPONSE_CHARS = 12_000
MAX_OFFSET = 100_000
MAX_ANALYSIS_COMMENTS = 10_000
QUERY_TIMEOUT_SECONDS = 5.0
QUERY_PROGRESS_STEPS = 1_000
SUPPORTED_SCHEMA_SIGNATURE = 1

_WINDOWS_DRIVE_FIXED = 3
_WINDOWS_DRIVE_REMOVABLE = 2
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

ALLOWED_READ_COLUMNS = {
    "analyses": {"id", "bv", "video_title", "status", "mode", "total_comments", "created_at"},
    "comments": {
        "id", "analysis_id", "content", "likes", "ip_location", "post_time",
        "sentiment_label", "sentiment_llm_label", "root_rpid", "parent_rpid",
    },
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
        "root_rpid": {"INTEGER"},
        "parent_rpid": {"INTEGER"},
    },
}


class AgentReadOnlyError(Exception):
    def __init__(self, message: str, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.message, self.code = message, code


class ReadOnlyService:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = self._validate_database_path(database_path)

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

    def _connect(self) -> sqlite3.Connection:
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
        for table, required_columns in REQUIRED_SCHEMA.items():
            table_row = connection.execute(
                "SELECT type FROM sqlite_schema WHERE name=? COLLATE BINARY",
                (table,),
            ).fetchone()
            if table_row is None or table_row["type"] != "table":
                raise AgentReadOnlyError(
                    f"数据库不符合支持的只读 Schema v{SUPPORTED_SCHEMA_SIGNATURE}。",
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
                    f"数据库不符合支持的只读 Schema v{SUPPORTED_SCHEMA_SIGNATURE}。",
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
            return sqlite3.SQLITE_OK if columns is not None and (argument2 or "") in columns else sqlite3.SQLITE_DENY
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
                "sentiment_llm_label": row["sentiment_llm_label"] or "", "root_rpid": row["root_rpid"],
                "parent_rpid": row["parent_rpid"]}

    @staticmethod
    def _analysis(connection: sqlite3.Connection, analysis_id: int) -> sqlite3.Row:
        row = connection.execute("SELECT id,bv,video_title,status,mode,total_comments,created_at FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if row is None:
            raise AgentReadOnlyError("未找到指定的分析记录。", "analysis_not_found")
        if row["status"] != "done":
            raise AgentReadOnlyError(f"该分析尚未完成（当前状态：{row['status'] or '未知'}）。", "analysis_not_done")
        return row

    def _comments(self, connection: sqlite3.Connection, analysis_id: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT id,content,likes,ip_location,post_time,sentiment_label,"
            "sentiment_llm_label,root_rpid,parent_rpid FROM comments "
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
    def _llm_ready(comments: list[dict[str, Any]]) -> bool:
        return bool(comments) and all(item["sentiment_llm_label"] in LLM_LABELS for item in comments)

    def list_analyses(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        limit, offset = self._paging(limit, offset)
        try:
            with closing(self._connect()) as db:
                total = db.execute("SELECT COUNT(*) FROM analyses WHERE status='done'").fetchone()[0]
                placeholders = ",".join("?" for _ in LLM_LABELS)
                rows = db.execute(
                    "SELECT page.id,page.bv,page.video_title,page.created_at,page.status,page.mode,"
                    "page.total_comments,"
                    "(SELECT COUNT(*) FROM comments c WHERE c.analysis_id=page.id) AS stored_count,"
                    "EXISTS(SELECT 1 FROM comments c WHERE c.analysis_id=page.id) AS has_comments,"
                    "NOT EXISTS(SELECT 1 FROM comments c WHERE c.analysis_id=page.id AND "
                    f"(c.sentiment_llm_label IS NULL OR c.sentiment_llm_label NOT IN ({placeholders}))) "
                    "AS labels_valid FROM (SELECT id,bv,video_title,created_at,status,mode,total_comments "
                    "FROM analyses WHERE status='done' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?) page",
                    (*LLM_LABELS, limit, offset),
                ).fetchall()
                values = []
                for row in rows:
                    values.append({"analysis_id": row["id"], "bv": row["bv"], "video_title": row["video_title"] or "",
                                   "created_at": self._iso(row["created_at"]), "status": row["status"],
                                   "analysis_mode": row["mode"] or "nlp", "total_comments": row["stored_count"],
                                   "has_llm_labels": bool(row["has_comments"] and row["labels_valid"])})
                return {
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
                ready = self._llm_ready(comments)
                if mode == "llm" and not ready:
                    raise AgentReadOnlyError("该分析尚未完成大模型情绪分析。", "llm_not_ready")
                labels, field = (LLM_LABELS, "sentiment_llm_label") if mode == "llm" else (NLP_LABELS, "sentiment_label")
                counts = {label: sum(item[field] == label for item in comments) for label in labels}
                sentiment_denominator = sum(counts.values())
                times = [item["post_time"] for item in comments if item.get("post_time")]
                annotated = annotate_exact_duplicates(comments)
                actual, declared = len(comments), row["total_comments"] or 0
                limitations = ["地域占比的分母是有地域信息的评论数。"]
                if actual != declared:
                    limitations.append("分析记录声明的评论数与实际保存行数不一致。")
                if sentiment_denominator != actual:
                    limitations.append("部分评论缺少当前模式的合法情绪标签，未计入情绪分母。")
                return {"analysis_id": row["id"], "bv": row["bv"], "video_title": row["video_title"] or "",
                        "created_at": self._iso(row["created_at"]), "status": row["status"],
                        "analysis_mode": row["mode"] if row["mode"] in {"nlp", "llm"} else "nlp", "mode": mode,
                        "declared_total_comments": declared, "stored_comment_count": actual,
                        "sentiment_distribution": counts, "sentiment_denominator": sentiment_denominator,
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
        allowed = set(LLM_LABELS if mode == "llm" else NLP_LABELS)
        sentiment = str(sentiment or "").strip()
        if sentiment and sentiment not in allowed:
            raise AgentReadOnlyError("sentiment 与当前分析模式不匹配。", "invalid_sentiment")
        try:
            with closing(self._connect()) as db:
                self._analysis(db, analysis_id)
                all_comments = annotate_exact_duplicates(self._comments(db, analysis_id))
                if mode == "llm" and not self._llm_ready(all_comments):
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
                                   "sentiment": item[field] or "unclassified", "is_exact_duplicate": bool(item["is_exact_duplicate"]),
                                   "has_context": bool(item["root_rpid"] or item["parent_rpid"])})
                return {"analysis_id": analysis_id, "mode": mode, "matched_count": len(matched),
                        "returned_count": len(output), "has_more": offset + len(output) < len(matched),
                        "comments": output,
                        "limitations": ["评论正文单条最多返回 240 字符，单次响应正文合计最多 12000 字符。"]}
        except AgentReadOnlyError:
            raise
        except sqlite3.Error as exc:
            raise self._database_read_error(exc, "检索评论") from exc
