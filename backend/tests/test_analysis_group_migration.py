import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from models import database


class AnalysisGroupMigrationTests(unittest.TestCase):
    def test_ai_summary_migration_rebuilds_legacy_unique_constraint_even_when_columns_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-summary-constraint.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.execute("DROP TABLE ai_summaries")
                connection.execute(
                    "CREATE TABLE ai_summaries (id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, "
                    "filter_json TEXT NOT NULL, filter_hash VARCHAR(64) NOT NULL, "
                    "interpretation_view VARCHAR(30) NOT NULL DEFAULT 'public_opinion', "
                    "report_mode VARCHAR(10) NOT NULL DEFAULT 'quick', "
                    "thinking_status VARCHAR(20) NOT NULL DEFAULT 'disabled', "
                    "input_hash VARCHAR(64) NOT NULL, summary_text TEXT NOT NULL, "
                    "provider VARCHAR(30) NOT NULL, model VARCHAR(100) NOT NULL, "
                    "matched_count INTEGER, sampled_count INTEGER, created_at DATETIME, updated_at DATETIME, "
                    "UNIQUE (analysis_id, filter_hash), "
                    "UNIQUE (analysis_id, filter_hash, interpretation_view, report_mode))"
                )
                connection.execute("INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1LEGACY', 1)")
                connection.commit()
                connection.close()

                self.assertTrue(database._ai_summary_role_migration_required(engine))
                database._migrate(engine)
                self.assertFalse(database._ai_summary_role_migration_required(engine))
            finally:
                engine.dispose()

    def test_ai_summary_role_migration_preserves_legacy_cache_and_allows_combinations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-summary.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.execute("DROP TABLE ai_summaries")
                connection.execute(
                    "CREATE TABLE ai_summaries (id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, "
                    "filter_json TEXT NOT NULL, filter_hash VARCHAR(64) NOT NULL, input_hash VARCHAR(64) NOT NULL, "
                    "summary_text TEXT NOT NULL, provider VARCHAR(30) NOT NULL, model VARCHAR(100) NOT NULL, "
                    "matched_count INTEGER, sampled_count INTEGER, created_at DATETIME, updated_at DATETIME, "
                    "UNIQUE (analysis_id, filter_hash))"
                )
                connection.execute(
                    "CREATE INDEX ix_ai_summaries_analysis_id ON ai_summaries (analysis_id)"
                )
                connection.execute("INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1LEGACY', 1)")
                connection.execute(
                    "INSERT INTO ai_summaries VALUES (1, 1, '{}', 'filter', 'input', '旧简报', 'custom', 'model', 1, 1, NULL, NULL)"
                )
                connection.commit()
                connection.close()

                self.assertTrue(database._ai_summary_role_migration_required(engine))
                database._migrate(engine)
                database._validate_schema(engine)
                connection = sqlite3.connect(path)
                self.assertEqual(connection.execute(
                    "SELECT interpretation_view, report_mode, thinking_status, summary_text FROM ai_summaries"
                ).fetchone(), ("public_opinion", "quick", "disabled", "旧简报"))
                connection.execute(
                    "INSERT INTO ai_summaries (analysis_id, filter_json, filter_hash, interpretation_view, report_mode, thinking_status, input_hash, summary_text, provider, model) "
                    "VALUES (1, '{}', 'filter', 'creator', 'quick', 'disabled', 'input', '另一简报', 'custom', 'model')"
                )
                connection.commit()
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM ai_summaries").fetchone()[0], 2)
                connection.close()
            finally:
                engine.dispose()

    def test_migration_preserves_labels_when_partial_tables_lack_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-taxonomy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE comments (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "sentiment_llm_label VARCHAR(20), sentiment_llm_style VARCHAR(20))"
            )
            connection.execute(
                "CREATE TABLE sentiment_results (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "llm_neutral INTEGER, llm_support INTEGER, llm_fear INTEGER, llm_sarcasm INTEGER)"
            )
            connection.executemany(
                "INSERT INTO comments (id, analysis_id, sentiment_llm_label, sentiment_llm_style) "
                "VALUES (?, 7, ?, ?)",
                [
                    (1, "trust", "plain"),
                    (2, "fear", "plain"),
                    (3, "anger", "sarcasm"),
                    (4, "anger", "plain"),
                ],
            )
            connection.execute(
                "INSERT INTO sentiment_results "
                "(id, analysis_id, llm_neutral, llm_support, llm_fear, llm_sarcasm) "
                "VALUES (1, 7, 61, 62, 63, 64)"
            )
            connection.commit()
            connection.close()
            engine = create_engine(f"sqlite:///{path}")
            try:
                database._migrate(engine)
                connection = sqlite3.connect(path)
                labels = [
                    row[0] for row in connection.execute(
                        "SELECT sentiment_llm_label FROM comments ORDER BY id"
                    )
                ]
                comment_versions = connection.execute(
                    "SELECT sentiment_llm_schema_version FROM comments ORDER BY id"
                ).fetchall()
                summary_version = connection.execute(
                    "SELECT sentiment_llm_schema_version, llm_neutral, llm_support, llm_fear, llm_sarcasm "
                    "FROM sentiment_results WHERE analysis_id = 7"
                ).fetchone()
                connection.close()
                self.assertEqual(labels, ["trust", "fear", "anger", "anger"])
                self.assertEqual(comment_versions, [(0,), (0,), (1,), (1,)])
                self.assertEqual(summary_version, (0, 61, 62, 63, 64))
            finally:
                engine.dispose()

    def test_existing_sqlite_is_backed_up_before_event_schema_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE analyses (id INTEGER PRIMARY KEY, bv VARCHAR(20))")
            connection.commit()
            connection.close()
            engine = create_engine(f"sqlite:///{path}")
            try:
                with patch.object(database, "DB_PATH", str(path)):
                    self.assertTrue(database._schema_change_required(engine))
                    backup = database._backup_database()
                    self.assertIsNotNone(backup)
                    self.assertTrue(backup.exists())
                    database.Base.metadata.create_all(engine)
                    database._migrate(engine)
                    database._validate_schema(engine)
                tables = set(inspect(engine).get_table_names())
                self.assertTrue({"analysis_groups", "analysis_group_items", "analysis_group_summaries"} <= tables)
            finally:
                engine.dispose()

    def test_failed_event_migration_restores_the_live_legacy_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE analyses (id INTEGER PRIMARY KEY, bv VARCHAR(20))")
            connection.execute("INSERT INTO analyses (id, bv) VALUES (1, 'BV1LEGACY')")
            connection.commit()
            connection.close()
            engine = create_engine(f"sqlite:///{path}")
            original_create_all = database.Base.metadata.create_all

            def fail_after_partial_schema(target_engine):
                original_create_all(target_engine)
                raise RuntimeError("injected migration failure")

            try:
                with (
                    patch.object(database, "DB_PATH", str(path)),
                    patch.object(database, "engine", engine),
                    patch.object(database.Base.metadata, "create_all", side_effect=fail_after_partial_schema),
                ):
                    with self.assertRaisesRegex(RuntimeError, "数据库迁移失败"):
                        database.init_db()
                engine.dispose()
                connection = sqlite3.connect(path)
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertEqual(tables, {"analyses"})
                self.assertEqual(connection.execute("SELECT bv FROM analyses WHERE id=1").fetchone()[0], "BV1LEGACY")
                self.assertEqual(
                    {row[1] for row in connection.execute("PRAGMA table_info(analyses)")}, {"id", "bv"},
                )
                connection.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
