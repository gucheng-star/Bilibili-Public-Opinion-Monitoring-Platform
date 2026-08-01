"""Local settings storage for independent LLM tasks."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Any


DEFAULT_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "settings.json",
)
SETTINGS_FILE = os.environ.get("BILI_SETTINGS_PATH", DEFAULT_SETTINGS_FILE)
SETTINGS_LOCK = threading.RLock()
LLM_TASKS = ("sentiment", "summary")

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "bailian": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.6-plus",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    },
    "custom": {
        "base_url": "",
        "model": "",
    },
}


def _default_task_config(task: str) -> dict[str, str]:
    defaults = PROVIDER_DEFAULTS["bailian"]
    return {
        "provider": "bailian",
        "base_url": defaults["base_url"],
        "model": defaults["model"],
        "fallback_model": "qwen-turbo" if task == "sentiment" else "",
        "api_key": "",
    }


def _read_raw() -> dict[str, Any]:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_raw(data: dict[str, Any]) -> None:
    directory = os.path.dirname(SETTINGS_FILE)
    os.makedirs(directory, exist_ok=True)
    temporary = SETTINGS_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temporary, SETTINGS_FILE)


def _normalize_task_config(task: str, value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    provider = str(source.get("provider", "bailian")).strip().lower()
    if provider not in PROVIDER_DEFAULTS:
        provider = "custom"
    defaults = PROVIDER_DEFAULTS[provider]
    config = _default_task_config(task)
    config.update({
        "provider": provider,
        "base_url": str(source.get("base_url") or defaults["base_url"]).strip().rstrip("/"),
        "model": str(source.get("model") or defaults["model"]).strip(),
        "fallback_model": str(source.get("fallback_model", config["fallback_model"]) or "").strip(),
        "api_key": str(source.get("api_key", "") or "").strip(),
    })
    if provider != "bailian" and "fallback_model" not in source:
        config["fallback_model"] = ""
    return config


def load_settings() -> dict[str, Any]:
    """Load normalized settings and migrate the legacy single Bailian key."""
    with SETTINGS_LOCK:
        raw = _read_raw()
        llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
        legacy_key = str(raw.get("api_key", "") or "").strip()
        normalized_llm: dict[str, dict[str, str]] = {}
        for task in LLM_TASKS:
            task_source = deepcopy(llm.get(task, {})) if isinstance(llm, dict) else {}
            if task == "sentiment" and legacy_key and not task_source.get("api_key"):
                task_source["api_key"] = legacy_key
            normalized_llm[task] = _normalize_task_config(task, task_source)

        normalized = {
            key: value
            for key, value in raw.items()
            if key not in {"api_key", "llm", "has_api_key", "api_key_preview"}
        }
        normalized["analysis_mode"] = raw.get("analysis_mode", "nlp")
        normalized["llm"] = normalized_llm
        if normalized != raw:
            _write_raw(normalized)
        return normalized


def _mask_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "已配置" if api_key else ""
    return f"{api_key[:4]}****{api_key[-4:]}"


def public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return settings without exposing any full API key."""
    current = settings or load_settings()
    tasks: dict[str, dict[str, Any]] = {}
    for task in LLM_TASKS:
        config = current["llm"][task]
        api_key = config.get("api_key", "")
        tasks[task] = {
            "provider": config["provider"],
            "base_url": config["base_url"],
            "model": config["model"],
            "fallback_model": config.get("fallback_model", ""),
            "has_api_key": bool(api_key),
            "api_key_preview": _mask_key(api_key),
        }
    sentiment = tasks["sentiment"]
    return {
        "analysis_mode": current.get("analysis_mode", "nlp"),
        "llm": tasks,
        # Backward-compatible fields for older frontends.
        "has_api_key": sentiment["has_api_key"],
        "api_key_preview": sentiment["api_key_preview"],
    }


def _apply_task_patch(task: str, current: dict[str, str], patch: Any) -> dict[str, str]:
    if not isinstance(patch, dict):
        return current
    updated = deepcopy(current)
    provider = str(patch.get("provider", current["provider"])).strip().lower()
    if provider not in PROVIDER_DEFAULTS:
        raise ValueError("不支持的模型供应商")
    if provider != current["provider"]:
        defaults = PROVIDER_DEFAULTS[provider]
        updated.update({
            "provider": provider,
            "base_url": defaults["base_url"],
            "model": defaults["model"],
            "fallback_model": "",
            "api_key": "",
        })
    for field in ("base_url", "model", "fallback_model"):
        if field in patch:
            updated[field] = str(patch[field] or "").strip()
    if patch.get("clear_api_key"):
        updated["api_key"] = ""
    elif str(patch.get("api_key", "") or "").strip():
        updated["api_key"] = str(patch["api_key"]).strip()
    return _normalize_task_config(task, updated)


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial public settings update while retaining omitted secrets."""
    with SETTINGS_LOCK:
        current = load_settings()
        if "analysis_mode" in patch:
            mode = str(patch["analysis_mode"])
            if mode not in {"nlp", "llm"}:
                raise ValueError("无效的分析模式")
            current["analysis_mode"] = mode

        llm_patch = patch.get("llm")
        if isinstance(llm_patch, dict):
            for task in LLM_TASKS:
                if task in llm_patch:
                    current["llm"][task] = _apply_task_patch(
                        task, current["llm"][task], llm_patch[task]
                    )

        # Legacy writes continue to update the sentiment task.
        if str(patch.get("api_key", "") or "").strip():
            current["llm"]["sentiment"]["api_key"] = str(patch["api_key"]).strip()
        _write_raw(current)
        return current


def get_task_config(task: str, override: dict[str, Any] | None = None) -> dict[str, str]:
    if task not in LLM_TASKS:
        raise ValueError("未知的 LLM 任务")
    current = load_settings()["llm"][task]
    if override:
        current = _apply_task_patch(task, current, override)
    return current
