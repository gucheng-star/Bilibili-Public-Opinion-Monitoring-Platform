"""Small local-only lifecycle API consumed by the desktop shell."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.auth import credential_reentry_required
from services.logging_config import dev_logging_ready, dev_session_id, log_frontend_events
from services.runtime_state import current_activity


router = APIRouter(prefix="/api/runtime", tags=["runtime"])

_DEV_ORIGINS = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})
_MAX_DIAGNOSTIC_BODY_BYTES = 64 * 1024
_MAX_EVENT_BYTES = 8 * 1024
_ERROR_EVENTS = frozenset({
    "window.error",
    "window.unhandledrejection",
    "react.error_boundary",
    "api.request_failed",
    "startup.failed",
})
_BREADCRUMB_EVENTS = frozenset({
    "route.changed",
    "analysis.selected",
    "group.selected",
    "analysis.mode_changed",
    "filter.changed",
    "api.request_started",
    "api.request_completed",
    "api.request_failed",
    "task.poll_status_changed",
    "component.action_started",
    "component.action_completed",
})
_FILTER_FIELDS = frozenset({
    "gender", "date_range", "region", "sentiment", "duplicate_mode",
    "source_analysis_id",
})
_IDENTIFIER_PATTERN = r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$"
_ACTION_PATTERN = r"^[a-z][a-z0-9_.-]{0,79}$"
_REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{1,80}$"
_TASK_STATUS_PATTERN = r"^[a-z_]{1,40}$"
_SAFE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9/:_.-]{0,159}$")


class _DiagnosticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Breadcrumb(_DiagnosticModel):
    event: str = Field(min_length=1, max_length=64)
    path: str | None = Field(default=None, max_length=160)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    status: int | None = Field(default=None, ge=100, le=599)
    poll_status: str | None = Field(default=None, pattern=_TASK_STATUS_PATTERN)
    duration_ms: float | None = Field(default=None, ge=0, le=120_000)
    request_id: str | None = Field(default=None, pattern=_REQUEST_ID_PATTERN)
    analysis_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)
    analysis_mode: Literal["nlp", "llm"] | None = None
    active_filter_fields: list[str] | None = Field(default=None, max_length=8)
    action: str | None = Field(default=None, pattern=_ACTION_PATTERN)

    @field_validator("path")
    @classmethod
    def normalise_path(cls, value: str | None) -> str | None:
        return _normalise_safe_path(value)

class _DiagnosticState(_DiagnosticModel):
    route: str | None = Field(default=None, max_length=160)
    view_type: Literal["single", "group", "settings"] | None = None
    analysis_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)
    analysis_mode: Literal["nlp", "llm"] | None = None
    loading: bool | None = None
    reanalyzing: bool | None = None
    keyword_status: Literal["ready", "loading", "error"] | None = None
    active_filter_fields: list[str] | None = Field(default=None, max_length=8)

    @field_validator("route")
    @classmethod
    def normalise_route(cls, value: str | None) -> str | None:
        return _normalise_safe_path(value)


class _DiagnosticEvent(_DiagnosticModel):
    event: str = Field(min_length=1, max_length=64)
    error_type: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    stack: str | None = Field(default=None, max_length=12_000)
    breadcrumbs: list[_Breadcrumb] | None = Field(default=None, max_length=20)
    state: _DiagnosticState | None = None


class _DiagnosticBatch(_DiagnosticModel):
    session_id: str = Field(min_length=1, max_length=128)
    events: list[_DiagnosticEvent] = Field(min_length=1, max_length=20)
    dropped_count: int = Field(default=0, ge=0, le=100_000)


def _dev_diagnostics_enabled() -> bool:
    return os.getenv("BILI_DEV_LOGGING") == "1"


def _require_dev_diagnostics(request: Request, *, allow_referer: bool) -> None:
    if not _dev_diagnostics_enabled():
        raise HTTPException(status_code=404, detail="未找到")
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="仅允许本机开发诊断请求")
    origin = request.headers.get("origin")
    if origin in _DEV_ORIGINS:
        return
    if allow_referer and origin is None and _referer_origin(request.headers.get("referer")) in _DEV_ORIGINS:
        return
    raise HTTPException(status_code=403, detail="开发来源未获允许")


def _is_loopback(host: str | None) -> bool:
    try:
        return bool(host) and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _referer_origin(referer: str | None) -> str | None:
    if not referer:
        return None
    try:
        value = urlsplit(referer)
        port = f":{value.port}" if value.port else ""
    except ValueError:
        return None
    if value.username or value.password or value.scheme not in {"http", "https"}:
        return None
    if not value.hostname:
        return None
    return f"{value.scheme}://{value.hostname}{port}"


def _normalise_safe_path(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.isascii():
        raise ValueError("diagnostic path must be ASCII")
    path = value.split("?", 1)[0].split("#", 1)[0]
    if not _SAFE_PATH_PATTERN.fullmatch(path):
        raise ValueError("diagnostic path is not a route")
    return path


def _filter_fields(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [value for value in values if value in _FILTER_FIELDS]


def _project_breadcrumb(item: _Breadcrumb) -> dict[str, object]:
    if item.event not in _BREADCRUMB_EVENTS:
        return {"event": "unknown"}
    result: dict[str, object] = {"event": item.event}
    if item.event == "route.changed" and item.path:
        result["path"] = item.path
    if item.event == "analysis.selected" and item.analysis_id is not None:
        result["analysis_id"] = item.analysis_id
    if item.event == "group.selected" and item.group_id is not None:
        result["group_id"] = item.group_id
    if item.event == "analysis.mode_changed" and item.analysis_mode:
        result["analysis_mode"] = item.analysis_mode
    if item.event == "filter.changed":
        fields = _filter_fields(item.active_filter_fields)
        if fields is not None:
            result["active_filter_fields"] = fields
    if item.event.startswith("api.request_"):
        if item.method:
            result["method"] = item.method
        if item.path:
            result["path"] = item.path
        if item.status is not None:
            result["status"] = item.status
        if item.duration_ms is not None:
            result["duration_ms"] = item.duration_ms
        if item.request_id:
            result["request_id"] = item.request_id
    if item.event == "task.poll_status_changed" and item.poll_status:
        result["poll_status"] = item.poll_status
    if item.action and item.event.startswith("component.action_"):
        result["action"] = item.action
    return result


def _project_state(value: _DiagnosticState | None) -> dict[str, object] | None:
    if value is None:
        return None
    result: dict[str, object] = {}
    route = value.route
    if route:
        result["route"] = route
    for key in ("view_type", "analysis_id", "group_id", "analysis_mode", "loading", "reanalyzing", "keyword_status"):
        item = getattr(value, key)
        if item is not None:
            result[key] = item
    fields = _filter_fields(value.active_filter_fields)
    if fields is not None:
        result["active_filter_fields"] = fields
    return result


@router.get("/dev-diagnostics/session")
async def dev_diagnostics_session(request: Request):
    _require_dev_diagnostics(request, allow_referer=True)
    if not dev_logging_ready():
        raise HTTPException(status_code=503, detail="开发诊断日志暂不可用，请稍后重试")
    return {"enabled": True, "session_id": dev_session_id()}


@router.post("/dev-diagnostics/events")
async def dev_diagnostics_events(request: Request):
    _require_dev_diagnostics(request, allow_referer=False)
    if not dev_logging_ready():
        raise HTTPException(status_code=503, detail="开发诊断日志暂不可用，请稍后重试")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _MAX_DIAGNOSTIC_BODY_BYTES:
        raise HTTPException(status_code=413, detail="诊断请求过大")
    raw_body = await _read_limited_body(request)
    try:
        batch = _DiagnosticBatch.model_validate(json.loads(raw_body))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="诊断事件格式无效") from exc
    if batch.session_id != dev_session_id():
        raise HTTPException(status_code=403, detail="开发会话不匹配")
    for item in batch.events:
        if item.event not in _ERROR_EVENTS:
            raise HTTPException(status_code=422, detail="不支持的诊断事件")
        if any(entry.event not in _BREADCRUMB_EVENTS for entry in item.breadcrumbs or []):
            raise HTTPException(status_code=422, detail="不支持的轨迹事件")
        if len(json.dumps(item.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > _MAX_EVENT_BYTES:
            raise HTTPException(status_code=413, detail="单条诊断事件过大")
    events_to_write: list[dict[str, object]] = []
    if batch.dropped_count:
        events_to_write.append({"event": "queue.dropped", "count": batch.dropped_count})
    for item in batch.events:
        events_to_write.append({
            "event": item.event,
            "error_type": item.error_type,
            "stack": item.stack,
            "breadcrumbs": [_project_breadcrumb(entry) for entry in item.breadcrumbs or []],
            "state": _project_state(item.state),
        })
    if not log_frontend_events(events_to_write):
        raise HTTPException(status_code=503, detail="开发诊断日志写入失败，请稍后重试")
    return {"accepted": len(batch.events)}


async def _read_limited_body(request: Request) -> bytes:
    """Accumulate an ASGI body only up to the diagnostic endpoint limit."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_DIAGNOSTIC_BODY_BYTES:
            raise HTTPException(status_code=413, detail="诊断请求过大")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/health")
def health():
    """Unauthenticated only so the local shell can wait for first boot.

    The backend is bound to loopback in desktop mode; no user data or secrets
    are returned from this endpoint.
    """
    return {
        "ok": True,
        "version": os.getenv("BILI_APP_VERSION", "0.1.1-beta"),
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
