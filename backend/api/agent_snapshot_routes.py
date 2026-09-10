"""User-triggered Agent snapshot endpoint for the local desktop backend."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.agent_snapshots import AgentSnapshotError, AgentSnapshotService


router = APIRouter(prefix="/api", tags=["agent-snapshots"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotRecordCounts(_StrictModel):
    analyses: int = Field(ge=0)
    comments: int = Field(ge=0)
    events: int = Field(ge=0)


class AgentSnapshotResponse(_StrictModel):
    snapshot_id: str
    created_at: str
    database_path: str
    manifest_path: str
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    application_version: str
    mcp_contract_version: int
    record_counts: SnapshotRecordCounts


@router.post("/agent-snapshots", response_model=AgentSnapshotResponse)
def create_agent_snapshot() -> dict[str, object]:
    if os.getenv("BILI_DESKTOP_MODE") != "1":
        raise HTTPException(status_code=403, detail="Agent 快照只能由已认证的桌面应用生成。")
    try:
        return AgentSnapshotService().create()
    except AgentSnapshotError as exc:
        raise HTTPException(status_code=503, detail="无法生成 Agent 快照，请稍后重试。") from exc
