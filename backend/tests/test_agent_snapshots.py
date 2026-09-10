import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx

import main
from agent_mcp.contracts import DataSourceInfoOutput
from agent_mcp.read_only_service import AgentReadOnlyError, ReadOnlyService
from services.agent_snapshots import AgentSnapshotService
from tests.test_agent_mcp import AgentMCPFixtureMixin, SENSITIVE_SENTINELS


class AgentSnapshotServiceTests(AgentMCPFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.snapshot_root = Path(self.temporary.name) / "data" / "agent-snapshots"

    def _service(self) -> AgentSnapshotService:
        return AgentSnapshotService(source_path=self.database_path, root_path=self.snapshot_root)

    def test_sqlite_backup_is_consistent_hashed_and_manifested(self):
        # WAL data is committed but is not required to have been checkpointed to
        # the source database file. SQLite's backup API must include it.
        source = sqlite3.connect(self.database_path)
        source.execute("PRAGMA journal_mode=WAL")
        source.execute(
            "INSERT INTO analyses (id,bv,video_title,status,mode,total_comments,created_at,sentiment_llm_schema_version,comment_collection_status) VALUES (?,?,?,?,?,?,?,?,?)",
            (99, "BV1WAL", "WAL 快照", "done", "nlp", 0, "2026-09-09T01:00:00Z", 0, "completed"),
        )
        source.commit()
        result = self._service().create()
        source.close()

        database = Path(result["database_path"])
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), result["database_sha256"])
        self.assertEqual(manifest["database_sha256"], result["database_sha256"])
        self.assertEqual(manifest["record_counts"], result["record_counts"])
        self.assertEqual(result["record_counts"]["analyses"], 6)
        with closing(sqlite3.connect(database)) as copied:
            self.assertEqual(copied.execute("SELECT bv FROM analyses WHERE id=99").fetchone()[0], "BV1WAL")
        self.assertEqual(sorted(path.name for path in database.parent.iterdir()), ["database.sqlite3", "manifest.json"])

        with patch.dict(os.environ, {"BILI_AGENT_SNAPSHOT_ROOT": str(self.snapshot_root)}):
            source_info = DataSourceInfoOutput.model_validate(ReadOnlyService(database).get_data_source_info())
        self.assertEqual(source_info.snapshot_id, result["snapshot_id"])
        self.assertEqual(source_info.snapshot_created_at, result["created_at"])
        self.assertEqual(source_info.snapshot_time_source, "manifest")
        self.assertEqual(source_info.record_counts, result["record_counts"])

    def test_failure_keeps_published_snapshots_and_removes_own_temporary_directory(self):
        first = self._service().create()
        before = sorted(path.relative_to(self.snapshot_root).as_posix() for path in self.snapshot_root.rglob("*"))
        with patch.object(AgentSnapshotService, "_backup", side_effect=sqlite3.Error("write failed")):
            with self.assertRaisesRegex(Exception, "无法生成 Agent 快照"):
                self._service().create()
        after = sorted(path.relative_to(self.snapshot_root).as_posix() for path in self.snapshot_root.rglob("*"))
        self.assertEqual(after, before)
        self.assertTrue(Path(first["database_path"]).is_file())
        self.assertFalse(any(path.name.startswith(".tmp-") for path in self.snapshot_root.iterdir()))

    def test_tampered_manifest_is_rejected_and_manual_copy_stays_unknown(self):
        result = self._service().create()
        database = Path(result["database_path"])
        manual = Path(self.temporary.name) / "manual-copy.sqlite3"
        shutil.copyfile(database, manual)
        manual_info = ReadOnlyService(manual).get_data_source_info()
        self.assertIsNone(manual_info["snapshot_id"])
        self.assertIsNone(manual_info["snapshot_created_at"])
        self.assertEqual(manual_info["snapshot_time_source"], "unknown")

        manifest_path = Path(result["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with patch.dict(os.environ, {"BILI_AGENT_SNAPSHOT_ROOT": str(self.snapshot_root)}):
            manifest["record_counts"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(AgentReadOnlyError, "快照清单无效"):
                ReadOnlyService(database)
            manifest["record_counts"] = result["record_counts"]
            manifest["database_schema"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(AgentReadOnlyError, "快照清单无效"):
                ReadOnlyService(database)
            manifest["database_schema"] = {
                "read_only_schema_signature": 1,
                "sqlite_user_version": 0,
            }
            manifest["database_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(AgentReadOnlyError, "快照清单无效") as raised:
                ReadOnlyService(database)
        self.assertEqual(raised.exception.code, "invalid_snapshot_manifest")

    def test_snapshot_layout_is_unknown_without_matching_shell_trust_anchor(self):
        result = self._service().create()
        database = Path(result["database_path"])
        foreign_root = Path(self.temporary.name) / "foreign" / "agent-snapshots"
        with patch.dict(os.environ, {"BILI_AGENT_SNAPSHOT_ROOT": str(foreign_root)}):
            info = ReadOnlyService(database).get_data_source_info()
        self.assertIsNone(info["snapshot_id"])
        self.assertEqual(info["snapshot_time_source"], "unknown")


class AgentSnapshotRouteTests(AgentMCPFixtureMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.data_path = Path(self.temporary.name) / "desktop-data"
        self.environment = patch.dict(os.environ, {
            "BILI_DB_PATH": str(self.database_path),
            "BILI_DATA_DIR": str(self.data_path),
            "BILI_DESKTOP_MODE": "1",
            "BILI_LOCAL_TOKEN": "agent-snapshot-test-token",
        }, clear=False)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        super().tearDown()

    async def test_route_returns_only_snapshot_metadata_without_secrets(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=("127.0.0.1", 50000)),
            base_url="http://testserver",
        ) as client:
            rejected = await client.post("/api/agent-snapshots")
            response = await client.post(
                "/api/agent-snapshots", headers={"X-Bili-Local-Token": "agent-snapshot-test-token"},
            )
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {
            "snapshot_id", "created_at", "database_path", "manifest_path", "database_sha256",
            "application_version", "mcp_contract_version", "record_counts",
        })
        self.assertEqual(payload["record_counts"], {"analyses": 5, "comments": 9, "events": 2})
        serialized = json.dumps(payload, ensure_ascii=False)
        for sentinel in SENSITIVE_SENTINELS:
            self.assertNotIn(sentinel, serialized)
        with patch.dict(os.environ, {"BILI_AGENT_SNAPSHOT_ROOT": str(self.data_path / "agent-snapshots")}):
            snapshot_info = ReadOnlyService(Path(payload["database_path"])).get_data_source_info()
        self.assertEqual(snapshot_info["snapshot_id"], payload["snapshot_id"])

    async def test_route_rejects_non_desktop_process(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=("127.0.0.1", 50000)),
            base_url="http://testserver",
        ) as client:
            with patch.dict(os.environ, {"BILI_DESKTOP_MODE": "0"}):
                response = await client.post("/api/agent-snapshots")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
