import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_entry


class DesktopSnapshotBootstrapTests(unittest.TestCase):
    def test_exact_bootstrap_argument_exits_without_starting_desktop_server(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(desktop_entry.sys, "argv", ["BiliOpinionBackend.exe", "--create-agent-snapshot"]),
            patch.object(desktop_entry, "create_agent_snapshot_for_bootstrap", return_value=0) as create,
            self.assertRaises(SystemExit) as exited,
        ):
            desktop_entry.main()
        self.assertEqual(exited.exception.code, 0)
        create.assert_called_once_with()

    def test_requires_shell_bootstrap_marker(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(desktop_entry.create_agent_snapshot_for_bootstrap(), 2)

    def test_publishes_a_nonce_bound_record_without_starting_http(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "agent-snapshots").mkdir()
            result = {"snapshot_id": "snapshot", "database_path": str(Path(temporary) / "database.sqlite3")}
            with (
                patch.dict(os.environ, {
                    "BILI_AGENT_BOOTSTRAP": "1",
                    "BILI_AGENT_BOOTSTRAP_NONCE": "a" * 32,
                }, clear=True),
                patch("services.agent_snapshots.AgentSnapshotService.create", return_value=result),
                patch("services.runtime_paths.data_dir", return_value=Path(temporary)),
            ):
                self.assertEqual(desktop_entry.create_agent_snapshot_for_bootstrap(), 0)
            record = json.loads((Path(temporary) / "agent-snapshots" / "latest-bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(record, {"schema": 1, "nonce": "a" * 32, "snapshot": result})


if __name__ == "__main__":
    unittest.main()
