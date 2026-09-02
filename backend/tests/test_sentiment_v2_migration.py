import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from models import database


class SentimentV2MigrationTests(unittest.TestCase):
    def test_new_database_declares_all_three_schema_version_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "new.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                inspector = inspect(engine)
                for table in ("analyses", "comments", "sentiment_results"):
                    version_column = next(
                        column for column in inspector.get_columns(table)
                        if column["name"] == "sentiment_llm_schema_version"
                    )
                    self.assertFalse(version_column["nullable"])
                    self.assertEqual(str(version_column["default"]).strip("'"), "0")

                connection = sqlite3.connect(path)
                connection.execute("INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1DEFAULT', 1)")
                connection.execute(
                    "INSERT INTO comments (id, analysis_id, rpid, post_time) "
                    "VALUES (1, 1, 1, '2026-09-02 00:00:00')"
                )
                connection.execute("INSERT INTO sentiment_results (id, analysis_id) VALUES (1, 1)")
                defaults = connection.execute(
                    "SELECT (SELECT sentiment_llm_schema_version FROM analyses WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM comments WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM sentiment_results WHERE id = 1)"
                ).fetchone()
                connection.close()
                self.assertEqual(defaults, (0, 0, 0))
            finally:
                engine.dispose()

    def test_legacy_labels_are_versioned_without_rewriting_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE analyses (id INTEGER PRIMARY KEY, bv VARCHAR(20))")
            connection.execute(
                "CREATE TABLE comments (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "sentiment_llm_label VARCHAR(20), sentiment_llm_style VARCHAR(20))"
            )
            connection.execute(
                "CREATE TABLE sentiment_results (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "llm_neutral INTEGER, llm_support INTEGER, llm_fear INTEGER, llm_sarcasm INTEGER)"
            )
            connection.executemany("INSERT INTO analyses (id, bv) VALUES (?, ?)", [
                (1, "BV1COMPLETE"), (2, "BV1PARTIAL"), (3, "BV1INVALID"),
            ])
            connection.executemany(
                "INSERT INTO comments (id, analysis_id, sentiment_llm_label, sentiment_llm_style) "
                "VALUES (?, ?, ?, ?)",
                [
                    (1, 1, "support", "plain"),
                    (2, 1, "sarcasm", "sarcasm"),
                    (3, 2, "joy", "plain"),
                    (4, 2, "", "plain"),
                    (5, 3, "trust", "plain"),
                    (6, 3, "fear", "plain"),
                ],
            )
            connection.executemany(
                "INSERT INTO sentiment_results "
                "(id, analysis_id, llm_neutral, llm_support, llm_fear, llm_sarcasm) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(1, 1, 11, 12, 13, 14), (2, 2, 21, 22, 23, 24), (3, 3, 31, 32, 33, 34)],
            )
            connection.commit()
            connection.close()

            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                database._migrate(engine)
                database._migrate(engine)
                connection = sqlite3.connect(path)
                comments = connection.execute(
                    "SELECT analysis_id, sentiment_llm_label, sentiment_llm_style, "
                    "sentiment_llm_schema_version FROM comments ORDER BY id"
                ).fetchall()
                analyses = connection.execute(
                    "SELECT id, sentiment_llm_schema_version FROM analyses ORDER BY id"
                ).fetchall()
                summaries = connection.execute(
                    "SELECT analysis_id, sentiment_llm_schema_version, "
                    "llm_neutral, llm_support, llm_fear, llm_sarcasm "
                    "FROM sentiment_results ORDER BY analysis_id"
                ).fetchall()
                connection.close()

                self.assertEqual(comments, [
                    (1, "support", "plain", 1),
                    (1, "sarcasm", "sarcasm", 1),
                    (2, "joy", "plain", 1),
                    (2, "", "plain", 0),
                    (3, "trust", "plain", 0),
                    (3, "fear", "plain", 0),
                ])
                self.assertEqual(analyses, [(1, 1), (2, 0), (3, 0)])
                self.assertEqual(summaries, [
                    (1, 1, 11, 12, 13, 14),
                    (2, 0, 21, 22, 23, 24),
                    (3, 0, 31, 32, 33, 34),
                ])
            finally:
                engine.dispose()

    def test_existing_v2_versions_are_never_downgraded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "v2.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.execute(
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1V2', 1, 2)"
                )
                connection.execute(
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'trust', 'plain', 2, '2026-09-02 00:00:00')"
                )
                connection.execute(
                    "INSERT INTO sentiment_results (id, analysis_id, sentiment_llm_schema_version) "
                    "VALUES (1, 1, 2)"
                )
                connection.commit()
                connection.close()
                database._migrate(engine)

                connection = sqlite3.connect(path)
                versions = connection.execute(
                    "SELECT (SELECT sentiment_llm_schema_version FROM analyses WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM comments WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM sentiment_results WHERE id = 1)"
                ).fetchone()
                connection.close()
                self.assertEqual(versions, (2, 2, 2))
            finally:
                engine.dispose()

    def test_init_db_repeated_startup_keeps_the_v1_marker_and_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE analyses (id INTEGER PRIMARY KEY, bv VARCHAR(20), "
                "status VARCHAR(20), error_msg TEXT)"
            )
            connection.execute(
                "CREATE TABLE comments (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "sentiment_llm_label VARCHAR(20), sentiment_llm_style VARCHAR(20))"
            )
            connection.execute(
                "CREATE TABLE sentiment_results (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "llm_neutral INTEGER, llm_support INTEGER, llm_fear INTEGER, llm_sarcasm INTEGER)"
            )
            connection.execute(
                "INSERT INTO analyses (id, bv, status) VALUES (1, 'BV1LEGACY', 'done')"
            )
            connection.execute(
                "INSERT INTO comments (id, analysis_id, sentiment_llm_label, sentiment_llm_style) "
                "VALUES (1, 1, 'support', 'sarcasm')"
            )
            connection.execute(
                "INSERT INTO sentiment_results "
                "(id, analysis_id, llm_neutral, llm_support, llm_fear, llm_sarcasm) "
                "VALUES (1, 1, 41, 42, 43, 44)"
            )
            connection.commit()
            connection.close()

            engine = create_engine(f"sqlite:///{path}")
            try:
                with (
                    patch.object(database, "DB_PATH", str(path)),
                    patch.object(database, "engine", engine),
                ):
                    database.init_db()
                    database.init_db()
                connection = sqlite3.connect(path)
                payload = connection.execute(
                    "SELECT sentiment_llm_label, sentiment_llm_style, sentiment_llm_schema_version "
                    "FROM comments WHERE id = 1"
                ).fetchone()
                versions = connection.execute(
                    "SELECT (SELECT sentiment_llm_schema_version FROM analyses WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM sentiment_results WHERE analysis_id = 1), "
                    "(SELECT llm_neutral FROM sentiment_results WHERE analysis_id = 1), "
                    "(SELECT llm_support FROM sentiment_results WHERE analysis_id = 1), "
                    "(SELECT llm_fear FROM sentiment_results WHERE analysis_id = 1), "
                    "(SELECT llm_sarcasm FROM sentiment_results WHERE analysis_id = 1)"
                ).fetchone()
                connection.close()
                self.assertEqual(payload, ("support", "sarcasm", 1))
                self.assertEqual(versions, (1, 1, 41, 42, 43, 44))
                self.assertEqual(len(list((path.parent / "backups").glob("legacy-*.db"))), 1)
            finally:
                engine.dispose()

    def test_v2_migration_failure_restores_the_pre_upgrade_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE analyses (id INTEGER PRIMARY KEY, bv VARCHAR(20), "
                "status VARCHAR(20), error_msg TEXT)"
            )
            connection.execute(
                "CREATE TABLE comments (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "sentiment_llm_label VARCHAR(20), sentiment_llm_style VARCHAR(20))"
            )
            connection.execute(
                "CREATE TABLE sentiment_results (id INTEGER PRIMARY KEY, analysis_id INTEGER, "
                "llm_neutral INTEGER, llm_support INTEGER, llm_fear INTEGER, llm_sarcasm INTEGER)"
            )
            connection.execute(
                "INSERT INTO analyses (id, bv, status) VALUES (1, 'BV1ROLLBACK', 'done')"
            )
            connection.execute(
                "INSERT INTO comments (id, analysis_id, sentiment_llm_label, sentiment_llm_style) "
                "VALUES (1, 1, 'support', 'sarcasm')"
            )
            connection.execute(
                "INSERT INTO sentiment_results "
                "(id, analysis_id, llm_neutral, llm_support, llm_fear, llm_sarcasm) "
                "VALUES (1, 1, 51, 52, 53, 54)"
            )
            connection.commit()
            connection.close()

            engine = create_engine(f"sqlite:///{path}")
            original_migrate = database._migrate

            def fail_after_v2_migration(target_engine):
                original_migrate(target_engine)
                raise RuntimeError("injected v2 migration failure")

            try:
                with (
                    patch.object(database, "DB_PATH", str(path)),
                    patch.object(database, "engine", engine),
                    patch.object(database, "_migrate", side_effect=fail_after_v2_migration),
                ):
                    with self.assertRaisesRegex(RuntimeError, "数据库迁移失败"):
                        database.init_db()
                engine.dispose()
                connection = sqlite3.connect(path)
                comment_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(comments)")
                }
                payload = connection.execute(
                    "SELECT sentiment_llm_label, sentiment_llm_style FROM comments WHERE id = 1"
                ).fetchone()
                counts = connection.execute(
                    "SELECT llm_neutral, llm_support, llm_fear, llm_sarcasm "
                    "FROM sentiment_results WHERE analysis_id = 1"
                ).fetchone()
                connection.close()
                self.assertNotIn("sentiment_llm_schema_version", comment_columns)
                self.assertEqual(payload, ("support", "sarcasm"))
                self.assertEqual(counts, (51, 52, 53, 54))
            finally:
                engine.dispose()

    def test_pending_backfill_is_backed_up_before_validation_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "current-schema.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            original_validate = database._validate_schema
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.execute(
                    "INSERT INTO analyses (id, bv, avid, status, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1BACKFILL', 1, 'done', 0)"
                )
                connection.execute(
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'support', 'sarcasm', 0, '2026-09-02 00:00:00')"
                )
                connection.execute(
                    "INSERT INTO sentiment_results "
                    "(id, analysis_id, sentiment_llm_schema_version, llm_neutral, llm_support, "
                    "llm_fear, llm_sarcasm) VALUES (1, 1, 0, 71, 72, 73, 74)"
                )
                connection.commit()
                connection.close()

                def fail_after_validation(target_engine):
                    original_validate(target_engine)
                    raise RuntimeError("injected post-backfill validation failure")

                with (
                    patch.object(database, "DB_PATH", str(path)),
                    patch.object(database, "engine", engine),
                    patch.object(database, "_validate_schema", side_effect=fail_after_validation),
                ):
                    self.assertTrue(database._schema_change_required(engine))
                    with self.assertRaisesRegex(RuntimeError, "数据库迁移失败"):
                        database.init_db()

                engine.dispose()
                connection = sqlite3.connect(path)
                versions = connection.execute(
                    "SELECT (SELECT sentiment_llm_schema_version FROM analyses WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM comments WHERE id = 1), "
                    "(SELECT sentiment_llm_schema_version FROM sentiment_results WHERE id = 1)"
                ).fetchone()
                payload = connection.execute(
                    "SELECT sentiment_llm_label, sentiment_llm_style FROM comments WHERE id = 1"
                ).fetchone()
                counts = connection.execute(
                    "SELECT llm_neutral, llm_support, llm_fear, llm_sarcasm "
                    "FROM sentiment_results WHERE id = 1"
                ).fetchone()
                connection.close()
                self.assertEqual(versions, (0, 0, 0))
                self.assertEqual(payload, ("support", "sarcasm"))
                self.assertEqual(counts, (71, 72, 73, 74))
            finally:
                engine.dispose()

    def test_backfill_predicate_covers_each_mutating_version_transition(self):
        cases = [
            (
                "comment-null",
                ["INSERT INTO comments (analysis_id, sentiment_llm_label, sentiment_llm_schema_version) "
                 "VALUES (1, '', NULL)"],
            ),
            (
                "comment-v1-label",
                ["INSERT INTO comments (analysis_id, sentiment_llm_label, sentiment_llm_schema_version) "
                 "VALUES (1, 'support', 0)"],
            ),
            (
                "analysis-null",
                ["INSERT INTO analyses (id, sentiment_llm_schema_version) VALUES (1, NULL)"],
            ),
            (
                "summary-null",
                ["INSERT INTO sentiment_results (analysis_id, sentiment_llm_schema_version) VALUES (1, NULL)"],
            ),
            (
                "analysis-complete-v1",
                [
                    "INSERT INTO analyses (id, sentiment_llm_schema_version) VALUES (1, 0)",
                    "INSERT INTO comments (analysis_id, sentiment_llm_label, sentiment_llm_schema_version) "
                    "VALUES (1, 'support', 1)",
                ],
            ),
            (
                "summary-complete-v1",
                [
                    "INSERT INTO analyses (id, sentiment_llm_schema_version) VALUES (1, 1)",
                    "INSERT INTO sentiment_results (analysis_id, sentiment_llm_schema_version) VALUES (1, 0)",
                ],
            ),
        ]
        for name, statements in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "predicate.sqlite3"
                connection = sqlite3.connect(path)
                connection.execute(
                    "CREATE TABLE analyses (id INTEGER PRIMARY KEY, sentiment_llm_schema_version INTEGER)"
                )
                connection.execute(
                    "CREATE TABLE comments (analysis_id INTEGER, sentiment_llm_label TEXT, "
                    "sentiment_llm_schema_version INTEGER)"
                )
                connection.execute(
                    "CREATE TABLE sentiment_results (analysis_id INTEGER, sentiment_llm_schema_version INTEGER)"
                )
                for statement in statements:
                    connection.execute(statement)
                connection.commit()
                connection.close()
                engine = create_engine(f"sqlite:///{path}")
                try:
                    self.assertTrue(database._pending_llm_sentiment_version_backfill(engine))
                finally:
                    engine.dispose()

    def test_schema_validation_rejects_illegal_versions_and_v2_payloads(self):
        cases = [
            (
                "invalid-version",
                [
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1BADVERSION', 1, 7)",
                ],
                "非法大模型情感 Schema 版本",
            ),
            (
                "invalid-v2-emotion",
                [
                    "INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1BADEMOTION', 1)",
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'support', 'plain', 2, '2026-09-02 00:00:00')",
                ],
                "评论 V2 大模型情感或表达风格非法",
            ),
            (
                "invalid-v1-emotion",
                [
                    "INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1BADV1', 1)",
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'trust', 'plain', 1, '2026-09-02 00:00:00')",
                ],
                "评论 V1 大模型情感标签非法",
            ),
            (
                "invalid-v2-style",
                [
                    "INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1BADSTYLE', 1)",
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'trust', 'unknown', 2, '2026-09-02 00:00:00')",
                ],
                "评论 V2 大模型情感或表达风格非法",
            ),
        ]
        for name, statements, expected_error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "invalid.sqlite3"
                engine = create_engine(f"sqlite:///{path}")
                try:
                    database.Base.metadata.create_all(engine)
                    connection = sqlite3.connect(path)
                    for statement in statements:
                        connection.execute(statement)
                    connection.commit()
                    connection.close()
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        database._validate_schema(engine)
                finally:
                    engine.dispose()

    def test_schema_validation_rejects_versions_above_comment_or_analysis_coverage(self):
        cases = [
            (
                "analysis-v1-without-comments",
                [
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1NOCOMMENTS', 1, 1)",
                ],
                "分析大模型情感 Schema 版本高于其评论覆盖范围",
            ),
            (
                "analysis-v1-with-comment-v0",
                [
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1COMMENTV0', 1, 1)",
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 0, '2026-09-02 00:00:00')",
                ],
                "分析大模型情感 Schema 版本高于其评论覆盖范围",
            ),
            (
                "analysis-v2-with-comment-v1",
                [
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1PSEUDOANALYSIS', 1, 2)",
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'support', 'plain', 1, '2026-09-02 00:00:00')",
                ],
                "分析大模型情感 Schema 版本高于其评论覆盖范围",
            ),
            (
                "summary-v1-with-analysis-v0",
                [
                    "INSERT INTO analyses (id, bv, avid) VALUES (1, 'BV1PSEUDOSUMMARY', 1)",
                    "INSERT INTO sentiment_results (id, analysis_id, sentiment_llm_schema_version) "
                    "VALUES (1, 1, 1)",
                ],
                "大模型情感汇总 Schema 版本高于来源分析",
            ),
            (
                "orphan-summary-v1",
                [
                    "INSERT INTO sentiment_results (id, analysis_id, sentiment_llm_schema_version) "
                    "VALUES (1, 99, 1)",
                ],
                "大模型情感汇总 Schema 版本高于来源分析",
            ),
            (
                "summary-v2-with-analysis-v1",
                [
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1SUMMARYV2', 1, 1)",
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (1, 1, 1, 'support', 'plain', 1, '2026-09-02 00:00:00')",
                    "INSERT INTO sentiment_results (id, analysis_id, sentiment_llm_schema_version) "
                    "VALUES (1, 1, 2)",
                ],
                "大模型情感汇总 Schema 版本高于来源分析",
            ),
        ]
        for name, statements, expected_error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "pseudo.sqlite3"
                engine = create_engine(f"sqlite:///{path}")
                try:
                    database.Base.metadata.create_all(engine)
                    connection = sqlite3.connect(path)
                    for statement in statements:
                        connection.execute(statement)
                    connection.commit()
                    connection.close()
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        database._validate_schema(engine)
                finally:
                    engine.dispose()

    def test_schema_validation_allows_v1_analysis_with_v1_v2_comment_mix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mixed.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.execute(
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (1, 'BV1MIXED', 1, 1)"
                )
                connection.executemany(
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (?, 1, ?, ?, ?, ?, '2026-09-02 00:00:00')",
                    [
                        (1, 1, "support", "plain", 1),
                        (2, 2, "trust", "meme", 2),
                    ],
                )
                connection.commit()
                connection.close()
                database._validate_schema(engine)
            finally:
                engine.dispose()

    def test_schema_validation_allows_v1_summary_for_v1_or_v2_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "summary-order.sqlite3"
            engine = create_engine(f"sqlite:///{path}")
            try:
                database.Base.metadata.create_all(engine)
                connection = sqlite3.connect(path)
                connection.executemany(
                    "INSERT INTO analyses (id, bv, avid, sentiment_llm_schema_version) "
                    "VALUES (?, ?, ?, ?)",
                    [(1, "BV1SUMMARYV1", 1, 1), (2, "BV1SUMMARYV2", 2, 2)],
                )
                connection.executemany(
                    "INSERT INTO comments (id, analysis_id, rpid, sentiment_llm_label, "
                    "sentiment_llm_style, sentiment_llm_schema_version, post_time) "
                    "VALUES (?, ?, ?, ?, ?, ?, '2026-09-02 00:00:00')",
                    [
                        (1, 1, 1, "support", "plain", 1),
                        (2, 2, 2, "trust", "plain", 2),
                    ],
                )
                connection.executemany(
                    "INSERT INTO sentiment_results (id, analysis_id, sentiment_llm_schema_version) "
                    "VALUES (?, ?, 1)",
                    [(1, 1), (2, 2)],
                )
                connection.commit()
                connection.close()
                database._validate_schema(engine)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
