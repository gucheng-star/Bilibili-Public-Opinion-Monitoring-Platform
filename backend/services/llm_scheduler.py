"""Bounded, task-lifetime scheduling for LLM sentiment requests."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from services.llm_client import LLMRequestError
from services.logging_config import get_logger, log_event


MAX_TRANSPORT_ATTEMPTS = 3
MAX_PROTOCOL_REPAIRS = 1
MAX_TOTAL_ATTEMPTS = 24
RECOVERY_SUCCESS_COUNT = 10


@dataclass(frozen=True)
class ProviderScheduleLimits:
    initial_concurrency: int
    max_concurrency: int


PROVIDER_SCHEDULE_LIMITS = {
    "deepseek": ProviderScheduleLimits(8, 16),
    "bailian": ProviderScheduleLimits(6, 12),
    "zhipu": ProviderScheduleLimits(4, 8),
    "custom": ProviderScheduleLimits(3, 6),
}


class ProtocolBatchError(RuntimeError):
    """A response schema failure that may be repaired or split safely."""

    def __init__(self, messages: list[str]):
        self.messages = tuple(messages)
        super().__init__("；".join(messages))


RequestCallable = Callable[[list[dict], str, str | None], Awaitable[dict[str, Any]]]
SuccessCallable = Callable[[list[dict], dict[str, Any]], None]


class LLMScheduler:
    """One analysis-lifetime budget, limiter, and retry policy for sentiment."""

    def __init__(
        self,
        config: dict[str, str],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        max_total_attempts: int = MAX_TOTAL_ATTEMPTS,
    ):
        provider = str(config.get("provider", "custom")).strip().lower()
        self.provider = provider if provider in PROVIDER_SCHEDULE_LIMITS else "custom"
        self.primary_model = str(config.get("model", "")).strip()
        fallback = str(config.get("fallback_model", "")).strip()
        self.fallback_model = fallback if fallback and fallback != self.primary_model else ""
        self.limits = PROVIDER_SCHEDULE_LIMITS[self.provider]
        self.effective_concurrency = self.limits.initial_concurrency
        self.total_attempts = 0
        self.max_total_attempts = max_total_attempts
        self._active_attempts = 0
        self._success_streak = 0
        self._condition = asyncio.Condition()
        self._sleep = sleep
        self._jitter = jitter
        self._logger = get_logger("llm_scheduler")

    async def run_batch(
        self,
        batch_index: int,
        batch: list[dict],
        request: RequestCallable,
        on_success: SuccessCallable | None = None,
    ) -> dict[str, Any]:
        result = await self._run_protocol(batch_index, batch, request, on_success)
        await self._record_success(batch_index)
        return result

    async def _run_protocol(
        self,
        batch_index: int,
        batch: list[dict],
        request: RequestCallable,
        on_success: SuccessCallable | None,
    ) -> dict[str, Any]:
        try:
            result = await self._run_transport(batch_index, batch, request, repair_instruction=None)
            if on_success:
                on_success(batch, result)
            return result
        except Exception as first_error:
            if self._classify(first_error) != "protocol":
                raise

        try:
            result = await self._run_transport(
                batch_index,
                batch,
                request,
                repair_instruction="上一次输出未通过协议校验；请严格按既定 JSON 协议完整返回。",
            )
            if on_success:
                on_success(batch, result)
            return result
        except Exception as repair_error:
            if self._classify(repair_error) != "protocol":
                raise
            if len(batch) <= 1:
                raise ProtocolBatchError(["单条评论未能完成大模型协议校验"]) from repair_error

        midpoint = len(batch) // 2
        results: dict[str, Any] = {}
        protocol_messages: list[str] = []
        for half in (batch[:midpoint], batch[midpoint:]):
            try:
                results.update(await self._run_protocol(batch_index, half, request, on_success))
            except ProtocolBatchError as error:
                protocol_messages.extend(error.messages)
        if protocol_messages:
            raise ProtocolBatchError(protocol_messages)
        return results

    async def _run_transport(
        self,
        batch_index: int,
        batch: list[dict],
        request: RequestCallable,
        *,
        repair_instruction: str | None,
    ) -> dict[str, Any]:
        for attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
            model = self.fallback_model if self.fallback_model and attempt > 1 else self.primary_model
            try:
                return await self._single_attempt(batch_index, batch, model, repair_instruction, request)
            except Exception as error:
                category = self._classify(error)
                await self._record_failure(batch_index, attempt, category)
                if category not in {"temporary", "rate_limited"} or attempt == MAX_TRANSPORT_ATTEMPTS:
                    raise
                await self._sleep(self._retry_delay(error, attempt))
        raise RuntimeError("unreachable transport retry state")

    async def _single_attempt(
        self,
        batch_index: int,
        batch: list[dict],
        model: str,
        repair_instruction: str | None,
        request: RequestCallable,
    ) -> dict[str, Any]:
        async with self._condition:
            while self._active_attempts >= self.effective_concurrency:
                await self._condition.wait()
            if self.total_attempts >= self.max_total_attempts:
                raise LLMRequestError("大模型请求预算已用尽", category="budget_exhausted")
            self._active_attempts += 1
            self.total_attempts += 1
        try:
            return await request(batch, model, repair_instruction)
        finally:
            async with self._condition:
                self._active_attempts -= 1
                self._condition.notify_all()

    def _classify(self, error: Exception) -> str:
        current: BaseException | None = error
        while current:
            if isinstance(current, ValueError):
                return "protocol"
            if isinstance(current, LLMRequestError):
                if current.provider_code in {1302, "1302"}:
                    return "rate_limited"
                if current.provider_code in {1305, "1305"}:
                    return "temporary"
                if current.category == "invalid_response":
                    return "protocol"
                if current.category in {"timeout", "connection", "rate_limited", "server_error"}:
                    return "rate_limited" if current.category == "rate_limited" else "temporary"
                return "permanent"
            current = current.__cause__
        return "permanent"

    async def _record_failure(self, batch_index: int, attempt: int, category: str) -> None:
        self._success_streak = 0
        log_event(
            self._logger,
            "WARNING",
            "llm.scheduler_attempt_failed",
            "大模型调度请求失败",
            batch_index=batch_index,
            attempt=attempt,
            stage=category,
        )
        if category != "rate_limited":
            return
        async with self._condition:
            previous = self.effective_concurrency
            self.effective_concurrency = max(1, self.effective_concurrency // 2)
            self._condition.notify_all()
        if self.effective_concurrency != previous:
            log_event(
                self._logger,
                "WARNING",
                "llm.scheduler_concurrency_reduced",
                "大模型调度并发已降低",
                batch_index=batch_index,
                attempt=attempt,
                stage=category,
                count=self.effective_concurrency,
            )

    async def _record_success(self, batch_index: int) -> None:
        self._success_streak += 1
        if self._success_streak < RECOVERY_SUCCESS_COUNT or self.effective_concurrency >= self.limits.max_concurrency:
            return
        async with self._condition:
            self.effective_concurrency += 1
            self._success_streak = 0
            self._condition.notify_all()
        log_event(
            self._logger,
            "INFO",
            "llm.scheduler_concurrency_recovered",
            "大模型调度并发已恢复",
            batch_index=batch_index,
            attempt=0,
            stage="success",
            count=self.effective_concurrency,
        )

    def _retry_delay(self, error: Exception, attempt: int) -> float:
        if isinstance(error, LLMRequestError) and error.retry_after is not None:
            return float(error.retry_after)
        return float(2 ** (attempt - 1)) + min(max(self._jitter(), 0), 1) * 0.25
