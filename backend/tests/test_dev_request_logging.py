import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

import main
from api import routes
from api import runtime_routes
from services import logging_config


class DevRequestLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "workspace"
        self.log_dir = self.workspace / "logs" / "dev" / "request-test"
        self.workspace_patch = patch.object(logging_config, "_WORKSPACE_DIR", self.workspace)
        self.workspace_patch.start()
        self.environment = patch.dict(os.environ, {
            "BILI_DEV_LOGGING": "1",
            "BILI_DEV_LOG_DIR": str(self.log_dir),
            "BILI_DEV_SESSION_ID": "request-test",
            "BILI_DEV_LOG_LEVEL": "DEBUG",
        }, clear=False)
        self.environment.start()
        self.assertTrue(logging_config.configure_dev_logging())

    def tearDown(self):
        os.environ["BILI_DEV_LOGGING"] = "0"
        logging_config.configure_dev_logging()
        self.environment.stop()
        self.workspace_patch.stop()
        self.temporary.cleanup()

    def _entries(self):
        for handler in logging.getLogger(logging_config.DEV_LOGGER_NAME).handlers:
            handler.flush()
        return [
            json.loads(line)
            for line in (self.log_dir / "backend.log").read_text(encoding="utf-8").splitlines()
        ]

    async def test_request_middleware_returns_id_and_logs_only_route_summary(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/status/42",
            "raw_path": b"/api/status/42",
            "query_string": b"api_key=must-not-appear",
            "headers": [(b"cookie", b"SESSDATA=must-not-appear")],
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 50000),
        }
        request = Request(scope)

        async def call_next(current_request):
            current_request.scope["route"] = SimpleNamespace(path="/api/status/{analysis_id}")
            return JSONResponse({"ok": True})

        response = await main.record_request_diagnostics(request, call_next)
        self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{12}$")
        entry = self._entries()[-1]
        self.assertEqual(entry["event"], "api.request_completed")
        self.assertEqual(entry["route"], "/api/status/{analysis_id}")
        self.assertEqual(entry["level"], "DEBUG")
        serialized = json.dumps(entry, ensure_ascii=False)
        self.assertNotIn("must-not-appear", serialized)
        self.assertNotIn("query", serialized.lower())

    async def test_background_wrapper_uses_creator_id_then_restores_context(self):
        observed = []

        async def capture_context(*_args, **_kwargs):
            observed.append(logging_config.get_request_id())

        outer_token = logging_config.set_request_id("outer-request")
        try:
            with patch.object(routes, "_run_analysis_inner", AsyncMock(side_effect=capture_context)):
                await routes._run_analysis(1, "BV1", 1, request_id="creator-request")
            self.assertEqual(observed, ["creator-request"])
            self.assertEqual(logging_config.get_request_id(), "outer-request")
        finally:
            logging_config.reset_request_id(outer_token)

    async def test_missing_analysis_records_an_aborted_terminal_event(self):
        database = MagicMock()
        database.query.return_value.filter_by.return_value.first.return_value = None
        with patch.object(routes, "SessionLocal", return_value=database):
            result = await routes._run_analysis_inner(404, "BV1", 1)
        self.assertFalse(result)
        database.close.assert_called_once()
        self.assertEqual(self._entries()[-1]["event"], "analysis.task_aborted")

    async def test_unmatched_path_is_not_written_to_log(self):
        private_path = "/api/not-found/comment-private-text"
        request = Request({
            "type": "http",
            "method": "GET",
            "path": private_path,
            "raw_path": private_path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 50000),
        })

        async def call_next(_request):
            return JSONResponse({"detail": "not found"}, status_code=404)

        await main.record_request_diagnostics(request, call_next)
        entry = self._entries()[-1]
        self.assertEqual(entry["route"], "<unmatched>")
        self.assertNotIn(private_path, json.dumps(entry, ensure_ascii=False))

    async def test_real_asgi_stack_correlates_cors_401_and_unhandled_errors(self):
        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            health = await client.get(
                "/api/runtime/health",
                headers={"Origin": "http://localhost:5173"},
            )
            self.assertEqual(health.status_code, 200)
            self.assertRegex(health.headers["X-Request-ID"], r"^[0-9a-f]{12}$")
            self.assertIn(
                "X-Request-ID",
                health.headers["Access-Control-Expose-Headers"],
            )

            with patch.dict(os.environ, {
                "BILI_DESKTOP_MODE": "1",
                "BILI_LOCAL_TOKEN": "expected-token",
            }, clear=False):
                unauthorized = await client.get(
                    "/api/runtime/activity",
                    headers={"Origin": "http://localhost:5173"},
                )
            self.assertEqual(unauthorized.status_code, 401)
            self.assertRegex(unauthorized.headers["X-Request-ID"], r"^[0-9a-f]{12}$")

            with patch.object(runtime_routes, "current_activity", side_effect=RuntimeError("private-comment")):
                failed = await client.get(
                    "/api/runtime/activity",
                    headers={"Origin": "http://localhost:5173"},
                )
            self.assertEqual(failed.status_code, 500)
            self.assertEqual(failed.json(), {"detail": "服务器内部错误"})
            self.assertRegex(failed.headers["X-Request-ID"], r"^[0-9a-f]{12}$")

        serialized = json.dumps(self._entries(), ensure_ascii=False)
        self.assertNotIn("expected-token", serialized)
        self.assertNotIn("private-comment", serialized)
        self.assertIn("api.request_failed", serialized)


if __name__ == "__main__":
    unittest.main()
