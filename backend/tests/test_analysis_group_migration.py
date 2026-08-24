import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from models import database


class AnalysisGroupMigrationTests(unittest.TestCase):
    def test_migration_normalizes_legacy_labels_and_rebuilds_ten_class_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-taxonomy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE comments (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "sentiment_llm_label VARCHAR(20), sentiment_llm_style VARCHAR(20))"
            )
            connection.execute(
                "CREATE TABLE sentiment_results (id INTEGER PRIMARY KEY, analysis_id INTEGER)"
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
            connection.execute("INSERT INTO sentiment_results (id, analysis_id) VALUES (1, 7)")
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
                counts = connection.execute(
                    "SELECT llm_support, llm_concern, llm_sarcasm, llm_anger, "
                    "llm_trust, llm_fear FROM sentiment_results WHERE analysis_id = 7"
                ).fetchone()
                connection.close()
                self.assertEqual(labels, ["support", "concern", "sarcasm", "anger"])
                self.assertEqual(counts, (1, 1, 1, 1, 0, 0))
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
