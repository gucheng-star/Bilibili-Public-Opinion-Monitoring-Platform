import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from models import database


class DanmakuMigrationTests(unittest.TestCase):
    def test_comment_collection_contract_backfills_existing_analysis_counts_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-comment-collection.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("""
                CREATE TABLE analyses (
                    id INTEGER PRIMARY KEY, bv VARCHAR(20), avid INTEGER,
                    status VARCHAR(20), total_comments INTEGER,
                    sentiment_llm_schema_version INTEGER NOT NULL DEFAULT 0
                )
            """)
            connection.execute(
                "INSERT INTO analyses (id, bv, avid, status, total_comments) VALUES (1, 'BV1LEGACY', 1, 'done', 17)",
            )
            connection.commit()
            connection.close()
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                database._migrate(engine)
                database._validate_schema(engine)
                connection = sqlite3.connect(path)
                row = connection.execute("""
                    SELECT comment_target_count, comment_fetched_count, comment_collection_status,
                           comment_termination_reason, comment_error_summary
                    FROM analyses WHERE id = 1
                """).fetchone()
                self.assertEqual(row, (17, 17, "completed", "legacy_record", None))
                connection.close()
            finally:
                engine.dispose()

    def test_existing_database_is_backed_up_before_danmaku_tables_are_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE analyses (id INTEGER PRIMARY KEY, bv VARCHAR(20))")
            connection.execute("INSERT INTO analyses (id, bv) VALUES (1, 'BV1LEGACY')")
            connection.commit()
            connection.close()
            engine = create_engine(f"sqlite:///{path}")
            try:
                with patch.object(database, "DB_PATH", str(path)):
                    self.assertTrue(database._schema_change_required(engine))
                    backup = database._backup_database()
                    self.assertIsNotNone(backup)
                    database.Base.metadata.create_all(engine)
                    database._migrate(engine)
                    database._validate_schema(engine)
                tables = set(inspect(engine).get_table_names())
                self.assertTrue({"danmaku_analyses", "danmaku_samples"} <= tables)
                connection = sqlite3.connect(path)
                self.assertEqual(connection.execute("SELECT bv FROM analyses").fetchone()[0], "BV1LEGACY")
                columns = {item[1] for item in connection.execute("PRAGMA table_info(analyses)")}
                self.assertTrue({
                    "comment_target_count", "comment_fetched_count", "comment_collection_status",
                    "comment_termination_reason", "comment_error_summary",
                } <= columns)
                connection.close()
            finally:
                engine.dispose()

    def test_legacy_single_attempt_table_is_rebuilt_without_losing_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-danmaku.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            connection = None
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.execute("DROP TABLE danmaku_samples")
                connection.execute("DROP TABLE danmaku_analyses")
                connection.execute("""
                    CREATE TABLE danmaku_analyses (
                        id INTEGER PRIMARY KEY, analysis_id INTEGER, bv VARCHAR(20) NOT NULL,
                        avid INTEGER NOT NULL, cid INTEGER NOT NULL, part_index INTEGER NOT NULL,
                        part_title VARCHAR(500) NOT NULL, video_duration_seconds INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL, sample_limit INTEGER NOT NULL,
                        segment_count INTEGER NOT NULL, requested_segments INTEGER NOT NULL,
                        requested_segment_indexes TEXT NOT NULL, successful_segments INTEGER NOT NULL,
                        kept_count INTEGER NOT NULL, ignored_count INTEGER NOT NULL,
                        failed_segment_indexes TEXT NOT NULL, error_msg TEXT,
                        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                        CONSTRAINT uq_danmaku_analysis_source_part UNIQUE (analysis_id, part_index)
                    )
                """)
                connection.execute("""
                    CREATE TABLE danmaku_samples (
                        id INTEGER PRIMARY KEY, danmaku_analysis_id INTEGER NOT NULL,
                        content TEXT NOT NULL, progress_ms INTEGER NOT NULL, segment_index INTEGER NOT NULL,
                        sentiment_label VARCHAR(10), sentiment_score FLOAT, created_at DATETIME NOT NULL,
                        FOREIGN KEY(danmaku_analysis_id) REFERENCES danmaku_analyses(id)
                    )
                """)
                connection.execute("INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1LEGACY', 1)")
                connection.execute("""
                    INSERT INTO danmaku_analyses VALUES
                    (1, 1, 'BV1LEGACY', 1, 2, 1, 'P1', 60, 'done', 100, 1, 1, '[0]', 1, 1, 0, '[]', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """)
                connection.execute("""
                    INSERT INTO danmaku_samples VALUES
                    (1, 1, '旧样本', 1000, 0, NULL, NULL, CURRENT_TIMESTAMP)
                """)
                connection.commit()
                connection.close()

                self.assertTrue(database._schema_change_required(engine))
                database._migrate(engine)
                database._validate_schema(engine)
                connection = sqlite3.connect(path)
                self.assertEqual(connection.execute("SELECT attempt_index FROM danmaku_analyses WHERE id = 1").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT content FROM danmaku_samples WHERE id = 1").fetchone()[0], "旧样本")
                connection.execute("""
                    INSERT INTO danmaku_analyses (
                        analysis_id, bv, avid, cid, part_index, part_title, attempt_index,
                        video_duration_seconds, status, sample_limit, segment_count,
                        requested_segments, requested_segment_indexes, successful_segments,
                        kept_count, ignored_count, failed_segment_indexes, created_at, updated_at
                    ) VALUES (1, 'BV1LEGACY', 1, 2, 1, 'P1', 2, 60, 'pending', 100, 1, 0, '[]', 0, 0, 0, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """)
                connection.commit()
                connection.close()
                connection = None
            finally:
                if connection:
                    connection.close()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
