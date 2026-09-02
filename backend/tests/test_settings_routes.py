import json
import unittest
from unittest.mock import AsyncMock, patch

from api import settings_routes


class SettingsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_sentiment_connection_uses_real_structured_chain(self):
        config = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "fallback_model": "",
            "api_key": "secret",
        }
        sentiment_probe = AsyncMock(return_value=2)
        generic_probe = AsyncMock()

        with (
            patch.object(settings_routes, "get_task_config", return_value=config),
            patch.object(settings_routes, "test_sentiment_connection", sentiment_probe),
            patch.object(settings_routes, "chat_completion", generic_probe),
        ):
            result = await settings_routes.test_llm({"task": "sentiment"})

        sentiment_probe.assert_awaited_once_with(config)
        generic_probe.assert_not_awaited()
        self.assertTrue(result["ok"])
        self.assertIn("2", result["message"])

    async def test_summary_connection_passes_summary_task_policy(self):
        config = {
            "provider": "zhipu",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4.5-flash",
            "fallback_model": "",
            "api_key": "secret-key",
        }
        generic_probe = AsyncMock(return_value=("连接成功", "glm-4.5-flash"))

        with (
            patch.object(settings_routes, "get_task_config", return_value=config),
            patch.object(settings_routes, "chat_completion", generic_probe),
        ):
            result = await settings_routes.test_llm({"task": "summary"})

        self.assertTrue(result["ok"])
        self.assertEqual(generic_probe.await_args.kwargs["task"], "summary")

    async def test_model_list_result_never_echoes_api_key(self):
        config = {
            "provider": "zhipu",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4.5-flash",
            "fallback_model": "",
            "api_key": "secret-model-list-key",
        }
        model_probe = AsyncMock(return_value=["glm-4.5-flash"])

        with (
            patch.object(settings_routes, "get_task_config", return_value=config),
            patch.object(settings_routes, "list_models", model_probe),
        ):
            result = await settings_routes.get_llm_models({"task": "summary"})

        self.assertEqual(result["models"], ["glm-4.5-flash"])
        self.assertNotIn(config["api_key"], json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
