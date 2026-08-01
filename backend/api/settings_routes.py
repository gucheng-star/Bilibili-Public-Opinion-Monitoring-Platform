"""Local settings and LLM connection test routes."""

from time import perf_counter

from fastapi import APIRouter, HTTPException

from services.llm_client import LLMRequestError, chat_completion, list_models
from services.sentiment_llm import test_sentiment_connection
from services.settings_store import (
    get_task_config,
    public_settings,
    update_settings as save_settings,
)

router = APIRouter(prefix="/api")


@router.get("/settings")
async def get_settings():
    return public_settings()


@router.put("/settings")
async def update_settings(req: dict):
    try:
        return public_settings(save_settings(req))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/settings/test-llm")
async def test_llm(req: dict):
    task = str(req.get("task", ""))
    override = req.get("config")
    try:
        config = get_task_config(task, override if isinstance(override, dict) else None)
        started = perf_counter()
        if task == "sentiment":
            tested_items = await test_sentiment_connection(config)
            content = f"情感分析链路正常（{tested_items} 条测试评论）"
            model = config["model"]
        else:
            content, model = await chat_completion(
                config,
                [
                    {"role": "system", "content": "你是连接测试助手。"},
                    {"role": "user", "content": "只回复：连接成功"},
                ],
                temperature=0,
                max_tokens=16,
                retries=0,
            )
        return {
            "ok": True,
            "provider": config["provider"],
            "model": model,
            "latency_ms": round((perf_counter() - started) * 1000),
            "message": content[:40],
        }
    except (ValueError, LLMRequestError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/settings/models")
async def get_llm_models(req: dict):
    task = str(req.get("task", ""))
    override = req.get("config")
    try:
        config = get_task_config(task, override if isinstance(override, dict) else None)
        models = await list_models(config)
        return {
            "ok": True,
            "provider": config["provider"],
            "models": models,
        }
    except (ValueError, LLMRequestError) as exc:
        raise HTTPException(400, str(exc)) from exc
