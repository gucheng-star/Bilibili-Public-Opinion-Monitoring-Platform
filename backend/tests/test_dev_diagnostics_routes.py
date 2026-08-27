import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException, Request

import main
from api import runtime_routes
from services import logging_config


class DevDiagnosticsRoutesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "workspace"
        self.log_dir = self.workspace / "logs" / "dev" / "diagnostics-test"
        self.workspace_patch = patch.object(logging_config, "_WORKSPACE_DIR", self.workspace)
        self.workspace_patch.start()
        self.environment = patch.dict(os.environ, {
            "BILI_DEV_LOGGING": "1",
            "BILI_DEV_LOG_DIR": str(self.log_dir),
            "BILI_DEV_SESSION_ID": "diagnostics-test",
        }, clear=False)
        self.environment.start()
        self.assertTrue(logging_config.configure_dev_logging())

    def tearDown(self):
        os.environ["BILI_DEV_LOGGING"] = "0"
        logging_config.configure_dev_logging()
        self.environment.stop()
        self.workspace_patch.stop()
        self.temporary.cleanup()

    def _client(self, host="127.0.0.1"):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=(host, 50000)),
            base_url="http://testserver",
        )

    @staticmethod
    def _origin_headers():
        return {"Origin": "http://localhost:5173"}

    @staticmethod
    def _event(**overrides):
        value = {
            "event": "window.error",
            "error_type": "TypeError",
            "stack": "TypeError: private comment\n    at renderDashboard (http://localhost:5173/src/App.tsx?api_key=must-not-log:10:2)",
            "breadcrumbs": [
                {
                    "event": "route.changed",
                    "path": "/workbench?api_key=must-not-log",
                },
                {
                    "event": "api.request_failed",
                    "path": "/status/:id",
                    "method": "GET",
                    "status": 404,
                    "duration_ms": 12,
                    "request_id": "abc123",
                },
                {
                    "event": "task.poll_status_changed",
                    "poll_status": "analyzing",
                },
            ],
            "state": {
                "route": "/workbench?private=must-not-log",
                "view_type": "single",
                "analysis_id": 7,
                "analysis_mode": "nlp",
                "loading": False,
                "active_filter_fields": ["gender", "not-allowed"],
            },
        }
        value.update(overrides)
        return value

    @classmethod
    def _payload(cls, *events, dropped_count=0):
        return {"session_id": "diagnostics-test", "events": list(events), "dropped_count": dropped_count}

    def _frontend_entries(self):
        for handler in logging.getLogger(logging_config.FRONTEND_LOGGER_NAME).handlers:
            handler.flush()
        path = self.log_dir / "frontend.log"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _backend_entries(self):
        for handler in logging.getLogger(logging_config.DEV_LOGGER_NAME).handlers:
            handler.flush()
        path = self.log_dir / "backend.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    async def test_disabled_returns_404(self):
        with patch.dict(os.environ, {"BILI_DEV_LOGGING": "0"}, clear=False):
            async with self._client() as client:
                session_response = await client.get(
                    "/api/runtime/dev-diagnostics/session",
                    headers=self._origin_headers(),
                )
                events_response = await client.post(
                    "/api/runtime/dev-diagnostics/events",
                    json=self._payload(self._event()),
                    headers=self._origin_headers(),
                )
        self.assertEqual(session_response.status_code, 404)
        self.assertEqual(events_response.status_code, 404)

    async def test_configuration_failure_returns_retryable_unavailable_response(self):
        with patch.object(
            logging_config,
            "_AcknowledgingRotatingFileHandler",
            side_effect=OSError("diagnostic directory unavailable"),
        ):
            self.assertFalse(logging_config.configure_dev_logging())
        async with self._client() as client:
            session_response = await client.get(
                "/api/runtime/dev-diagnostics/session", headers=self._origin_headers(),
            )
            events_response = await client.post(
                "/api/runtime/dev-diagnostics/events",
                json=self._payload(self._event()),
                headers=self._origin_headers(),
            )
        self.assertEqual(session_response.status_code, 503)
        self.assertEqual(events_response.status_code, 503)
        self.assertFalse(logging_config.dev_logging_ready())

    async def test_session_allows_exact_origin_or_referer_only(self):
        async with self._client() as client:
            allowed = await client.get("/api/runtime/dev-diagnostics/session", headers=self._origin_headers())
            via_referer = await client.get(
                "/api/runtime/dev-diagnostics/session",
                headers={"Referer": "http://127.0.0.1:5173/#/settings"},
            )
            missing = await client.get("/api/runtime/dev-diagnostics/session")
            tauri = await client.get(
                "/api/runtime/dev-diagnostics/session",
                headers={"Origin": "http://tauri.localhost"},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json(), {"enabled": True, "session_id": "diagnostics-test"})
        self.assertEqual(via_referer.status_code, 200)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(tauri.status_code, 403)

    async def test_post_requires_exact_origin_and_loopback_client(self):
        payload = self._payload(self._event())
        async with self._client() as client:
            missing_origin = await client.post("/api/runtime/dev-diagnostics/events", json=payload)
            tauri = await client.post(
                "/api/runtime/dev-diagnostics/events",
                json=payload,
                headers={"Origin": "http://tauri.localhost"},
            )
        async with self._client("192.0.2.10") as client:
            non_loopback = await client.post(
                "/api/runtime/dev-diagnostics/events", json=payload, headers=self._origin_headers(),
            )
        self.assertEqual(missing_origin.status_code, 403)
        self.assertEqual(tauri.status_code, 403)
        self.assertEqual(non_loopback.status_code, 403)

    async def test_rejects_raw_batch_and_single_event_limits(self):
        async with self._client() as client:
            too_many = await client.post(
                "/api/runtime/dev-diagnostics/events",
                json=self._payload(*[self._event() for _ in range(21)]),
                headers=self._origin_headers(),
            )
            event_too_large = await client.post(
                "/api/runtime/dev-diagnostics/events",
                json=self._payload(self._event(stack="x" * (9 * 1024))),
                headers=self._origin_headers(),
            )
            raw_too_large = await client.post(
                "/api/runtime/dev-diagnostics/events",
                content=b"{" + b"x" * (65 * 1024) + b"}",
                headers={**self._origin_headers(), "Content-Type": "application/json"},
            )
        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(event_too_large.status_code, 413)
        self.assertEqual(raw_too_large.status_code, 413)

    async def test_streamed_body_without_content_length_stops_at_limit(self):
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": b"x" * (65 * 1024), "more_body": False}

        request = Request({
            "type": "http", "method": "POST", "path": "/api/runtime/dev-diagnostics/events",
            "headers": [(b"origin", b"http://localhost:5173")], "client": ("127.0.0.1", 50000),
            "scheme": "http", "server": ("127.0.0.1", 8000), "query_string": b"",
        }, receive=receive)
        with self.assertRaises(HTTPException) as raised:
            await runtime_routes._read_limited_body(request)
        self.assertEqual(raised.exception.status_code, 413)

    async def test_forbids_extra_client_controlled_fields(self):
        event = self._event(component="forged", timestamp="forged", message="forged", details={"unsafe": True})
        async with self._client() as client:
            response = await client.post(
                "/api/runtime/dev-diagnostics/events", json=self._payload(event), headers=self._origin_headers(),
            )
        self.assertEqual(response.status_code, 422)

    async def test_rejects_free_text_paths_and_non_slug_identifiers(self):
        invalid_path = self._event(breadcrumbs=[{"event": "route.changed", "path": "/评论正文"}])
        invalid_identifiers = self._event(
            error_type="Type Error",
            breadcrumbs=[{"event": "component.action_started", "action": "clicked submit"}],
        )
        async with self._client() as client:
            path_response = await client.post(
                "/api/runtime/dev-diagnostics/events", json=self._payload(invalid_path), headers=self._origin_headers(),
            )
            identifier_response = await client.post(
                "/api/runtime/dev-diagnostics/events", json=self._payload(invalid_identifiers), headers=self._origin_headers(),
            )
        self.assertEqual(path_response.status_code, 422)
        self.assertEqual(identifier_response.status_code, 422)

    async def test_writes_projected_frontend_log_without_request_log_recursion(self):
        async with self._client() as client:
            response = await client.post(
                "/api/runtime/dev-diagnostics/events", json=self._payload(self._event()), headers=self._origin_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"accepted": 1})
        self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{12}$")
        handler = next(iter(logging.getLogger(logging_config.FRONTEND_LOGGER_NAME).handlers))
        self.assertEqual(handler.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 1)
        entry = self._frontend_entries()[0]
        self.assertEqual(entry["component"], "frontend")
        self.assertEqual(entry["event"], "window.error")
        self.assertEqual(entry["level"], "ERROR")
        self.assertEqual(entry["dev_session_id"], "diagnostics-test")
        self.assertEqual(entry["message"], "浏览器窗口错误")
        self.assertEqual(entry["breadcrumbs"], [
            {"event": "route.changed", "path": "/workbench"},
            {
                "event": "api.request_failed", "path": "/status/:id", "method": "GET",
                "status": 404, "duration_ms": 12.0, "request_id": "abc123",
            },
            {"event": "task.poll_status_changed", "poll_status": "analyzing"},
        ])
        self.assertEqual(entry["state"]["route"], "/workbench")
        self.assertEqual(entry["state"]["active_filter_fields"], ["gender"])
        self.assertEqual(entry["stack"], "at renderDashboard")
        self.assertNotIn("api.request_completed", [item["event"] for item in self._backend_entries()])

    async def test_frontend_flush_failure_never_returns_accepted_and_disables_session(self):
        handler = next(
            item for item in logging.getLogger(logging_config.FRONTEND_LOGGER_NAME).handlers
            if getattr(item, "_bili_dev_handler", False)
        )
        with patch.object(handler, "flush", side_effect=[None, None, OSError("disk full")]):
            async with self._client() as client:
                failed = await client.post(
                    "/api/runtime/dev-diagnostics/events",
                    json=self._payload(self._event(), self._event(event="startup.failed")),
                    headers=self._origin_headers(),
                )
        async with self._client() as client:
            unavailable = await client.get(
                "/api/runtime/dev-diagnostics/session", headers=self._origin_headers(),
            )
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("accepted", failed.json())
        self.assertEqual(unavailable.status_code, 503)
        self.assertFalse(logging_config.dev_logging_ready())

    async def test_stack_drops_secret_message_urls_paths_and_comment_text(self):
        secret_values = {
            "BILI_API_KEY": "api-secret-value",
            "BILI_LOCAL_TOKEN": "local-secret-value",
        }
        event = self._event(
            stack=(
                "TypeError: 评论正文 Cookie=SESSDATA-secret Authorization: Bearer bearer-secret; "
                "api_key=api-secret-value; local_token=local-secret-value\n"
                "    at renderDashboard (http://localhost:5173/src/App.tsx?private=comment:10:2)\n"
                "    at App (C:\\Users\\PrivateName\\App.tsx:20:4)\n"
                "    in ErrorBoundary (created by App)"
            ),
        )
        with patch.dict(os.environ, secret_values, clear=False):
            async with self._client() as client:
                response = await client.post(
                    "/api/runtime/dev-diagnostics/events", json=self._payload(event), headers=self._origin_headers(),
                )
        self.assertEqual(response.status_code, 200)
        text = (self.log_dir / "frontend.log").read_text(encoding="utf-8")
        for value in ("SESSDATA-secret", "bearer-secret", "api-secret-value", "local-secret-value", "评论正文", "localhost:5173", "PrivateName"):
            self.assertNotIn(value, text)
        entry = self._frontend_entries()[0]
        self.assertEqual(entry["stack"], "at renderDashboard\nat App\ncomponent ErrorBoundary")

    async def test_dropped_count_writes_server_generated_queue_event_first(self):
        async with self._client() as client:
            response = await client.post(
                "/api/runtime/dev-diagnostics/events",
                json=self._payload(self._event(event="startup.failed"), dropped_count=3),
                headers=self._origin_headers(),
            )
        self.assertEqual(response.status_code, 200)
        entries = self._frontend_entries()
        self.assertEqual(entries[0]["event"], "queue.dropped")
        self.assertEqual(entries[0]["count"], 3)
        self.assertEqual(entries[1]["event"], "startup.failed")

    async def test_desktop_token_does_not_bypass_source_checks(self):
        payload = self._payload(self._event())
        with patch.dict(os.environ, {
            "BILI_DESKTOP_MODE": "1",
            "BILI_LOCAL_TOKEN": "desktop-token",
        }, clear=False):
            async with self._client() as client:
                rejected = await client.post(
                    "/api/runtime/dev-diagnostics/events",
                    json=payload,
                    headers={"Origin": "http://tauri.localhost", "X-Bili-Local-Token": "desktop-token"},
                )
                token_still_required = await client.post(
                    "/api/runtime/dev-diagnostics/events", json=payload, headers=self._origin_headers(),
                )
                allowed = await client.post(
                    "/api/runtime/dev-diagnostics/events",
                    json=payload,
                    headers={**self._origin_headers(), "X-Bili-Local-Token": "desktop-token"},
                )
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(token_still_required.status_code, 401)
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
