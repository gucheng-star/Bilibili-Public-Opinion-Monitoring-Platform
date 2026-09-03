from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from mcp import Client, StdioServerParameters

from agent_mcp.read_only_service import AgentReadOnlyError, ReadOnlyService
from agent_mcp.contracts import (
    AnalysisOverviewOutput,
    LLMSentimentDistribution,
    NLPSentimentDistribution,
)
from agent_mcp.server import mcp


SENSITIVE_SENTINELS = (
    "COOKIE_SENTINEL_AGENT_MCP",
    "APIKEY_SENTINEL_AGENT_MCP",
    "PATH_SENTINEL_AGENT_MCP",
)


class AgentMCPFixtureMixin:
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "fixture.db"
        self._create_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create_fixture(self) -> None:
        connection = sqlite3.connect(self.database_path)
        connection.executescript(
            """
            CREATE TABLE analyses (
                id INTEGER PRIMARY KEY,
                bv TEXT NOT NULL,
                video_title TEXT,
                video_cover TEXT,
                status TEXT,
                mode TEXT,
                total_comments INTEGER,
                created_at TEXT,
                error_msg TEXT
            );
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY,
                analysis_id INTEGER NOT NULL,
                rpid INTEGER,
                root_rpid INTEGER,
                parent_rpid INTEGER,
                username TEXT,
                gender TEXT,
                ip_location TEXT,
                content TEXT,
                likes INTEGER,
                sentiment_label TEXT,
                sentiment_llm_label TEXT,
                post_time TEXT
            );
            """
        )
        connection.executescript(
            """
            ALTER TABLE analyses ADD COLUMN sentiment_llm_schema_version INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE comments ADD COLUMN sentiment_llm_style TEXT;
            ALTER TABLE comments ADD COLUMN sentiment_llm_schema_version INTEGER NOT NULL DEFAULT 0;
            """
        )
        connection.executemany(
            "INSERT INTO analyses (id,bv,video_title,video_cover,status,mode,total_comments,created_at,error_msg) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (1, "BV1NLP", "中文 NLP 样本", SENSITIVE_SENTINELS[2], "done", "nlp", 4, "2026-08-01T08:00:00", SENSITIVE_SENTINELS[1]),
                (2, "BV1LLM", "十分类样本", "", "done", "llm", 2, "2026-08-02T08:00:00", ""),
                (3, "BV1INCOMPLETE", "未完成十分类", "", "done", "nlp", 1, "2026-08-03T08:00:00", ""),
                (4, "BV1PENDING", "仍在分析", "", "analyzing", "nlp", 0, "2026-08-04T08:00:00", ""),
            ],
        )
        comments = [
            (1, 1, 101, None, None, SENSITIVE_SENTINELS[0], "男", "IP属地：广东", "共同观点", 8, "positive", "", "2026-08-01T09:00:00"),
            (2, 1, 102, None, 101, "用户乙", "女", "广东", "共同观点", 3, "positive", "", "2026-08-01T10:00:00"),
            (3, 1, 103, None, None, "用户丙", "", "北京", "不同观点_%_测试", 2, "negative", "", "2026-08-01T11:00:00"),
            (4, 1, 104, None, None, "用户丁", "", "未知", "长文本" + "🙂" * 400, 0, "neutral", "", "2026-08-01T12:00:00"),
            (5, 2, 201, None, None, "用户甲", "男", "上海", "支持这个方案", 6, "positive", "support", "2026-08-02T09:00:00"),
            (6, 2, 202, None, None, "用户乙", "女", "上海", "仍然有些担忧", 4, "negative", "concern", "2026-08-02T10:00:00"),
            (7, 3, 301, None, None, "用户甲", "", "", "没有大模型标签", 0, "neutral", "", "2026-08-03T09:00:00"),
        ]
        connection.executemany("INSERT INTO comments (id,analysis_id,rpid,root_rpid,parent_rpid,username,gender,ip_location,content,likes,sentiment_label,sentiment_llm_label,post_time) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", comments)
        connection.execute("UPDATE analyses SET sentiment_llm_schema_version=2 WHERE id=2")
        connection.execute("UPDATE comments SET sentiment_llm_label='trust', sentiment_llm_style='plain', sentiment_llm_schema_version=2 WHERE id=5")
        connection.execute("UPDATE comments SET sentiment_llm_label='fear', sentiment_llm_style='rhetorical', sentiment_llm_schema_version=2 WHERE id=6")
        connection.commit()
        connection.close()

    def service(self) -> ReadOnlyService:
        return ReadOnlyService(self.database_path)


