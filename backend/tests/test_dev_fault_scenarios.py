import json
import logging
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import BackgroundTasks, HTTPException

from api import routes
from services import bilibili, logging_config, sentiment_llm
from services.llm_client import LLMRequestError


API_KEY_SENTINEL = "fault-test-api-key-must-not-persist"
COMMENT_SENTINEL = "fault-test-comment-must-not-persist"


class TimeoutClient:
    """A local httpx-shaped client that fails every request without I/O."""

    def __init__(self):
        self.calls = 0

    async def get(self, *_args, **_kwargs):
        self.calls += 1
        raise httpx.ReadTimeout("local timeout injection")


class LocalAsyncClient:
    """Context-manager replacement for the route's httpx client."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class CommitFailingSession:
    """Minimal SessionLocal replacement that never opens SQLite."""

    def __init__(self):
        self.added = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commit_calls += 1
        raise sqlite3.OperationalError("local task-create database fault")

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


class DevFaultScenarioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "workspace"
        self.log_dir = self.workspace / "logs" / "dev" / "fault-scenarios"
        self.workspace_patch = patch.object(logging_config, "_WORKSPACE_DIR", self.workspace)
        self.workspace_patch.start()
        self.environment = patch.dict(os.environ, {
            "BILI_DEV_LOGGING": "1",
            "BILI_DEV_LOG_DIR": str(self.log_dir),
            "BILI_DEV_SESSION_ID": "fault-scenarios",
            "BILI_API_KEY": API_KEY_SENTINEL,
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
        path = self.log_dir / "backend.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _assert_secrets_absent(self):
        serialized = (self.log_dir / "backend.log").read_text(encoding="utf-8")
        self.assertNotIn(API_KEY_SENTINEL, serialized)
        self.assertNotIn(COMMENT_SENTINEL, serialized)

    async def test_video_info_timeout_records_component_stage_and_error_type(self):
        client = TimeoutClient()

        with self.assertRaises(httpx.ReadTimeout):
            await bilibili.get_video_info(client, "BV1FAULT00001")

        self.assertEqual(client.calls, 1)
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["component"], "bilibili")
        self.assertEqual(entries[0]["event"], "bilibili.video_request_failed")
        self.assertEqual(entries[0]["error_type"], "ReadTimeout")

    async def test_fetch_comments_timeout_records_page_stage_and_error_type(self):
        client = TimeoutClient()

        comments = await bilibili.fetch_comments(client, avid=1, max_comments=20, delay=0)

        self.assertEqual(comments, [])
        self.assertEqual(client.calls, 1)
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["component"], "bilibili")
        self.assertEqual(entries[0]["event"], "bilibili.fetch_page_failed")
        self.assertEqual(entries[0]["error_type"], "ReadTimeout")
        self.assertEqual(entries[0]["batch_index"], 1)
        self.assertEqual(entries[0]["count"], 0)

    async def test_start_analysis_commit_fault_keeps_http_error_and_logs_without_database(self):
        session = CommitFailingSession()
        video_info = {
            "avid": 1,
            "title": "local fake video",
            "cover": "https://example.invalid/cover.jpg",
            "play": 1,
        }
        local_client = LocalAsyncClient()

        with (
            patch.object(routes.httpx, "AsyncClient", return_value=local_client),
            patch.object(routes, "get_video_info", new=AsyncMock(return_value=video_info)) as get_info,
            patch.object(routes, "SessionLocal", return_value=session) as session_local,
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.start_analysis({"bv": "BV1FAULT00002"}, BackgroundTasks())

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(raised.exception.detail, "local task-create database fault")
        get_info.assert_awaited_once_with(local_client, "BV1FAULT00002")
        session_local.assert_called_once_with()
        self.assertEqual(session.commit_calls, 1)
        self.assertEqual(session.rollback_calls, 1)
        self.assertEqual(session.close_calls, 1)
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["component"], "analysis")
        self.assertEqual(entries[0]["event"], "analysis.task_create_failed")
        self.assertEqual(entries[0]["error_type"], "OperationalError")
        self.assertNotIn("analysis_id", entries[0])

    async def test_llm_auth_failure_logs_batch_lifecycle_without_key_or_comment(self):
        comments = [{"rpid": 1, "content": COMMENT_SENTINEL}]

        with (
            patch.object(
                sentiment_llm,
                "_analyze_comment_batch",
                new=AsyncMock(side_effect=LLMRequestError("local authentication failure")),
            ) as analyze_batch,
            patch.object(sentiment_llm.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "连续 3 次失败"):
                await sentiment_llm.batch_analyze_llm(
                    comments,
                    {"api_key": API_KEY_SENTINEL},
                    concurrency=1,
                )

        self.assertEqual(analyze_batch.await_count, 3)
        self.assertEqual(sleep.await_count, 2)
        entries = self._entries()
        self.assertEqual(
            [entry["event"] for entry in entries],
            ["llm.batch_started", "llm.batch_retried", "llm.batch_retried", "llm.batch_failed"],
        )
        self.assertTrue(all(entry["component"] == "sentiment_llm" for entry in entries))
        self.assertEqual(entries[0]["batch_index"], 1)
        self.assertEqual([entry["attempt"] for entry in entries[1:3]], [1, 2])
        self.assertTrue(all(entry["error_type"] == "LLMRequestError" for entry in entries[1:3]))
        self.assertEqual(entries[3]["batch_index"], 1)
        self.assertEqual(entries[3]["error_type"], "RuntimeError")
        self._assert_secrets_absent()

    async def test_invalid_llm_label_uses_real_protocol_retry_and_failure_logging(self):
        comments = [{"rpid": 2, "content": COMMENT_SENTINEL}]
        invalid_result = ({"items": [{"id": "item-1", "label": "not-a-valid-label"}]}, "local-fake")

        with (
            patch.object(sentiment_llm, "chat_completion_json", new=AsyncMock(return_value=invalid_result)) as chat,
            patch.object(sentiment_llm.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            with self.assertRaises(sentiment_llm.LLMProtocolFailure):
                await sentiment_llm.batch_analyze_llm(
                    comments,
                    {"api_key": API_KEY_SENTINEL},
                    concurrency=1,
                )

        self.assertEqual(chat.await_count, 3)
        self.assertEqual([call.args for call in sleep.await_args_list], [(1,), (2,)])
        entries = self._entries()
        self.assertEqual(
            [entry["event"] for entry in entries],
            ["llm.batch_started", "llm.batch_retried", "llm.batch_retried", "llm.batch_failed"],
        )
        self.assertEqual(entries[0]["batch_index"], 1)
        self.assertTrue(all(entry["error_type"] == "ValueError" for entry in entries[1:3]))
        self.assertEqual(entries[3]["batch_index"], 1)
        self.assertEqual(entries[3]["error_type"], "LLMProtocolFailure")
        self._assert_secrets_absent()

    async def test_failing_log_handler_does_not_mask_video_timeout(self):
        class FailingHandler(logging.Handler):
            def emit(self, _record):
                raise OSError("local handler fault")

        handler = FailingHandler()
        dev_root = logging.getLogger(logging_config.DEV_LOGGER_NAME)
        dev_root.addHandler(handler)
        try:
            with self.assertRaises(httpx.ReadTimeout):
                await bilibili.get_video_info(TimeoutClient(), "BV1FAULT00003")
        finally:
            dev_root.removeHandler(handler)
            handler.close()

        entries = self._entries()
        self.assertEqual(entries[0]["event"], "bilibili.video_request_failed")
        self.assertEqual(entries[0]["error_type"], "ReadTimeout")


if __name__ == "__main__":
    unittest.main()
