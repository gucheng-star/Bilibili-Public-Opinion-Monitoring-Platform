"""FastAPI application entry."""
import hmac
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(__file__))
from api.auth_routes import router as auth_router
from api.group_routes import router as group_router
from api.routes import router
from api.runtime_routes import router as runtime_router
from api.settings_routes import router as settings_router
from api.summary_routes import router as summary_router
from models.database import init_db
from services.runtime_paths import handshake_path
from services.logging_config import (
    configure_dev_logging,
    get_logger,
    log_event,
    reset_request_id,
    set_request_id,
)


logger = get_logger("app")


def _desktop_mode() -> bool:
    return os.getenv("BILI_DESKTOP_MODE") == "1"


def _write_handshake() -> None:
    path = handshake_path()
    port = os.getenv("BILI_BOUND_PORT")
    if not path or not port:
        return
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps({
        "schema": 1,
        "port": int(port),
        "pid": os.getpid(),
        "version": os.getenv("BILI_APP_VERSION", "0.1.0"),
    }), encoding="utf-8")
    os.replace(temporary, path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_enabled = configure_dev_logging()
    if logging_enabled:
        log_event(logger, "INFO", "backend.started", "后端开发诊断已启用")
    init_db()
    _write_handshake()
    yield


app = FastAPI(title="B站舆论监测平台", version="0.1.0", lifespan=lifespan)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "<unmatched>"


def _quiet_successful_request(path: str, status_code: int) -> bool:
    return status_code < 400 and (
        path.startswith("/api/status/")
        or path in {"/api/runtime/health", "/api/runtime/activity"}
    )


def _is_dev_diagnostics_path(path: str) -> bool:
    return path.startswith("/api/runtime/dev-diagnostics/")


async def record_request_diagnostics(request: Request, call_next):
    """Record a bounded request summary without headers, query strings, or bodies."""
    request_id = secrets.token_hex(6)
    token = set_request_id(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        route = _route_template(request)
        if not _is_dev_diagnostics_path(request.url.path):
            level = "DEBUG" if _quiet_successful_request(route, response.status_code) else "INFO"
            log_event(
                logger, level, "api.request_completed", "API 请求已完成",
                request_id=request_id, method=request.method, route=route,
                status_code=response.status_code, duration_ms=duration_ms,
            )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        if not _is_dev_diagnostics_path(request.url.path):
            log_event(
                logger, "ERROR", "api.request_failed", "API 请求发生未处理异常",
                request_id=request_id, method=request.method, route=_route_template(request),
                duration_ms=round((time.perf_counter() - started) * 1000, 2), exception=exc,
            )
        return JSONResponse(
            {"detail": "服务器内部错误"}, status_code=500,
            headers={"X-Request-ID": request_id},
        )
    finally:
        reset_request_id(token)


@app.middleware("http")
async def require_local_token(request: Request, call_next):
    """Desktop API is private even if another local process probes its port."""
    if _desktop_mode() and request.method != "OPTIONS" and request.url.path != "/api/runtime/health":
        expected = os.environ["BILI_LOCAL_TOKEN"]
        supplied = request.headers.get("X-Bili-Local-Token", "")
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse({"detail": "本地桌面会话验证失败"}, status_code=401)
    return await call_next(request)


# Register diagnostics after token validation so Starlette places diagnostics
# outside it; rejected desktop requests still receive a correlation ID.
app.middleware("http")(record_request_diagnostics)


allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if _desktop_mode():
    allowed_origins.append("http://tauri.localhost")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.include_router(settings_router)
app.include_router(summary_router)
app.include_router(group_router)
app.include_router(router)
app.include_router(auth_router)
app.include_router(runtime_router)

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dir) and not _desktop_mode():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    desktop = _desktop_mode()
    uvicorn.run("main:app", host="127.0.0.1" if desktop else "0.0.0.0", port=int(os.getenv("BILI_PORT", "8000")))
