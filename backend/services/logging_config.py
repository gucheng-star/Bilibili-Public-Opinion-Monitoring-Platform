"""Safe, opt-in JSONL logging for development diagnostics.

This module deliberately does not configure production logging.  A file handler
is installed only when ``BILI_DEV_LOGGING=1`` so importing it is side-effect
free for ordinary application and test runs.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


DEV_LOGGER_NAME = "bili.dev"
FRONTEND_LOGGER_NAME = "bili.dev.frontend"
MAX_LOG_LINE_BYTES = 32 * 1024
ROTATING_MAX_BYTES = 10 * 1024 * 1024
ROTATING_BACKUP_COUNT = 1

_WORKSPACE_DIR = Path(__file__).resolve().parents[2]
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "bili_dev_request_id", default=None
)

_ALLOWED_FIELDS = frozenset({
    "request_id", "analysis_id", "group_id", "task_type", "duration_ms",
    "error_type", "stack", "method", "route", "status_code",
    "batch_index", "count", "attempt", "stage",
})
_FRONTEND_ALLOWED_FIELDS = frozenset({
    "error_type", "stack", "breadcrumbs", "state", "count",
})
_SENSITIVE_KEY_PARTS = (
    "cookie", "sessdata", "bili_jct", "refresh_token", "refresh-token",
    "api_key", "api-key", "authorization", "bearer", "local_token",
    "local-token", "qrcode_key", "qrcode-key", "login_url", "login-url",
    "prompt", "raw_response", "raw-response", "comment_content",
    "comment-content", "comment_body", "comment-body", "request_body",
    "request-body", "response_body", "response-body", "headers", "messages",
    "username", "uid",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(cookie|set-cookie|sessdata|bili_jct|refresh[ _-]?token|api[ _-]?key|"
    r"local[ _-]?token|qrcode[ _-]?key|authorization)\b\s*[:=]\s*[^\s,;]+"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]{4,}")
_LOGIN_URL = re.compile(r"(?i)https?://[^\s]+(?:login|qrcode)[^\s]*")


def set_request_id(value: str | None) -> contextvars.Token[str | None]:
    """Set the request correlation id for this context and return its token."""
    return _request_id.set(_safe_text(value, 128) if value else None)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    """Restore a request id saved by :func:`set_request_id`."""
    _request_id.reset(token)


def get_request_id() -> str | None:
    """Return the current context-local request correlation id."""
    return _request_id.get()


def get_logger(name: str) -> logging.Logger:
    """Get a logger that participates in the safe development log stream."""
    component = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(name))[:128] or "backend"
    return logging.getLogger(f"{DEV_LOGGER_NAME}.{component}")


def dev_session_id() -> str:
    """Return the bounded development session identifier used in log records."""
    return _safe_text(os.getenv("BILI_DEV_SESSION_ID", "manual"), 128)


def configure_dev_logging() -> bool:
    """Configure the opt-in JSONL file handler; return whether enabled.

    Repeated calls reconcile this module's handlers instead of duplicating
    them.  All failures are swallowed because diagnostics must never disrupt
    the application being diagnosed.
    """
    logger = logging.getLogger(DEV_LOGGER_NAME)
    frontend_logger = logging.getLogger(FRONTEND_LOGGER_NAME)
    try:
        _remove_dev_handlers(logger)
        _remove_dev_handlers(frontend_logger)
        if os.getenv("BILI_DEV_LOGGING") != "1":
            return False

        log_dir = _log_directory()
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.setLevel(_configured_level())
        # Keep the application's existing console logging policy.  This module
        # owns only the JSONL file handler and must not add a second console
        # stream (or swallow a console handler configured by the app).
        logger.propagate = True

        formatter = _JsonlFormatter()
        file_handler = _AcknowledgingRotatingFileHandler(
            log_dir / "backend.log",
            maxBytes=ROTATING_MAX_BYTES,
            backupCount=ROTATING_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._bili_dev_handler = True  # type: ignore[attr-defined]
        logger.addHandler(file_handler)

        frontend_logger.setLevel(logging.INFO)
        # This handler is intentionally separate: frontend diagnostics must
        # never be copied into backend.log through the parent logger.
        frontend_logger.propagate = False
        frontend_handler = _AcknowledgingRotatingFileHandler(
            log_dir / "frontend.log",
            maxBytes=ROTATING_MAX_BYTES,
            backupCount=ROTATING_BACKUP_COUNT,
            encoding="utf-8",
        )
        frontend_handler.setFormatter(formatter)
        frontend_handler._bili_dev_handler = True  # type: ignore[attr-defined]
        frontend_logger.addHandler(frontend_handler)

        return dev_logging_ready()
    except Exception:
        _remove_dev_handlers(logger)
        _remove_dev_handlers(frontend_logger)
        return False


def log_event(
    logger: logging.Logger,
    level: int | str,
    event: str,
    message: str,
    **fields: Any,
) -> None:
    """Write one whitelist-only event without allowing logging failures through.

    Supported fields are the scalar identifiers, request summaries and task
    counters defined in ``_ALLOWED_FIELDS``.  Arbitrary nested ``details`` are
    deliberately rejected so private input cannot bypass event field policy. An
    ``exception`` argument is accepted as input only and becomes a sanitised
    ``error_type`` plus ``stack``; it is never serialised directly.
    """
    try:
        exception = fields.pop("exception", None)
        safe_fields = {
            key: _safe_field(key, value)
            for key, value in fields.items()
            if key in _ALLOWED_FIELDS
        }
        if "request_id" not in safe_fields and _request_id.get():
            safe_fields["request_id"] = _request_id.get()
        if isinstance(exception, BaseException):
            safe_fields.setdefault("error_type", type(exception).__name__)
            safe_fields.setdefault("stack", format_exception(exception))
        logger.log(
            _coerce_level(level),
            _safe_text(message, 4096),
            extra={
                "_bili_dev_event": _safe_text(event, 128),
                "_bili_dev_message": _safe_text(message, 4096),
                "_bili_dev_fields": safe_fields,
            },
        )
    except Exception:
        # Never turn a diagnostic failure into an application failure.
        return


def dev_logging_ready() -> bool:
    """Return whether both development log streams can confirm a flush.

    ``BILI_DEV_LOGGING=1`` only requests diagnostics.  The runtime endpoints
    must not advertise a usable session until both configured file handlers are
    present and their streams can still flush successfully.
    """
    try:
        backend = _configured_dev_handler(logging.getLogger(DEV_LOGGER_NAME))
        frontend = _configured_dev_handler(logging.getLogger(FRONTEND_LOGGER_NAME))
        return bool(backend and frontend and backend.is_ready() and frontend.is_ready())
    except Exception:
        return False


def log_frontend_event(
    event: str,
    *,
    error_type: object | None = None,
    stack: object | None = None,
    breadcrumbs: object | None = None,
    state: object | None = None,
    count: object | None = None,
) -> bool:
    """Write one server-projected browser error to ``frontend.log``.

    This deliberately has no ``details`` argument and does not use the
    backend event field whitelist.  The caller supplies a narrow projection,
    then this function applies a second defensive projection before writing.
    """
    return log_frontend_events([{
        "event": event,
        "error_type": error_type,
        "stack": stack,
        "breadcrumbs": breadcrumbs,
        "state": state,
        "count": count,
    }])


def log_frontend_events(events: list[dict[str, object]]) -> bool:
    """Persist a validated frontend batch and acknowledge only after flush.

    The endpoint passes its whole accepted batch here so all JSONL records are
    formatted before one locked write/flush attempt.  If that attempt fails the
    caller receives a retryable response instead of a false ``accepted`` ack.
    A storage failure after bytes reach the operating system remains inherently
    indeterminate, so no partial count is reported to the client.
    """
    try:
        handler = _configured_dev_handler(logging.getLogger(FRONTEND_LOGGER_NAME))
        if handler is None or not handler.is_ready():
            return False
        logger = logging.getLogger(FRONTEND_LOGGER_NAME)
        records = []
        for item in events:
            event = item.get("event")
            if not isinstance(event, str):
                return False
            fields = _safe_frontend_fields(
                error_type=item.get("error_type"),
                stack=item.get("stack"),
                breadcrumbs=item.get("breadcrumbs"),
                state=item.get("state"),
                count=item.get("count"),
            )
            message = _frontend_message(event)
            records.append(logger.makeRecord(
                logger.name, logging.ERROR, __file__, 0, message, (), None,
                extra={
                    "_bili_dev_event": _safe_text(event, 128),
                    "_bili_dev_message": message,
                    "_bili_frontend_fields": fields,
                },
            ))
        return bool(records) and handler.write_records(records)
    except Exception:
        return False


def _frontend_message(event: str) -> str:
    return {
        "window.error": "浏览器窗口错误",
        "window.unhandledrejection": "浏览器未处理的异步错误",
        "react.error_boundary": "React 渲染错误边界捕获异常",
        "api.request_failed": "前端 API 请求失败",
        "startup.failed": "前端启动失败",
        "queue.dropped": "前端诊断队列丢弃事件",
    }.get(event, "前端开发诊断错误")


def _safe_frontend_fields(
    *, error_type: object | None, stack: object | None,
    breadcrumbs: object | None, state: object | None, count: object | None,
) -> dict[str, Any]:
    """Keep the frontend-specific payload narrow even if called directly."""
    result: dict[str, Any] = {}
    if error_type is not None:
        result["error_type"] = _safe_text(error_type, 128)
    if stack is not None:
        result["stack"] = _sanitise_frontend_stack(stack)
    if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 100_000:
        result["count"] = count
    if isinstance(breadcrumbs, list):
        safe_breadcrumbs: list[dict[str, Any]] = []
        for item in breadcrumbs[:20]:
            if not isinstance(item, dict):
                continue
            safe_item: dict[str, Any] = {}
            for key in ("event", "path", "method", "action", "request_id", "analysis_mode", "poll_status"):
                value = item.get(key)
                if isinstance(value, str):
                    safe_item[key] = _safe_text(value, 160 if key == "path" else 128)
            for key in ("duration_ms", "analysis_id", "group_id"):
                value = item.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    safe_item[key] = value
            status = item.get("status")
            if isinstance(status, int) and not isinstance(status, bool):
                safe_item["status"] = status
            values = item.get("active_filter_fields")
            if isinstance(values, list):
                safe_item["active_filter_fields"] = [
                    _safe_text(value, 64) for value in values[:8] if isinstance(value, str)
                ]
            if safe_item:
                safe_breadcrumbs.append(safe_item)
        result["breadcrumbs"] = safe_breadcrumbs
    if isinstance(state, dict):
        safe_state: dict[str, Any] = {}
        for key in ("route", "view_type", "analysis_mode", "keyword_status"):
            value = state.get(key)
            if isinstance(value, str):
                safe_state[key] = _safe_text(value, 160 if key == "route" else 64)
        for key in ("analysis_id", "group_id"):
            value = state.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                safe_state[key] = value
        for key in ("loading", "reanalyzing"):
            value = state.get(key)
            if isinstance(value, bool):
                safe_state[key] = value
        values = state.get("active_filter_fields")
        if isinstance(values, list):
            safe_state["active_filter_fields"] = [
                _safe_text(value, 64) for value in values[:8] if isinstance(value, str)
            ]
        result["state"] = safe_state
    return result


_JS_FRAME = re.compile(r"^\s*at\s+(?:new\s+)?([A-Za-z_$][A-Za-z0-9_$.-]*|<anonymous>)")
_JS_COMPONENT = re.compile(r"^\s*(?:in|at)\s+([A-Z][A-Za-z0-9_$.-]{0,79})\b")


def _sanitise_frontend_stack(value: object) -> str:
    """Keep only browser frame/component names, never exception messages or locations."""
    if not isinstance(value, str):
        return ""
    frames: list[str] = []
    for line in value.splitlines():
        frame = _JS_FRAME.match(line)
        if frame:
            frames.append(f"at {frame.group(1)}")
        else:
            component = _JS_COMPONENT.match(line)
            if component:
                frames.append(f"component {component.group(1)}")
        if len(frames) == 40:
            break
    return _safe_text("\n".join(frames), 4096)


def format_exception(exception: BaseException) -> str:
    """Return frames without exception text, which may contain private input."""
    try:
        lines = ["Traceback (most recent call last):\n"]
        workspace = _WORKSPACE_DIR.resolve()
        for frame in traceback.extract_tb(exception.__traceback__):
            filename = "<external>"
            try:
                frame_path = Path(frame.filename)
                if frame_path.is_absolute():
                    resolved = frame_path.resolve()
                    if resolved.is_relative_to(workspace):
                        filename = f"<workspace>/{resolved.relative_to(workspace).as_posix()}"
            except (OSError, ValueError):
                pass
            lines.append(f'  File "{filename}", line {frame.lineno}, in {frame.name}\n')
        lines.append(f"{type(exception).__name__}: [message omitted]\n")
        stack = "".join(lines)
    except Exception:
        stack = f"<{type(exception).__name__}>"
    return _safe_text(stack, 12_000)


def _remove_dev_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_bili_dev_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def _log_directory() -> Path:
    dev_root = (_WORKSPACE_DIR / "logs" / "dev").resolve()
    configured = os.getenv("BILI_DEV_LOG_DIR")
    if configured:
        candidate = Path(configured).expanduser().resolve()
    else:
        session_id = _safe_text(os.getenv("BILI_DEV_SESSION_ID", "manual"), 128)
        candidate = (dev_root / session_id).resolve()
    if candidate == dev_root or not candidate.is_relative_to(dev_root):
        raise ValueError("BILI_DEV_LOG_DIR must be a session directory inside logs/dev")
    return candidate


def _configured_level() -> int:
    value = os.getenv("BILI_DEV_LOG_LEVEL", "INFO").upper()
    return getattr(logging, value, logging.INFO) if value in logging._nameToLevel else logging.INFO


def _coerce_level(level: int | str) -> int:
    if isinstance(level, int):
        return level
    return logging._nameToLevel.get(str(level).upper(), logging.INFO)


def _is_sensitive_key(key: str) -> bool:
    normalised = key.lower().replace(" ", "_")
    return any(part in normalised for part in _SENSITIVE_KEY_PARTS)


def _known_secret_values() -> tuple[str, ...]:
    values: list[str] = []
    for key, value in os.environ.items():
        if value and _is_sensitive_key(key) and len(value) >= 4:
            values.append(value)
    return tuple(values)


def _redact_text(value: str) -> str:
    result = value
    for secret in _known_secret_values():
        result = result.replace(secret, "[REDACTED]")
    result = _BEARER_VALUE.sub("Bearer [REDACTED]", result)
    result = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", result)
    return _LOGIN_URL.sub("[REDACTED_LOGIN_URL]", result)


def _safe_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        if isinstance(value, (int, float, bool)) or value is None:
            value = str(value)
        else:
            value = f"<{type(value).__name__}>"
    return _truncate_utf8(_redact_text(value), limit)


def _safe_field(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if key == "stack":
        return _safe_text(value, 12_000)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _safe_text(value, 1024) if isinstance(value, str) else value
    return f"<{type(value).__name__}>"


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "...<truncated>"
    allowed = max(0, max_bytes - len(suffix.encode("utf-8")))
    return encoded[:allowed].decode("utf-8", errors="ignore") + suffix


class _AcknowledgingRotatingFileHandler(RotatingFileHandler):
    """Rotating JSONL handler that can report whether a write reached ``flush``.

    Standard logging handlers intentionally swallow their own I/O failures.
    That is correct for ordinary application diagnostics, but the browser
    diagnostics endpoint needs an explicit acknowledgement before telling its
    client that queued data was accepted.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._bili_dev_write_failed = False

    def is_ready(self) -> bool:
        """Confirm the open stream can flush without emitting a log record."""
        self.acquire()
        try:
            if self._bili_dev_write_failed or self.stream is None or self.stream.closed:
                return False
            self.flush()
            return True
        except Exception:
            self._bili_dev_write_failed = True
            return False
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        # ``logging`` ignores handler return values.  Keep its normal
        # fire-and-forget behaviour for backend events while remembering a
        # failure so the browser endpoint can stop issuing false acknowledgements.
        self.write_records([record])

    def write_records(self, records: list[logging.LogRecord]) -> bool:
        """Format and flush one batch under a single handler lock."""
        self.acquire()
        try:
            if self._bili_dev_write_failed:
                return False
            lines = [self.format(record) for record in records]
            payload = "\n".join(lines) + "\n"
            if self.stream is None:
                self.stream = self._open()
            if self.maxBytes > 0:
                self.stream.seek(0, 2)
                if self.stream.tell() + len(payload.encode(self.encoding or "utf-8")) >= self.maxBytes:
                    self.doRollover()
            self.stream.write(payload)
            self.flush()
            return True
        except Exception:
            self._bili_dev_write_failed = True
            return False
        finally:
            self.release()


