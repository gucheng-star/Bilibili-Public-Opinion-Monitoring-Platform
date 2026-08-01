"""Provider-aware client for OpenAI-compatible chat completion APIs."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import httpx


class LLMRequestError(RuntimeError):
    """Safe, user-facing LLM request error."""


def validate_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Base URL 必须是公网 HTTPS 地址")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("Base URL 不允许指向本机或私网")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("Base URL 不允许指向本机或私网")
    return value


async def _ensure_public_hostname(base_url: str) -> None:
    hostname = urlparse(base_url).hostname
    if not hostname:
        raise ValueError("Base URL 缺少主机名")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise LLMRequestError("无法解析模型服务地址，请检查 Base URL") from exc
    for entry in addresses:
        address_text = entry[4][0].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            continue
        if not address.is_global:
            raise LLMRequestError("模型服务地址解析到了本机或私网，已拒绝请求")


def _chat_url(base_url: str) -> str:
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"


def _models_url(base_url: str) -> str:
    chat_suffix = "/chat/completions"
    root = base_url[:-len(chat_suffix)] if base_url.endswith(chat_suffix) else base_url
    return root if root.endswith("/models") else f"{root}/models"


def _status_error(status: int) -> LLMRequestError:
    if status in {401, 403}:
        message = "API Key 无效或没有模型权限"
    elif status == 404:
        message = "模型服务不支持该接口，请检查 Base URL"
    elif status == 429:
        message = "模型服务请求过于频繁，请稍后重试"
    elif status >= 500:
        message = "模型服务暂时不可用"
    else:
        message = f"模型服务拒绝了请求（HTTP {status}）"
    return LLMRequestError(message)


async def list_models(
    config: dict[str, str],
    *,
    check_dns: bool = True,
) -> list[str]:
    """Return model IDs exposed by an OpenAI-compatible ``/models`` endpoint."""
    api_key = config.get("api_key", "").strip()
    if not api_key:
        raise ValueError("尚未配置 API Key")
    base_url = validate_base_url(config.get("base_url", ""))
    if check_dns:
        await _ensure_public_hostname(base_url)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                _models_url(base_url),
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if 300 <= response.status_code < 400:
            raise LLMRequestError("模型服务返回重定向，已拒绝跟随")
        response.raise_for_status()
        data = response.json()
        entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise LLMRequestError("模型列表返回格式不完整")
        models = sorted({
            item["id"].strip()
            for item in entries
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        })
        if not models:
            raise LLMRequestError("模型服务没有返回可用模型")
        return models
    except LLMRequestError:
        raise
    except httpx.TimeoutException as exc:
        raise LLMRequestError("模型服务响应超时") from exc
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc.response.status_code) from exc
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise LLMRequestError("无法连接模型服务，请检查接口配置") from exc


def _extract_content(data: Any) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("模型返回格式不完整") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMRequestError("模型返回了空内容")
    return content.strip()


def parse_json_content(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else value[3:]
        if value.endswith("```"):
            value = value[:-3]
        value = value.strip()
        if value.lower().startswith("json"):
            value = value[4:].strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LLMRequestError("模型未返回有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMRequestError("模型 JSON 返回值必须是对象")
    return parsed


async def chat_completion(
    config: dict[str, str],
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 400,
    retries: int = 1,
    check_dns: bool = True,
) -> tuple[str, str]:
    """Return response content and the model that succeeded."""
    api_key = config.get("api_key", "").strip()
    model = config.get("model", "").strip()
    if not api_key:
        raise ValueError("尚未配置 API Key")
    if not model:
        raise ValueError("尚未配置模型名称")
    base_url = validate_base_url(config.get("base_url", ""))
    if check_dns:
        await _ensure_public_hostname(base_url)

    models = [model]
    fallback = config.get("fallback_model", "").strip()
    if fallback and fallback != model:
        models.append(fallback)

    last_error: Exception | None = None
    for candidate in models:
        for attempt in range(retries + 1):
            payload: dict[str, Any] = {
                "model": candidate,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if config.get("provider") == "deepseek":
                # DeepSeek V4 enables thinking by default. Short structured
                # tasks can otherwise spend the entire token budget in
                # reasoning_content and return an empty final content field.
                payload["thinking"] = {"type": "disabled"}
            elif config.get("provider") == "bailian":
                payload["enable_thinking"] = False
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0),
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        _chat_url(base_url),
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                if 300 <= response.status_code < 400:
                    raise LLMRequestError("模型服务返回重定向，已拒绝跟随")
                response.raise_for_status()
                return _extract_content(response.json()), candidate
            except LLMRequestError as exc:
                last_error = exc
            except httpx.TimeoutException as exc:
                last_error = LLMRequestError("模型服务响应超时")
                last_error.__cause__ = exc
            except httpx.HTTPStatusError as exc:
                last_error = _status_error(exc.response.status_code)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = LLMRequestError("无法连接模型服务，请检查接口配置")
                last_error.__cause__ = exc
            if attempt < retries:
                await asyncio.sleep(attempt + 1)
    raise last_error or LLMRequestError("模型请求失败")


async def chat_completion_json(
    config: dict[str, str],
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 400,
) -> tuple[dict[str, Any], str]:
    content, model = await chat_completion(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_json_content(content), model
