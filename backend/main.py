"""FastAPI application entry."""
import hmac
import json
import os
import sys
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
    init_db()
    _write_handshake()
    yield


app = FastAPI(title="B站舆论监测平台", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def require_local_token(request: Request, call_next):
    """Desktop API is private even if another local process probes its port."""
    if _desktop_mode() and request.method != "OPTIONS" and request.url.path != "/api/runtime/health":
        expected = os.environ["BILI_LOCAL_TOKEN"]
        supplied = request.headers.get("X-Bili-Local-Token", "")
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse({"detail": "本地桌面会话验证失败"}, status_code=401)
    return await call_next(request)


allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if _desktop_mode():
    allowed_origins.append("http://tauri.localhost")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