class ReadOnlyServiceTests(AgentMCPFixtureMixin, unittest.TestCase):
    def _digest(self) -> str:
        return hashlib.sha256(self.database_path.read_bytes()).hexdigest()

    def test_lists_only_done_records_with_stable_paging_and_llm_readiness(self):
        first = self.service().list_analyses(limit=2, offset=0)
        second = self.service().list_analyses(limit=2, offset=2)

        self.assertEqual(first["total_count"], 3)
        self.assertEqual([item["analysis_id"] for item in first["items"]], [3, 2])
        self.assertEqual([item["analysis_id"] for item in second["items"]], [1])
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        llm = next(item for item in first["items"] if item["analysis_id"] == 2)
        self.assertEqual(llm["llm_schema_version"], 2)
        self.assertTrue(llm["has_v2_llm_labels"])

    def test_overview_matches_product_semantics_and_reports_limits(self):
        overview = self.service().get_analysis_overview(1, "nlp")

        self.assertEqual(sum(overview["sentiment_distribution"].values()), overview["sentiment_denominator"])
        self.assertEqual(overview["sentiment_denominator"], 4)
        self.assertEqual(overview["duplicate_statistics"]["group_count"], 1)
        self.assertEqual(overview["duplicate_statistics"]["involved_comments"], 2)
        self.assertEqual(overview["top_regions"][0]["region"], "广东")
        self.assertEqual(overview["time_range"]["earliest"], "2026-08-01T09:00:00")
        self.assertTrue(overview["data_complete"])
        self.assertTrue(any("地域占比" in item for item in overview["limitations"]))

    def test_llm_mode_requires_all_labels_and_never_triggers_analysis(self):
        complete = self.service().get_analysis_overview(2, "llm")
        self.assertEqual(complete["sentiment_distribution"]["trust"], 1)
        self.assertEqual(complete["sentiment_distribution"]["fear"], 1)
        self.assertEqual(complete["style_distribution"]["rhetorical"], 1)

        with self.assertRaisesRegex(AgentReadOnlyError, "尚未完成大模型情绪分析"):
            self.service().get_analysis_overview(3, "llm")

    def test_search_is_bounded_private_and_uses_exact_contains_semantics(self):
        response = self.service().search_comments(1, keyword="_%_", limit=50)
        self.assertEqual(response["matched_count"], 1)
        self.assertEqual(response["returned_count"], 1)
        self.assertEqual(response["comments"][0]["content"], "不同观点_%_测试")

        long_response = self.service().search_comments(1, keyword="长文本", limit=50)
        self.assertLessEqual(len(long_response["comments"][0]["content"]), 240)
        serialized = json.dumps(long_response, ensure_ascii=False)
        for sentinel in SENSITIVE_SENTINELS:
            self.assertNotIn(sentinel, serialized)
        self.assertNotIn("username", serialized)
        self.assertNotIn("rpid", serialized)

    def test_fifty_item_page_never_skips_records_at_character_budget(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "INSERT INTO analyses (id,bv,video_title,video_cover,status,mode,total_comments,created_at,error_msg) VALUES (?,?,?,?,?,?,?,?,?)",
            (5, "BV1PAGING", "分页边界", "", "done", "nlp", 55, "2026-08-05T08:00:00", ""),
        )
        connection.executemany(
            "INSERT INTO comments (id,analysis_id,rpid,root_rpid,parent_rpid,username,gender,ip_location,content,likes,sentiment_label,sentiment_llm_label,post_time) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    100 + index, 5, 500 + index, None, None, "用户", "", "广东",
                    f"分页-{index:02d}-" + "长" * 300, 0, "neutral", "", f"2026-08-05T{index % 24:02d}:00:00",
                )
                for index in range(55)
            ],
        )
        connection.commit()
        connection.close()

        first = self.service().search_comments(5, limit=50, offset=0)
        second = self.service().search_comments(5, limit=50, offset=50)
        self.assertEqual(first["returned_count"], 50)
        self.assertTrue(first["has_more"])
        self.assertEqual(second["returned_count"], 5)
        self.assertFalse(second["has_more"])
        contents = [item["content"] for item in first["comments"] + second["comments"]]
        self.assertEqual(len(contents), len(set(contents)))
        self.assertTrue(all(len(content) <= 240 for content in contents))

    def test_invalid_arguments_and_unavailable_records_are_actionable(self):
        for operation, message in (
            (lambda: self.service().list_analyses(limit=0), "limit"),
            (lambda: self.service().list_analyses(offset=100_001), "offset"),
            (lambda: self.service().get_analysis_overview(0), "analysis_id"),
            (lambda: self.service().get_analysis_overview(999), "未找到"),
            (lambda: self.service().get_analysis_overview(4), "尚未完成"),
            (lambda: self.service().search_comments(1, sentiment="support"), "sentiment"),
            (lambda: self.service().search_comments(1, keyword="密" * 101), "keyword"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(AgentReadOnlyError, message):
                    operation()

    def test_connection_rejects_writes_ddl_pragmas_attach_and_sensitive_columns(self):
        before = self._digest()
        before_entries = sorted(path.name for path in self.database_path.parent.iterdir())
        connection = self.service()._connect()
        try:
            attempts = (
                "INSERT INTO analyses (id,bv,status) VALUES (9,'BV9','done')",
                "UPDATE analyses SET video_title='changed' WHERE id=1",
                "DELETE FROM comments WHERE id=1",
                "CREATE TABLE forbidden (id INTEGER)",
                "PRAGMA user_version=9",
                "ATTACH DATABASE ':memory:' AS other",
                "SELECT username FROM comments LIMIT 1",
                "SELECT error_msg FROM analyses LIMIT 1",
            )
            for statement in attempts:
                with self.subTest(statement=statement):
                    with self.assertRaises(sqlite3.DatabaseError):
                        connection.execute(statement).fetchall()
            self.assertEqual(connection.total_changes, 0)
        finally:
            connection.close()

        self.assertEqual(self._digest(), before)
        self.assertEqual(sorted(path.name for path in self.database_path.parent.iterdir()), before_entries)

    def test_database_path_must_be_absolute_local_regular_backup_without_sidecars(self):
        unsafe_inputs = (
            "fixture.db",
            r"\\server\share\fixture.db",
            r"\\.\PhysicalDrive0",
            self.database_path.with_name(f"{self.database_path.name}-wal"),
        )
        for unsafe in unsafe_inputs:
            with self.subTest(unsafe=str(unsafe)):
                with self.assertRaisesRegex(AgentReadOnlyError, "静态副本要求") as raised:
                    ReadOnlyService(unsafe)
                self.assertNotIn(str(unsafe), raised.exception.message)

        sidecar = Path(f"{self.database_path}-wal")
        sidecar.touch()
        try:
            with self.assertRaisesRegex(AgentReadOnlyError, "静态副本要求"):
                self.service()
        finally:
            sidecar.unlink()

        with patch.object(ReadOnlyService, "_has_reparse_component", return_value=True):
            with self.assertRaisesRegex(AgentReadOnlyError, "静态副本要求"):
                self.service()

    def test_sentiment_contracts_are_explicit_and_bound_to_the_selected_mode(self):
        nlp_payload = self.service().get_analysis_overview(1, "nlp")
        llm_payload = self.service().get_analysis_overview(2, "llm")
        nlp = AnalysisOverviewOutput.model_validate(nlp_payload)
        llm = AnalysisOverviewOutput.model_validate(llm_payload)

        self.assertIsInstance(nlp.sentiment_distribution, NLPSentimentDistribution)
        self.assertEqual(set(nlp.sentiment_distribution.model_dump()), {"positive", "negative", "neutral"})
        self.assertIsInstance(llm.sentiment_distribution, LLMSentimentDistribution)
        self.assertEqual(len(llm.sentiment_distribution.model_dump()), 9)
        self.assertEqual(len(llm.style_distribution.model_dump()), 5)

        mismatched = dict(nlp_payload)
        mismatched["sentiment_distribution"] = llm_payload["sentiment_distribution"]
        with self.assertRaises(ValueError):
            AnalysisOverviewOutput.model_validate(mismatched)

    def test_schema_signature_rejects_missing_or_incompatible_columns(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute("ALTER TABLE comments RENAME COLUMN sentiment_llm_label TO incompatible_label")
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(AgentReadOnlyError, "Schema v1") as raised:
            self.service().list_analyses()
        self.assertEqual(raised.exception.code, "unsupported_database_schema")
        self.assertNotIn(str(self.database_path), raised.exception.message)

    def test_comment_loading_has_product_aligned_hard_limit(self):
        with patch("agent_mcp.read_only_service.MAX_ANALYSIS_COMMENTS", 3):
            with self.assertRaisesRegex(AgentReadOnlyError, "3 条评论读取上限") as raised:
                self.service().get_analysis_overview(1)
        self.assertEqual(raised.exception.code, "analysis_too_large")

    def test_query_deadline_interrupts_work_without_exposing_sql(self):
        with (
            patch("agent_mcp.read_only_service.QUERY_TIMEOUT_SECONDS", 0),
            patch("agent_mcp.read_only_service.QUERY_PROGRESS_STEPS", 1),
        ):
            with self.assertRaisesRegex(AgentReadOnlyError, "只读查询时限") as raised:
                self.service().list_analyses()
        self.assertEqual(raised.exception.code, "query_timeout")
        self.assertNotIn("SELECT", raised.exception.message)


class MCPProtocolTests(AgentMCPFixtureMixin, unittest.IsolatedAsyncioTestCase):
    async def test_in_memory_client_discovers_schemas_annotations_and_calls_tools(self):
        with patch.dict(os.environ, {"BILI_MCP_DB_PATH": str(self.database_path)}):
            async with Client(mcp) as client:
                listed = await client.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                self.assertEqual(set(tools), {
                    "bili_list_analyses",
                    "bili_get_analysis_overview",
                    "bili_search_comments",
                })
                for tool in tools.values():
                    self.assertFalse(tool.input_schema.get("additionalProperties", True))
                    self.assertIsNotNone(tool.output_schema)
                    self.assertFalse(tool.output_schema.get("additionalProperties", True))
                    self.assertTrue(tool.annotations.read_only_hint)
                    self.assertFalse(tool.annotations.destructive_hint)
                    self.assertTrue(tool.annotations.idempotent_hint)
                    self.assertFalse(tool.annotations.open_world_hint)

                result = await client.call_tool("bili_get_analysis_overview", {"analysis_id": 1})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["sentiment_denominator"], 4)
                self.assertEqual(
                    set(result.structured_content["sentiment_distribution"]),
                    {"positive", "negative", "neutral"},
                )
                self.assertIn("情绪分母为 4", result.content[0].text)

                error = await client.call_tool("bili_get_analysis_overview", {"analysis_id": 999})
                self.assertTrue(error.is_error)
                self.assertIn("未找到指定的分析记录", error.content[0].text)
                self.assertNotIn(str(self.database_path), error.content[0].text)

                sentinel = "COOKIE_SENTINEL_IN_INVALID_EXTRA_ARGUMENT"
                invalid = await client.call_tool("bili_list_analyses", {"unexpected": sentinel})
                self.assertTrue(invalid.is_error)
                self.assertIn("工具参数不合法", invalid.content[0].text)
                self.assertNotIn(sentinel, invalid.content[0].text)

                invalid_mode = await client.call_tool("bili_search_comments", {
                    "analysis_id": 1,
                    "mode": {"secret": sentinel},
                })
                self.assertTrue(invalid_mode.is_error)
                self.assertIn("工具参数不合法", invalid_mode.content[0].text)
                self.assertNotIn(sentinel, invalid_mode.content[0].text)

                unknown_name = await client.call_tool(sentinel, {})
                self.assertTrue(unknown_name.is_error)
                self.assertIn("工具名称不合法", unknown_name.content[0].text)
                self.assertNotIn(sentinel, unknown_name.content[0].text)

                nlp_distribution_schema = tools["bili_get_analysis_overview"].output_schema["properties"]["sentiment_distribution"]
                self.assertIn("anyOf", nlp_distribution_schema)
                self.assertNotIn("additionalProperties", nlp_distribution_schema)

    async def test_real_stdio_client_starts_calls_and_exits_cleanly(self):
        server_path = Path(__file__).resolve().parents[1] / "agent_mcp" / "server.py"
        environment = dict(os.environ)
        environment["BILI_MCP_DB_PATH"] = str(self.database_path)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(server_path)],
            env=environment,
            cwd=str(server_path.parent.parent),
        )
        async with Client(parameters, read_timeout_seconds=10) as client:
            listed = await client.list_tools()
            self.assertEqual(len(listed.tools), 3)
            result = await client.call_tool("bili_search_comments", {
                "analysis_id": 1,
                "keyword": "共同观点",
                "limit": 1,
            })
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["matched_count"], 2)
            self.assertEqual(result.structured_content["returned_count"], 1)
            self.assertTrue(result.structured_content["has_more"])


if __name__ == "__main__":
    unittest.main()
