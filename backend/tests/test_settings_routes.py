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


if __name__ == "__main__":
    unittest.main()
