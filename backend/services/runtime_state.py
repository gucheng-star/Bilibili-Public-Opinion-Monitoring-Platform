"""Desktop lifecycle state shared by API routes and the Tauri shell."""

from __future__ import annotations

import threading
from collections import Counter
from contextlib import contextmanager

from models.database import Analysis, SessionLocal


ACTIVE_ANALYSIS_STATUSES = ("pending", "fetching", "analyzing")
_lock = threading.RLock()
_tasks: Counter[str] = Counter()


@contextmanager
def activity(name: str):
    with _lock:
        _tasks[name] += 1
    try:
        yield
    finally:
        with _lock:
            _tasks.subtract([name])
            if _tasks[name] <= 0:
                del _tasks[name]


def current_activity() -> dict:
    db = SessionLocal()
    try:
        analyses = [
            {"id": item.id, "status": item.status, "title": item.video_title or ""}
            for item in db.query(Analysis).filter(Analysis.status.in_(ACTIVE_ANALYSIS_STATUSES)).all()
        ]
    finally:
        db.close()
    with _lock:
        memory_tasks = dict(_tasks)
    return {
        "active": bool(analyses or memory_tasks),
        "analyses": analyses,
        "tasks": memory_tasks,
    }