def _configured_dev_handler(logger: logging.Logger) -> _AcknowledgingRotatingFileHandler | None:
    """Return this module's sole acknowledgement-capable handler, if healthy."""
    handlers = [
        handler for handler in logger.handlers
        if getattr(handler, "_bili_dev_handler", False)
        and isinstance(handler, _AcknowledgingRotatingFileHandler)
    ]
    return handlers[0] if len(handlers) == 1 else None


class _JsonlFormatter(logging.Formatter):
    """Convert all records in the development logger hierarchy to safe JSONL."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            component = record.name.removeprefix(f"{DEV_LOGGER_NAME}.")
            payload: dict[str, Any] = {
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "component": _safe_text(component, 128),
                "event": _safe_text(getattr(record, "_bili_dev_event", "log_message"), 128),
                "dev_session_id": _safe_text(os.getenv("BILI_DEV_SESSION_ID", "manual"), 128),
                "message": _safe_text(getattr(record, "_bili_dev_message", record.getMessage()), 4096),
            }
            for key, value in getattr(record, "_bili_dev_fields", {}).items():
                if key in _ALLOWED_FIELDS:
                    payload[key] = _safe_field(key, value)
            for key, value in getattr(record, "_bili_frontend_fields", {}).items():
                if key in _FRONTEND_ALLOWED_FIELDS:
                    payload[key] = value
            return _fit_json_line(payload)
        except Exception:
            return '{"timestamp":"","level":"ERROR","component":"logging","event":"format_failed","dev_session_id":"","message":"[REDACTED]"}'


def _fit_json_line(payload: dict[str, Any]) -> str:
    def encode() -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    try:
        line = encode()
    except (TypeError, ValueError):
        payload = {"timestamp": "", "level": "ERROR", "component": "logging", "event": "serialization_failed", "dev_session_id": "", "message": "[REDACTED]"}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(line.encode("utf-8")) <= MAX_LOG_LINE_BYTES:
        return line
    payload["truncated"] = True
    payload["stack"] = _truncate_utf8(str(payload.get("stack", "")), 4096)
    payload["message"] = _truncate_utf8(str(payload.get("message", "")), 1024)
    line = encode()
    if len(line.encode("utf-8")) <= MAX_LOG_LINE_BYTES:
        return line
    payload["message"] = "<truncated>"
    payload.pop("stack", None)
    return encode()
