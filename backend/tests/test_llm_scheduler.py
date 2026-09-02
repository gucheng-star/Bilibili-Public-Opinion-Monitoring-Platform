import unittest
from unittest.mock import AsyncMock

from services.llm_client import LLMRequestError
from services.llm_scheduler import LLMScheduler


class LLMSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def config(self, provider="deepseek", fallback_model=""):
        return {
            "provider": provider,
            "model": "primary-model",
            "fallback_model": fallback_model,
        }

    async def test_429_retries_within_shared_budget_and_recovers_concurrency(self):
        scheduler = LLMScheduler(self.config(), sleep=AsyncMock(), jitter=lambda: 0)
        failures = [
            LLMRequestError("rate limit", category="rate_limited", status_code=429, retry_after=0),
            None,
        ]

        async def request(_batch, _model, _repair):
            failure = failures.pop(0) if failures else None
            if failure:
                raise failure
            return {"ok": True}

        self.assertEqual(await scheduler.run_batch(1, [{"rpid": 1}], request), {"ok": True})
        self.assertEqual(scheduler.total_attempts, 2)
        self.assertEqual(scheduler.effective_concurrency, 4)

        for index in range(2, 11):
            self.assertEqual(await scheduler.run_batch(index, [{"rpid": index}], request), {"ok": True})
        self.assertEqual(scheduler.effective_concurrency, 5)

    async def test_glm_1302_and_1305_are_temporary_without_extra_nested_attempts(self):
        for code, expected_concurrency in ((1302, 2), (1305, 4)):
            with self.subTest(code=code):
                scheduler = LLMScheduler(self.config("zhipu"), sleep=AsyncMock(), jitter=lambda: 0)
                outcomes = [
                    LLMRequestError("provider busy", category="http_error", provider_code=code),
                    {"ok": True},
                ]

                async def request(_batch, _model, _repair):
                    result = outcomes.pop(0)
                    if isinstance(result, Exception):
                        raise result
                    return result

                self.assertEqual(await scheduler.run_batch(1, [{"rpid": 1}], request), {"ok": True})
                self.assertEqual(scheduler.total_attempts, 2)
                self.assertEqual(scheduler.effective_concurrency, expected_concurrency)

    async def test_permanent_errors_do_not_retry_or_split(self):
        scheduler = LLMScheduler(self.config(), sleep=AsyncMock(), jitter=lambda: 0)
        request = AsyncMock(side_effect=LLMRequestError("auth", category="authentication", status_code=401))

        with self.assertRaises(LLMRequestError):
            await scheduler.run_batch(1, [{"rpid": 1}, {"rpid": 2}], request)
        self.assertEqual(request.await_count, 1)
        self.assertEqual(scheduler.total_attempts, 1)

    async def test_5xx_and_fallback_share_a_three_attempt_total_limit(self):
        scheduler = LLMScheduler(self.config(fallback_model="fallback-model"), sleep=AsyncMock(), jitter=lambda: 0)
        models = []

        async def request(_batch, model, _repair):
            models.append(model)
            raise LLMRequestError("unavailable", category="server_error", status_code=503)

        with self.assertRaises(LLMRequestError):
            await scheduler.run_batch(1, [{"rpid": 1}], request)
        self.assertEqual(scheduler.total_attempts, 3)
        self.assertEqual(models, ["primary-model", "fallback-model", "fallback-model"])

    async def test_malformed_protocol_repairs_once_then_splits_and_keeps_subbatches(self):
        scheduler = LLMScheduler(self.config(), sleep=AsyncMock(), jitter=lambda: 0)
        call_sizes = []

        async def request(batch, _model, _repair):
            call_sizes.append(len(batch))
            if len(batch) == 2:
                raise ValueError("invalid items")
            return {str(batch[0]["rpid"]): {"emotion": "neutral", "style": "plain"}}

        result = await scheduler.run_batch(1, [{"rpid": 1}, {"rpid": 2}], request)
        self.assertEqual(call_sizes, [2, 2, 1, 1])
        self.assertEqual(set(result), {"1", "2"})
        self.assertEqual(scheduler.total_attempts, 4)

    async def test_malformed_json_gets_one_targeted_repair_without_transport_retry(self):
        scheduler = LLMScheduler(self.config(), sleep=AsyncMock(), jitter=lambda: 0)
        repair_instructions = []
        outcomes = [
            LLMRequestError("invalid json", category="invalid_response"),
            {"1": {"emotion": "neutral", "style": "plain"}},
        ]

        async def request(_batch, _model, repair_instruction):
            repair_instructions.append(repair_instruction)
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        self.assertEqual(
            await scheduler.run_batch(1, [{"rpid": 1}], request),
            {"1": {"emotion": "neutral", "style": "plain"}},
        )
        self.assertEqual(scheduler.total_attempts, 2)
        self.assertEqual(repair_instructions[0], None)
        self.assertIsNotNone(repair_instructions[1])


if __name__ == "__main__":
    unittest.main()
