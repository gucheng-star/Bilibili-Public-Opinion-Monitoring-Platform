import unittest
from unittest.mock import AsyncMock, patch

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
                config, [{"role": "user", "content": "test"}], check_dns=False, retries=0,
                task="sentiment",
            )
        self.assertEqual((content, model), ("完成", "deepseek-v4-flash"))
        self.assertNotIn("enable_thinking", calls[0][1]["json"])
        self.assertEqual(calls[0][1]["json"]["thinking"], {"type": "disabled"})

        calls.clear()
        config["provider"] = "bailian"
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            await llm_client.chat_completion(
                config, [{"role": "user", "content": "test"}], check_dns=False, retries=0,
                task="sentiment",
            )
        self.assertFalse(calls[0][1]["json"]["enable_thinking"])
        self.assertNotIn("thinking", calls[0][1]["json"])

    async def test_json_request_uses_response_format_only_for_supported_providers(self):
        calls = []
        response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            request=httpx.Request("POST", "https://api.example.com"),
        )
        config = {
            "provider": "deepseek", "base_url": "https://api.deepseek.com",
            "model": "model", "fallback_model": "", "api_key": "secret",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            parsed, _ = await llm_client.chat_completion_json(
                config, [{"role": "user", "content": "test"}], check_dns=False,
            )
        self.assertEqual(parsed, {"ok": True})
        self.assertEqual(calls[0][1]["json"]["response_format"], {"type": "json_object"})

        calls.clear()
        config["provider"] = "bailian"
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            await llm_client.chat_completion_json(
                config, [{"role": "user", "content": "output json"}], check_dns=False,
            )
        self.assertEqual(calls[0][1]["json"]["response_format"], {"type": "json_object"})
        self.assertFalse(calls[0][1]["json"]["enable_thinking"])

        calls.clear()
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            await llm_client.chat_completion(
                config, [{"role": "user", "content": "plain text"}], check_dns=False,
            )
        self.assertNotIn("response_format", calls[0][1]["json"])

        calls.clear()
        config["provider"] = "custom"
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
            await llm_client.chat_completion_json(
                config, [{"role": "user", "content": "test"}], check_dns=False,
            )
        self.assertNotIn("response_format", calls[0][1]["json"])

    async def test_all_provider_sentiment_payloads_are_isolated(self):
        response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            request=httpx.Request("POST", "https://api.example.com"),
        )
        expectations = {
            "deepseek": {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}},
            "bailian": {"enable_thinking": False, "response_format": {"type": "json_object"}},
            "zhipu": {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}},
            "custom": {},
        }
        for provider, expected_fields in expectations.items():
            with self.subTest(provider=provider):
                calls = []
                config = {
                    "provider": provider,
                    "base_url": "https://api.example.com/v1",
                    "model": "model",
                    "fallback_model": "",
                    "api_key": "secret",
                }
                with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, calls)):
                    await llm_client.chat_completion_json(
                        config, [{"role": "user", "content": "test"}], check_dns=False,
                    )
                payload = calls[0][1]["json"]
                self.assertEqual(
                    {key: payload[key] for key in ("thinking", "enable_thinking", "response_format") if key in payload},
                    expected_fields,
                )

    async def test_summary_and_sentiment_thinking_policies_are_independent(self):
        response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "完成"}}]},
            request=httpx.Request("POST", "https://api.example.com"),
        )
        for provider in ("deepseek", "bailian", "zhipu"):
            with self.subTest(provider=provider):
                config = {
                    "provider": provider,
                    "base_url": "https://api.example.com/v1",
                    "model": "model",
                    "fallback_model": "",
                    "api_key": "secret",
                }
                summary_calls = []
                with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, summary_calls)):
                    await llm_client.chat_completion(
                        config, [{"role": "user", "content": "summary"}],
                        check_dns=False, retries=0, task="summary",
                    )
                self.assertNotIn("thinking", summary_calls[0][1]["json"])
                self.assertNotIn("enable_thinking", summary_calls[0][1]["json"])

                sentiment_calls = []
                with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, sentiment_calls)):
                    await llm_client.chat_completion(
                        config, [{"role": "user", "content": "sentiment"}],
                        check_dns=False, retries=0, task="sentiment",
                    )
                if provider == "bailian":
                    self.assertFalse(sentiment_calls[0][1]["json"]["enable_thinking"])
                else:
                    self.assertEqual(sentiment_calls[0][1]["json"]["thinking"], {"type": "disabled"})

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

    async def test_http_error_metadata_is_sanitized_and_retry_after_is_bounded(self):
        response = httpx.Response(
            429,
            headers={"Retry-After": "12"},
            json={"error": {"code": "rate_limit_exceeded", "message": "secret provider detail"}},
            request=httpx.Request("POST", "https://api.example.com"),
        )
        config = {
            "provider": "zhipu",
            "base_url": "https://api.example.com/v1",
            "model": "model",
            "fallback_model": "",
            "api_key": "secret-api-key",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(response, [])):
            with self.assertRaises(llm_client.LLMRequestError) as raised:
                await llm_client.chat_completion(
                    config, [{"role": "user", "content": "test"}], check_dns=False, retries=0,
                )
        error = raised.exception
        self.assertEqual(error.category, "rate_limited")
        self.assertEqual(error.status_code, 429)
        self.assertEqual(error.retry_after, 12)
        self.assertEqual(error.provider_code, "rate_limit_exceeded")
        self.assertNotIn("secret provider detail", str(error))
        self.assertNotIn(config["api_key"], str(error))

    async def test_list_models_and_connection_errors_keep_safe_metadata(self):
        list_response = httpx.Response(
            429,
            headers={"Retry-After": "-1"},
            json={"error": {"code": "not safe code with spaces", "message": "secret detail"}},
            request=httpx.Request("GET", "https://api.example.com/models"),
        )
        config = {
            "provider": "custom",
            "base_url": "https://api.example.com/v1",
            "model": "model",
            "fallback_model": "",
            "api_key": "secret-api-key",
        }
        with patch.object(llm_client.httpx, "AsyncClient", return_value=FakeClient(list_response, [])):
            with self.assertRaises(llm_client.LLMRequestError) as listed:
                await llm_client.list_models(config, check_dns=False)
        self.assertEqual(listed.exception.category, "rate_limited")
        self.assertEqual(listed.exception.status_code, 429)
        self.assertIsNone(listed.exception.retry_after)
        self.assertIsNone(listed.exception.provider_code)

        client = FakeClient(None, [])
        client.post = AsyncMock(side_effect=httpx.ConnectError(
            "raw connection secret", request=httpx.Request("POST", "https://api.example.com"),
        ))
        with patch.object(llm_client.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(llm_client.LLMRequestError) as connected:
                await llm_client.chat_completion(
                    config, [{"role": "user", "content": "test"}], check_dns=False, retries=0,
                )
        self.assertEqual(connected.exception.category, "connection")
        self.assertIsNone(connected.exception.status_code)
        self.assertIsNone(connected.exception.retry_after)
        self.assertIsNone(connected.exception.provider_code)
        self.assertNotIn("raw connection secret", str(connected.exception))

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
