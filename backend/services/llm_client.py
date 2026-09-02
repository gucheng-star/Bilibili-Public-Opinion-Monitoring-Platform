"""Provider-aware client for OpenAI-compatible chat completion APIs."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


LLM_TASK_SENTIMENT = "sentiment"
LLM_TASK_SUMMARY = "summary"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Explicit provider-specific extensions to the OpenAI-compatible payload."""

    supports_json_object: bool = False
    sentiment_thinking_parameter: tuple[str, Any] | None = None


PROVIDER_CAPABILITIES: dict[str, ProviderCapabilities] = {
    "deepseek": ProviderCapabilities(
        supports_json_object=True,
        sentiment_thinking_parameter=("thinking", {"type": "disabled"}),
    ),
    "bailian": ProviderCapabilities(
        supports_json_object=True,
        sentiment_thinking_parameter=("enable_thinking", False),
    ),
    "zhipu": ProviderCapabilities(
        supports_json_object=True,
        sentiment_thinking_parameter=("thinking", {"type": "disabled"}),
    ),
    "custom": ProviderCapabilities(),
}


class LLMRequestError(RuntimeError):
    """Safe, user-facing LLM request error."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        status_code: int | None = None,
        retry_after: int | None = None,
        provider_code: str | int | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retry_after = retry_after
        self.provider_code = provider_code


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
        raise LLMRequestError("无法解析模型服务地址，请检查 Base URL", category="dns") from exc
    for entry in addresses:
        address_text = entry[4][0].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            continue
        if not address.is_global:
            raise LLMRequestError("模型服务地址解析到了本机或私网，已拒绝请求", category="invalid_endpoint")


def _chat_url(base_url: str) -> str:
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"


def _models_url(base_url: str) -> str:
    chat_suffix = "/chat/completions"
    root = base_url[:-len(chat_suffix)] if base_url.endswith(chat_suffix) else base_url
    return root if root.endswith("/models") else f"{root}/models"


def _provider_capabilities(config: dict[str, str]) -> ProviderCapabilities:
    return PROVIDER_CAPABILITIES.get(str(config.get("provider", "custom")).strip().lower(), PROVIDER_CAPABILITIES["custom"])


def _task_payload(capabilities: ProviderCapabilities, task: str) -> dict[str, Any]:
    if task != LLM_TASK_SENTIMENT or not capabilities.sentiment_thinking_parameter:
        return {}
    field, value = capabilities.sentiment_thinking_parameter
    return {field: value.copy() if isinstance(value, dict) else value}


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After", "").strip()
    if not value.isascii() or not value.isdecimal():
        return None
    return int(value)


def _provider_error_code(response: httpx.Response) -> str | int | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    candidates = [
        error.get("code") if isinstance(error, dict) else None,
        payload.get("code"),
    ]
    for value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and len(str(value)) <= 80:
            return value
        if (
            isinstance(value, str)
            and 0 < len(value) <= 80
            and value.isascii()
            and all(character.isalnum() or character in "._:-" for character in value)
        ):
            return value
    return None


def _status_error(status: int, response: httpx.Response | None = None) -> LLMRequestError:
    if status in {401, 403}:
        message = "API Key 无效或没有模型权限"
        category = "authentication"
    elif status == 404:
        message = "模型服务不支持该接口，请检查 Base URL"
        category = "not_found"
    elif status == 429:
        message = "模型服务请求过于频繁，请稍后重试"
        category = "rate_limited"
    elif status >= 500:
        message = "模型服务暂时不可用"
        category = "server_error"
    else:
        message = f"模型服务拒绝了请求（HTTP {status}）"
        category = "http_error"
    return LLMRequestError(
        message,
        category=category,
        status_code=status,
        retry_after=_retry_after(response) if response else None,
        provider_code=_provider_error_code(response) if response else None,
    )


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
            raise LLMRequestError(
                "模型服务返回重定向，已拒绝跟随",
                category="redirect",
                status_code=response.status_code,
            )
        response.raise_for_status()
        data = response.json()
        entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise LLMRequestError("模型列表返回格式不完整", category="invalid_response")
        models = sorted({
            item["id"].strip()
            for item in entries
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        })
        if not models:
            raise LLMRequestError("模型服务没有返回可用模型", category="invalid_response")
        return models
    except LLMRequestError:
        raise
    except httpx.TimeoutException as exc:
        raise LLMRequestError("模型服务响应超时", category="timeout") from exc
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc.response.status_code, exc.response) from exc
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise LLMRequestError("无法连接模型服务，请检查接口配置", category="connection") from exc


def _extract_content(data: Any) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("模型返回格式不完整", category="invalid_response") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMRequestError("模型返回了空内容", category="invalid_response")
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
        raise LLMRequestError("模型未返回有效 JSON", category="invalid_response") from exc
    if not isinstance(parsed, dict):
        raise LLMRequestError("模型 JSON 返回值必须是对象", category="invalid_response")
    return parsed


async def chat_completion(
    config: dict[str, str],
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 400,
    retries: int = 1,
    check_dns: bool = True,
    response_format: dict[str, str] | None = None,
    task: str = LLM_TASK_SUMMARY,
) -> tuple[str, str]:
    """Return response content and the model that succeeded."""
    if task not in {LLM_TASK_SENTIMENT, LLM_TASK_SUMMARY}:
        raise ValueError("未知的 LLM 任务策略")
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
    capabilities = _provider_capabilities(config)
    for candidate in models:
        for attempt in range(retries + 1):
            payload: dict[str, Any] = {
                "model": candidate,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            payload.update(_task_payload(capabilities, task))
            if response_format and capabilities.supports_json_object:
                payload["response_format"] = response_format
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
                    raise LLMRequestError(
                        "模型服务返回重定向，已拒绝跟随",
                        category="redirect",
                        status_code=response.status_code,
                    )
                response.raise_for_status()
                return _extract_content(response.json()), candidate
            except LLMRequestError as exc:
                last_error = exc
            except httpx.TimeoutException as exc:
                last_error = LLMRequestError("模型服务响应超时", category="timeout")
                last_error.__cause__ = exc
            except httpx.HTTPStatusError as exc:
                last_error = _status_error(exc.response.status_code, exc.response)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = LLMRequestError("无法连接模型服务，请检查接口配置", category="connection")
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
    check_dns: bool = True,
    task: str = LLM_TASK_SENTIMENT,
) -> tuple[dict[str, Any], str]:
    content, model = await chat_completion(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        check_dns=check_dns,
        response_format={"type": "json_object"},
        task=task,
    )
    return parse_json_content(content), model
