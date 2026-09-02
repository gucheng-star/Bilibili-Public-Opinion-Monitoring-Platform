import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes
from models.database import Analysis, Base, Comment, SentimentResult
from services.llm_client import LLMRequestError
from services.sentiment_contract import LLM_SENTIMENT_SCHEMA_V2


class V2ReanalysisTests(unittest.IsolatedAsyncioTestCase):
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

    def create_analysis(self, comments):
        session = self.sessions()
        try:
            analysis = Analysis(
                bv="BV1V2TEST", avid=1, video_title="强烈愤怒的标题", status="done", mode="nlp",
                total_comments=len(comments),
            )
            session.add(analysis)
            session.flush()
            session.add_all([
                Comment(
                    analysis_id=analysis.id,
                    rpid=comment["rpid"],
                    content=comment["content"],
                    post_time=datetime.now(),
                    sentiment_llm_label=comment.get("label", ""),
                    sentiment_llm_style=comment.get("style", "plain"),
                    sentiment_llm_schema_version=comment.get("version", 0),
                )
                for comment in comments
            ])
            session.add(SentimentResult(
                analysis_id=analysis.id,
                llm_support=9,
                llm_concern=8,
                llm_sarcasm=7,
            ))
            session.commit()
            return analysis.id
        finally:
            session.close()

    async def test_full_v2_reanalysis_persists_title_blank_and_v2_summary(self):
        analysis_id = self.create_analysis([
            {"rpid": 1, "content": "谢谢你的安慰"},
            {"rpid": 2, "content": "", "label": "support", "version": 1},
            {"rpid": 3, "content": "好害怕", "label": "concern", "version": 1},
        ])

        async def fake_batch(comments, _config, **kwargs):
            self.assertEqual(kwargs["video_title"], "强烈愤怒的标题")
            self.assertEqual(len(kwargs["context_comments"]), 3)
            for comment in comments:
                emotion = {1: "trust", 2: "neutral", 3: "fear"}[comment["rpid"]]
                comment["sentiment_llm_label"] = emotion
                comment["sentiment_llm_style"] = "plain"
            kwargs["progress_callback"](len(comments))
            return comments

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "batch_analyze_llm", new=AsyncMock(side_effect=fake_batch)),
        ):
            self.assertTrue(await routes._run_reanalyze_inner(
                analysis_id,
                [
                    {"rpid": 1, "content": "谢谢你的安慰"},
                    {"rpid": 2, "content": ""},
                    {"rpid": 3, "content": "好害怕"},
                ],
                {"api_key": "test-key"},
                context_comments=[
                    {"rpid": 1, "content": "谢谢你的安慰"},
                    {"rpid": 2, "content": ""},
                    {"rpid": 3, "content": "好害怕"},
                ],
            ))
            status = routes.get_status(analysis_id)
            payload = routes.get_results(analysis_id)

        session = self.sessions()
        try:
            analysis = session.get(Analysis, analysis_id)
            result = session.query(SentimentResult).filter_by(analysis_id=analysis_id).one()
            comments = session.query(Comment).filter_by(analysis_id=analysis_id).order_by(Comment.rpid).all()
            self.assertEqual(analysis.sentiment_llm_schema_version, LLM_SENTIMENT_SCHEMA_V2)
            self.assertEqual(analysis.mode, "llm")
            self.assertEqual(analysis.processed_comments, 3)
            self.assertTrue(all(comment.sentiment_llm_schema_version == LLM_SENTIMENT_SCHEMA_V2 for comment in comments))
            self.assertEqual((result.llm_trust, result.llm_fear), (1, 1))
            self.assertEqual((result.llm_support, result.llm_concern, result.llm_sarcasm), (0, 0, 0))
            self.assertEqual(result.sentiment_llm_schema_version, LLM_SENTIMENT_SCHEMA_V2)
            self.assertEqual(status["v2_target_count"], 3)
            self.assertEqual(status["v2_completed_count"], 3)
            self.assertEqual(status["v2_pending_count"], 0)
            self.assertEqual((payload["sentiment_llm"]["trust"], payload["sentiment_llm"]["fear"]), (1, 1))
            self.assertNotIn("support", payload["sentiment_llm"])
            self.assertNotIn("concern", payload["sentiment_llm"])
            self.assertNotIn("sarcasm", payload["sentiment_llm"])
        finally:
            session.close()

    async def test_partial_failure_is_safe_and_resume_targets_only_non_v2_comments(self):
        analysis_id = self.create_analysis([
            {"rpid": 1, "content": "谢谢"},
            {"rpid": 2, "content": "很担心"},
        ])

        async def partial_batch(comments, _config, **kwargs):
            comments[0]["sentiment_llm_label"] = "trust"
            comments[0]["sentiment_llm_style"] = "plain"
            kwargs["progress_callback"](1)
            raise LLMRequestError("raw rpid=2 and secret-key", category="authentication")

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "batch_analyze_llm", new=AsyncMock(side_effect=partial_batch)),
        ):
            self.assertFalse(await routes._run_reanalyze_inner(
                analysis_id,
                [{"rpid": 1, "content": "谢谢"}, {"rpid": 2, "content": "很担心"}],
                {"api_key": "secret-key"},
            ))

        session = self.sessions()
        try:
            analysis = session.get(Analysis, analysis_id)
            persisted = {comment.rpid: comment for comment in session.query(Comment).filter_by(analysis_id=analysis_id)}
            self.assertEqual(analysis.status, "done")
            self.assertEqual(analysis.mode, "nlp")
            self.assertNotEqual(analysis.sentiment_llm_schema_version, LLM_SENTIMENT_SCHEMA_V2)
            self.assertEqual(persisted[1].sentiment_llm_schema_version, LLM_SENTIMENT_SCHEMA_V2)
            self.assertNotEqual(persisted[2].sentiment_llm_schema_version, LLM_SENTIMENT_SCHEMA_V2)
            self.assertNotIn("rpid=2", analysis.error_msg)
            self.assertNotIn("secret-key", analysis.error_msg)
        finally:
            session.close()

        background_tasks = BackgroundTasks()
        config = Mock(return_value={"api_key": "test-key"})
        with patch.object(routes, "SessionLocal", self.sessions), patch.object(routes, "get_task_config", config):
            status = routes.get_status(analysis_id)
            response = await routes.reanalyze(analysis_id, background_tasks)
        self.assertEqual(response["status"], "analyzing")
        self.assertEqual([comment["rpid"] for comment in background_tasks.tasks[0].args[1]], [2])
        self.assertNotIn("rpid=2", status["error_summary"])
        self.assertNotIn("secret-key", status["error_summary"])
        self.assertEqual((status["v2_target_count"], status["v2_completed_count"], status["v2_pending_count"]), (2, 1, 1))

    async def test_all_v2_comments_skip_without_model_call(self):
        analysis_id = self.create_analysis([
            {"rpid": 1, "content": "已经完成", "label": "trust", "style": "plain", "version": 2},
        ])
        config = Mock()
        with patch.object(routes, "SessionLocal", self.sessions), patch.object(routes, "get_task_config", config):
            response = await routes.reanalyze(analysis_id, BackgroundTasks())

        self.assertTrue(response["skipped"])
        config.assert_not_called()
        session = self.sessions()
        try:
            analysis = session.get(Analysis, analysis_id)
            self.assertEqual(analysis.mode, "llm")
            self.assertEqual(analysis.sentiment_llm_schema_version, LLM_SENTIMENT_SCHEMA_V2)
        finally:
            session.close()

    async def test_v1_llm_results_keep_legacy_response_keys(self):
        analysis_id = self.create_analysis([
            {"rpid": 1, "content": "历史分类", "label": "support", "style": "sarcasm", "version": 1},
        ])
        session = self.sessions()
        try:
            analysis = session.get(Analysis, analysis_id)
            result = session.query(SentimentResult).filter_by(analysis_id=analysis_id).one()
            analysis.mode = "llm"
            analysis.sentiment_llm_schema_version = 1
            result.sentiment_llm_schema_version = 1
            result.llm_support = 2
            result.llm_concern = 3
            result.llm_sarcasm = 4
            result.llm_trust = 5
            result.llm_fear = 6
            session.commit()
        finally:
            session.close()

        with patch.object(routes, "SessionLocal", self.sessions):
            payload = routes.get_results(analysis_id)

        llm = payload["sentiment_llm"]
        self.assertEqual((llm["support"], llm["concern"], llm["sarcasm"]), (2, 3, 4))
        self.assertNotIn("trust", llm)
        self.assertNotIn("fear", llm)


if __name__ == "__main__":
    unittest.main()
