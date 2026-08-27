import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import logging_config


class DevLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = Path(self.temp_dir.name) / "workspace"
        self.log_dir = self.workspace_dir / "logs" / "dev" / "test-session"
        self.workspace = patch.object(logging_config, "_WORKSPACE_DIR", self.workspace_dir)
        self.workspace.start()
        self.environ = patch.dict(os.environ, {}, clear=True)
        self.environ.start()
        logging_config.configure_dev_logging()

    def tearDown(self):
        os.environ["BILI_DEV_LOGGING"] = "0"
        logging_config.configure_dev_logging()
        self.environ.stop()
        self.workspace.stop()
        self.temp_dir.cleanup()

    def _enable(self, **extra):
        os.environ.update({
            "BILI_DEV_LOGGING": "1",
            "BILI_DEV_LOG_DIR": str(self.log_dir),
            "BILI_DEV_SESSION_ID": "test-session",
            **extra,
        })
        self.assertTrue(logging_config.configure_dev_logging())

    def _lines(self):
        return [json.loads(line) for line in (self.log_dir / "backend.log").read_text(encoding="utf-8").splitlines()]

    def test_disabled_does_not_create_log_file(self):
        self.assertFalse(logging_config.configure_dev_logging())
        self.assertFalse(logging_config.dev_logging_ready())
        logging_config.log_event(logging_config.get_logger("disabled"), "INFO", "ignored", "nothing")
        self.assertFalse(self.log_dir.exists())

    def test_handler_configuration_failure_is_not_reported_as_ready(self):
        os.environ.update({
            "BILI_DEV_LOGGING": "1",
            "BILI_DEV_LOG_DIR": str(self.log_dir),
            "BILI_DEV_SESSION_ID": "test-session",
        })
        with patch.object(logging_config, "_AcknowledgingRotatingFileHandler", side_effect=OSError("directory unavailable")):
            self.assertFalse(logging_config.configure_dev_logging())
        self.assertFalse(logging_config.dev_logging_ready())

    def test_enabled_writes_parseable_jsonl_with_timezone(self):
        self._enable()
        logging_config.log_event(
            logging_config.get_logger("analysis"), "INFO", "task_created", "created",
            analysis_id=12, task_type="analysis", count=3,
        )
        entry = self._lines()[0]
        self.assertEqual(entry["component"], "analysis")
        self.assertEqual(entry["event"], "task_created")
        self.assertEqual(entry["dev_session_id"], "test-session")
        self.assertEqual(entry["analysis_id"], 12)
        self.assertIn("+", entry["timestamp"])

    def test_repeat_configuration_does_not_duplicate_handlers_or_events(self):
        self._enable()
        self.assertTrue(logging_config.configure_dev_logging())
        handlers = [h for h in logging.getLogger(logging_config.DEV_LOGGER_NAME).handlers if getattr(h, "_bili_dev_handler", False)]
        self.assertEqual(len(handlers), 1)
        logging_config.log_event(logging_config.get_logger("repeat"), "INFO", "once", "once")
        self.assertEqual(len(self._lines()), 1)

    def test_line_is_bounded_to_32kb(self):
        self._enable()
        logging_config.log_event(logging_config.get_logger("size"), "ERROR", "large", "中" * 20_000)
        raw = (self.log_dir / "backend.log").read_bytes().splitlines()[0]
        self.assertLessEqual(len(raw), logging_config.MAX_LOG_LINE_BYTES)
        self.assertEqual(json.loads(raw.decode("utf-8"))["event"], "large")

    def test_rotating_handler_uses_required_configuration(self):
        self._enable()
        handler = next(h for h in logging.getLogger(logging_config.DEV_LOGGER_NAME).handlers if isinstance(h, logging_config.RotatingFileHandler))
        self.assertEqual(handler.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 1)

    def test_rotation_keeps_current_and_one_parseable_backup(self):
        self._enable()
        handler = next(
            item for item in logging.getLogger(logging_config.DEV_LOGGER_NAME).handlers
            if isinstance(item, logging_config.RotatingFileHandler)
        )
        handler.maxBytes = 512
        for index in range(20):
            logging_config.log_event(
                logging_config.get_logger("rotation"), "ERROR", "rotation.error",
                "用于验证轮转的错误事件", count=index,
            )
        handler.flush()
        current = self.log_dir / "backend.log"
        backup = self.log_dir / "backend.log.1"
        self.assertTrue(current.exists())
        self.assertTrue(backup.exists())
        for path in (current, backup):
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertEqual(json.loads(line)["event"], "rotation.error")

    def test_log_directory_must_stay_inside_workspace_dev_logs(self):
        outside = Path(self.temp_dir.name) / "outside"
        os.environ.update({
            "BILI_DEV_LOGGING": "1",
            "BILI_DEV_LOG_DIR": str(outside),
            "BILI_DEV_SESSION_ID": "test-session",
        })
        self.assertFalse(logging_config.configure_dev_logging())
        self.assertFalse(outside.exists())

    def test_exception_normalises_workspace_path(self):
        self._enable()
        private_comment = "这是一条不应出现在异常堆栈中的评论"
        try:
            exec(compile(
                f'raise RuntimeError("api_key=secret-value; {private_comment}")',
                str(self.workspace_dir / "synthetic_failure.py"),
                "exec",
            ))
        except RuntimeError as error:
            logging_config.log_event(logging_config.get_logger("failure"), "ERROR", "task_failed", "failed", exception=error)
        entry = self._lines()[0]
        self.assertEqual(entry["error_type"], "RuntimeError")
        self.assertIn("<workspace>/synthetic_failure.py", entry["stack"])
        self.assertNotIn(str(logging_config._WORKSPACE_DIR), entry["stack"])
        self.assertNotIn("secret-value", json.dumps(entry, ensure_ascii=False))
        self.assertNotIn(private_comment, json.dumps(entry, ensure_ascii=False))

    def test_secret_fields_and_known_values_never_reach_disk(self):
        self._enable(BILI_API_KEY="api-secret-value")
        comment = "这是一条不应写入的评论"
        logging_config.log_event(
            logging_config.get_logger("privacy"), "ERROR", "failed",
            "Cookie=abc123; Bearer bearer-secret; qrcode_key=qr-secret",
            cookie="abc123", prompt="prompt-secret", username="alice", uid="42",
            note=comment, value="api-secret-value", context="prompt-secret",
            details={"ordinary": comment, "another": "alice"},
        )
        text = (self.log_dir / "backend.log").read_text(encoding="utf-8")
        for secret in ("abc123", "bearer-secret", "qr-secret", "prompt-secret", "alice", "api-secret-value", comment):
            self.assertNotIn(secret, text)
        self.assertIn("[REDACTED]", text)

    def test_external_traceback_paths_are_collapsed(self):
        self._enable()
        try:
            exec(compile('raise RuntimeError("private")', r"C:\Users\PrivateName\secret.py", "exec"))
        except RuntimeError as error:
            logging_config.log_event(logging_config.get_logger("external"), "ERROR", "failed", "failed", exception=error)
        stack = self._lines()[0]["stack"]
        self.assertIn('File "<external>"', stack)
        self.assertNotIn("PrivateName", stack)
        self.assertNotIn("secret.py", stack)

    def test_standard_library_traceback_paths_are_collapsed(self):
        self._enable()
        try:
            json.loads("{")
        except json.JSONDecodeError as error:
            logging_config.log_event(logging_config.get_logger("stdlib"), "ERROR", "failed", "failed", exception=error)
        stack = self._lines()[0]["stack"]
        self.assertIn('File "<external>"', stack)
        self.assertNotIn("python", stack.lower())
        self.assertNotIn("site-packages", stack.lower())

    def test_request_id_context_is_added_and_reset(self):
        self._enable()
        token = logging_config.set_request_id("request-123")
        self.assertEqual(logging_config.get_request_id(), "request-123")
        logging_config.log_event(logging_config.get_logger("request"), "INFO", "request_completed", "done")
        logging_config.reset_request_id(token)
        self.assertIsNone(logging_config.get_request_id())
        self.assertEqual(self._lines()[0]["request_id"], "request-123")

    def test_frontend_event_returns_true_only_after_a_successful_flush(self):
        self._enable()
        self.assertTrue(logging_config.log_frontend_event("window.error", error_type="TypeError"))
        entry = json.loads((self.log_dir / "frontend.log").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(entry["event"], "window.error")
        self.assertTrue(logging_config.dev_logging_ready())

    def test_frontend_flush_failure_returns_false_and_marks_diagnostics_unready(self):
        self._enable()
        handler = next(
            item for item in logging.getLogger(logging_config.FRONTEND_LOGGER_NAME).handlers
            if getattr(item, "_bili_dev_handler", False)
        )
        with patch.object(handler, "flush", side_effect=OSError("disk full")):
            self.assertFalse(logging_config.log_frontend_event("window.error", error_type="TypeError"))
        self.assertFalse(logging_config.dev_logging_ready())

    def test_backend_logging_failure_is_still_swallowed(self):
        self._enable()

        class FailingHandler(logging.Handler):
            def emit(self, _record):
                raise OSError("local handler fault")

        handler = FailingHandler()
        dev_root = logging.getLogger(logging_config.DEV_LOGGER_NAME)
        dev_root.addHandler(handler)
        try:
            logging_config.log_event(logging_config.get_logger("business"), "ERROR", "failed", "failed")
        finally:
            dev_root.removeHandler(handler)
            handler.close()

    def test_unknown_objects_and_non_whitelist_fields_are_not_serialized(self):
        class UntrustedValue:
            def __str__(self):
                raise AssertionError("logging must not stringify arbitrary objects")

        self._enable()
        logging_config.log_event(
            logging_config.get_logger("safe"), "INFO", "safe_event", "safe",
            analysis_id=UntrustedValue(), comment=UntrustedValue(),
            details={"untrusted": UntrustedValue()},
        )
        entry = self._lines()[0]
        self.assertEqual(entry["analysis_id"], "<UntrustedValue>")
        self.assertNotIn("comment", entry)
        self.assertNotIn("details", entry)


if __name__ == "__main__":
    unittest.main()
