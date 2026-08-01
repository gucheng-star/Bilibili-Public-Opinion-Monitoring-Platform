import unittest
from unittest.mock import patch

import httpx

from services import llm_client


class FakeClient:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class LLMClientTests(unittest.IsolatedAsyncioTestCase):
    def test_url_validation_rejects_non_public_targets(self):
        for value in (
            "http://api.example.com/v1",
            "https://localhost/v1",
            "https://127.0.0.1/v1",
            "https://user:pass@example.com/v1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                llm_client.validate_base_url(value)
        self.assertEqual(
            llm_client.validate_base_url("https://api.example.com/v1/"),
            "https://api.example.com/v1",
        )

    def test_json_parser_accepts_fenced_object(self):
        self.assertEqual(llm_client.parse_json_content("```json\n{\"ok\":true}\n```"), {"ok": True})
        with self.assertRaises(llm_client.LLMRequestError):
            llm_client.parse_json_content("not json")

    async def test_provider_specific_payload_isolated(self):
        calls = []
        response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "完成"}}]},
            request=httpx.Request("POST", "https://api.example.com"),
        )
        config = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "fallback_model": "",
            "api_key": "secret",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            content, model = await llm_client.chat_completion(
                config, [{"role": "user", "content": "test"}], check_dns=False, retries=0
            )
        self.assertEqual((content, model), ("完成", "deepseek-v4-flash"))
        self.assertNotIn("enable_thinking", calls[0][1]["json"])
        self.assertEqual(calls[0][1]["json"]["thinking"], {"type": "disabled"})

        calls.clear()
        config["provider"] = "bailian"
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            await llm_client.chat_completion(
                config, [{"role": "user", "content": "test"}], check_dns=False, retries=0
            )
        self.assertFalse(calls[0][1]["json"]["enable_thinking"])
        self.assertNotIn("thinking", calls[0][1]["json"])

    async def test_authentication_error_is_sanitized(self):
        response = httpx.Response(
            401,
            json={"error": {"message": "raw provider secret detail"}},
            request=httpx.Request("POST", "https://api.example.com"),
        )
        config = {
            "provider": "custom",
            "base_url": "https://api.example.com/v1",
            "model": "model",
            "fallback_model": "",
            "api_key": "secret",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, [])):
            with self.assertRaisesRegex(llm_client.LLMRequestError, "API Key"):
                await llm_client.chat_completion(
                    config, [{"role": "user", "content": "test"}], check_dns=False, retries=0
                )

    async def test_list_models_uses_compatible_endpoint_and_deduplicates_ids(self):
        calls = []
        response = httpx.Response(
            200,
            json={"object": "list", "data": [
                {"id": "model-b", "object": "model"},
                {"id": "model-a", "object": "model"},
                {"id": "model-a", "object": "model"},
                {"id": " ", "object": "model"},
                {"object": "model"},
            ]},
            request=httpx.Request("GET", "https://api.example.com/v1/models"),
        )
        config = {
            "provider": "custom",
            "base_url": "https://api.example.com/v1/chat/completions",
            "model": "",
            "fallback_model": "",
            "api_key": "secret",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            models = await llm_client.list_models(config, check_dns=False)

        self.assertEqual(models, ["model-a", "model-b"])
        self.assertEqual(calls[0][0], "https://api.example.com/v1/models")
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer secret")

    async def test_list_models_rejects_incomplete_response(self):
        response = httpx.Response(
            200,
            json={"object": "list"},
            request=httpx.Request("GET", "https://api.example.com/v1/models"),
        )
        config = {
            "provider": "custom",
            "base_url": "https://api.example.com/v1",
            "model": "",
            "fallback_model": "",
            "api_key": "secret",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, [])):
            with self.assertRaisesRegex(llm_client.LLMRequestError, "模型列表返回格式不完整"):
                await llm_client.list_models(config, check_dns=False)


if __name__ == "__main__":
    unittest.main()
