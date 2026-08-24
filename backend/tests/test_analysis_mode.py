import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes
from models.database import Analysis, Base, Comment, SentimentResult


class InitialAnalysisModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    async def test_new_analysis_forces_nlp_when_client_requests_llm(self):
        background_tasks = BackgroundTasks()
        video_info = {
            "avid": 123,
            "title": "test video",
            "cover": "https://example.com/cover.jpg",
            "play": 456,
        }

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_video_info", new=AsyncMock(return_value=video_info)),
        ):
            response = await routes.start_analysis(
                {
                    "bv": "BV1TEST00000",
                    "max_comments": 20,
                    "request_delay": 1,
                    "mode": "llm",
                },
                background_tasks,
            )

        session = self.sessions()
        try:
            analysis = session.get(Analysis, response["analysis_id"])
            self.assertIsNotNone(analysis)
            self.assertEqual(analysis.mode, "nlp")
        finally:
            session.close()

        self.assertEqual(response["mode"], "nlp")
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertEqual(background_tasks.tasks[0].kwargs["mode"], "nlp")

    async def test_failed_llm_reanalysis_preserves_nlp_result(self):
        session = self.sessions()
        analysis = Analysis(
            bv="BV1TEST00000",
            avid=123,
            video_title="test video",
            status="analyzing",
            mode="nlp",
            total_comments=20,
        )
        session.add(analysis)
        session.commit()
        analysis_id = analysis.id
        session.close()

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(
                routes,
                "batch_analyze_llm",
                new=AsyncMock(side_effect=RuntimeError("model returned empty content")),
            ),
        ):
            await routes._run_reanalyze(analysis_id, [], {})

        session = self.sessions()
        try:
            preserved = session.get(Analysis, analysis_id)
            self.assertEqual(preserved.status, "done")
            self.assertEqual(preserved.mode, "nlp")
            self.assertIn("empty content", preserved.error_msg)
        finally:
            session.close()

    async def test_reanalysis_resets_and_persists_real_progress(self):
        session = self.sessions()
        analysis = Analysis(
            bv="BV1TEST00000", avid=123, video_title="test video", status="done",
            mode="nlp", total_comments=99, processed_comments=99,
        )
        session.add(analysis)
        session.flush()
        session.add_all([
            Comment(analysis_id=analysis.id, rpid=1, content="first", post_time=datetime.now()),
            Comment(analysis_id=analysis.id, rpid=2, content="", post_time=datetime.now()),
        ])
        session.commit()
        analysis_id = analysis.id
        session.close()

        background_tasks = BackgroundTasks()
        async def fake_batch(comments, _config, progress_callback=None):
            progress_callback(1)
            progress_callback(2)
            for comment in comments:
                comment["sentiment_llm_label"] = "sarcasm" if comment["rpid"] == 1 else "neutral"
                comment["sentiment_llm_style"] = "plain"
            return comments

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_task_config", return_value={"api_key": "test-key"}),
            patch.object(routes, "batch_analyze_llm", new=AsyncMock(side_effect=fake_batch)),
        ):
            response = await routes.reanalyze(analysis_id, background_tasks)
            self.assertEqual(response["status"], "analyzing")
            self.assertEqual(len(background_tasks.tasks), 1)
            pending_session = self.sessions()
            try:
                pending = pending_session.get(Analysis, analysis_id)
                self.assertEqual(pending.total_comments, 2)
                self.assertEqual(pending.processed_comments, 0)
            finally:
                pending_session.close()
            await routes._run_reanalyze_inner(analysis_id, [
                {"rpid": 1, "content": "first"}, {"rpid": 2, "content": ""},
            ], {"api_key": "test-key"})

        session = self.sessions()
        try:
            completed = session.get(Analysis, analysis_id)
            self.assertEqual(completed.total_comments, 2)
            self.assertEqual(completed.processed_comments, 2)
            self.assertEqual(completed.status, "done")
            self.assertEqual(completed.mode, "llm")
            sentiment = session.query(SentimentResult).filter_by(analysis_id=analysis_id).one()
            self.assertEqual(sentiment.llm_sarcasm, 1)
            with patch.object(routes, "SessionLocal", self.sessions):
                self.assertEqual(routes.get_status(analysis_id)["processed_comments"], 2)
                self.assertEqual(routes.get_results(analysis_id)["sentiment_llm"]["sarcasm"], 1)
        finally:
            session.close()

    async def test_reanalysis_keeps_completed_subbatches_when_one_comment_keeps_failing(self):
        session = self.sessions()
        analysis = Analysis(
            bv="BV1TEST00000", avid=123, video_title="test video", status="analyzing",
            mode="nlp", total_comments=5,
        )
        session.add(analysis)
        session.flush()
        session.add_all([
            Comment(analysis_id=analysis.id, rpid=index, content=f"comment {index}", post_time=datetime.now())
            for index in range(1, 6)
        ])
        session.commit()
        analysis_id = analysis.id
        session.close()

        async def fake_analyze(batch, _config, _contexts):
            if len(batch) >= 3:
                try:
                    raise ValueError("模型返回了重复的评论 ID")
                except ValueError as cause:
                    raise RuntimeError("LLM batch failed after 3 attempts") from cause
            if len(batch) == 1 and batch[0]["rpid"] == 3:
                try:
                    raise ValueError("模型持续返回非法评论 ID")
                except ValueError as cause:
                    raise RuntimeError("LLM batch failed after 3 attempts") from cause
            return {
                str(comment["rpid"]): {"label": "joy", "style": "plain"}
                for comment in batch
            }

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch("services.sentiment_llm._analyze_batch_with_retry", side_effect=fake_analyze),
        ):
            await routes._run_reanalyze_inner(
                analysis_id,
                [{"rpid": index, "content": f"comment {index}"} for index in range(1, 6)],
                {"api_key": "test-key"},
            )

        session = self.sessions()
        try:
            failed = session.get(Analysis, analysis_id)
            self.assertEqual(failed.status, "done")
            self.assertEqual(failed.mode, "nlp")
            self.assertEqual(failed.processed_comments, 4)
            self.assertIn("rpid=3", failed.error_msg)
            labels = {
                comment.rpid: comment.sentiment_llm_label
                for comment in session.query(Comment).filter_by(analysis_id=analysis_id)
            }
            self.assertEqual(labels[1], "joy")
            self.assertEqual(labels[2], "joy")
            self.assertEqual(labels[3], "")
            self.assertEqual(labels[4], "joy")
            self.assertEqual(labels[5], "joy")
        finally:
            session.close()

        background_tasks = BackgroundTasks()
        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_task_config", return_value={"api_key": "test-key"}),
        ):
            response = await routes.reanalyze(analysis_id, background_tasks)

        self.assertEqual(response["status"], "analyzing")
        queued_comments = background_tasks.tasks[0].args[1]
        self.assertEqual([comment["rpid"] for comment in queued_comments], [3])

    async def test_one_protocol_failure_does_not_cancel_other_halves_or_batches(self):
        session = self.sessions()
        analysis = Analysis(
            bv="BV1TEST00000", avid=123, video_title="test video", status="analyzing",
            mode="nlp", total_comments=10,
        )
        session.add(analysis)
        session.flush()
        session.add_all([
            Comment(analysis_id=analysis.id, rpid=index, content=f"comment {index}", post_time=datetime.now())
            for index in range(1, 11)
        ])
        session.commit()
        analysis_id = analysis.id
        session.close()

        async def fake_analyze(batch, _config, _contexts):
            if any(comment["rpid"] == 3 for comment in batch):
                try:
                    raise ValueError("模型返回格式不符合要求：包含意外的批次条目 ID")
                except ValueError as cause:
                    raise RuntimeError("大模型批次连续 3 次失败") from cause
            return {
                str(comment["rpid"]): {"label": "joy", "style": "plain"}
                for comment in batch
            }

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch("services.sentiment_llm._analyze_batch_with_retry", side_effect=fake_analyze),
        ):
            await routes._run_reanalyze_inner(
                analysis_id,
                [{"rpid": index, "content": f"comment {index}"} for index in range(1, 11)],
                {"api_key": "test-key"},
            )

        session = self.sessions()
        try:
            failed = session.get(Analysis, analysis_id)
            self.assertEqual(failed.status, "done")
            self.assertEqual(failed.mode, "nlp")
            self.assertEqual(failed.processed_comments, 9)
            self.assertIn("rpid=3", failed.error_msg)
            labels = {
                comment.rpid: comment.sentiment_llm_label
                for comment in session.query(Comment).filter_by(analysis_id=analysis_id)
            }
            self.assertEqual(labels[3], "")
            self.assertTrue(all(labels[index] == "joy" for index in range(1, 11) if index != 3))
        finally:
            session.close()

        background_tasks = BackgroundTasks()
        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_task_config", return_value={"api_key": "test-key"}),
        ):
            response = await routes.reanalyze(analysis_id, background_tasks)

        self.assertEqual(response["status"], "analyzing")
        queued_comments = background_tasks.tasks[0].args[1]
        self.assertEqual([comment["rpid"] for comment in queued_comments], [3])

    async def test_reanalysis_marks_legacy_valid_labels_ready_without_api_key(self):
        session = self.sessions()
        analysis = Analysis(bv="BV1TEST00000", avid=123, video_title="test video", status="done", mode="nlp")
        session.add(analysis)
        session.flush()
        session.add(Comment(
            analysis_id=analysis.id, rpid=1, content="已有标签", sentiment_llm_label="support",
            sentiment_llm_style="sarcasm", post_time=datetime.now(),
        ))
        session.commit()
        analysis_id = analysis.id
        session.close()

        config = Mock()
        with patch.object(routes, "SessionLocal", self.sessions), patch.object(routes, "get_task_config", config):
            response = await routes.reanalyze(analysis_id, BackgroundTasks())

        self.assertEqual(response["status"], "done")
        self.assertTrue(response["skipped"])
        config.assert_not_called()
        session = self.sessions()
        try:
            self.assertEqual(session.get(Analysis, analysis_id).mode, "llm")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
