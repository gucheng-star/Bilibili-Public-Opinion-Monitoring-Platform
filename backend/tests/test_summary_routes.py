from datetime import datetime
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import summary_routes
from models.database import AISummary, Analysis, Base, Comment


class SummaryRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        db = self.sessions()
        analysis = Analysis(
            bv="BV1TEST",
            avid=1,
            video_title="测试视频",
            status="done",
            mode="nlp",
            total_comments=1,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        self.analysis_id = analysis.id
        db.add(Comment(
            analysis_id=analysis.id,
            rpid=1,
            username="不会发送的用户名",
            gender="男",
            ip_location="广东",
            content="这是一条测试评论",
            likes=3,
            sentiment_label="positive",
            sentiment_score=0.9,
            post_time=datetime(2026, 7, 1, 12, 0),
        ))
        db.commit()
        db.close()
        self.session_patch = patch.object(summary_routes, "SessionLocal", self.sessions)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    async def test_create_cache_and_regenerate_overwrites(self):
        filters = {"gender": "all", "dateFrom": "", "dateTo": "", "region": "", "sentiment": "all"}
        config = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "fallback_model": "",
            "api_key": "secret",
        }
        generator = AsyncMock(return_value=("第一版总结", "deepseek-v4-flash", 1))
        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(
            summary_routes, "generate_summary", generator
        ):
            first = await summary_routes.create_summary(self.analysis_id, {"filters": filters})
            cached = await summary_routes.create_summary(self.analysis_id, {"filters": filters})
            generator.return_value = ("第二版总结", "deepseek-v4-pro", 1)
            regenerated = await summary_routes.create_summary(
                self.analysis_id, {"filters": filters, "regenerate": True}
            )

        self.assertEqual(generator.await_count, 2)
        self.assertEqual(first["id"], cached["id"])
        self.assertEqual(first["id"], regenerated["id"])
        self.assertEqual(regenerated["summary_text"], "第二版总结")
        db = self.sessions()
        self.assertEqual(db.query(AISummary).count(), 1)
        db.close()

    async def test_saved_summary_becomes_stale_after_source_change(self):
        filters = {"gender": "all", "dateFrom": "", "dateTo": "", "region": "", "sentiment": "all"}
        config = {
            "provider": "bailian", "base_url": "https://example.com",
            "model": "model", "fallback_model": "", "api_key": "secret",
        }
        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(
            summary_routes, "generate_summary", AsyncMock(return_value=("总结", "model", 1))
        ):
            await summary_routes.create_summary(self.analysis_id, {"filters": filters})

        db = self.sessions()
        comment = db.query(Comment).first()
        comment.content = "已经改变的评论"
        db.commit()
        db.close()

        listed = summary_routes.list_summaries(self.analysis_id)
        self.assertTrue(listed[0]["stale"])

    async def test_provider_failure_does_not_persist_summary(self):
        filters = {"gender": "all", "dateFrom": "", "dateTo": "", "region": "", "sentiment": "all"}
        config = {
            "provider": "custom", "base_url": "https://example.com/v1",
            "model": "model", "fallback_model": "", "api_key": "secret",
        }
        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(
            summary_routes, "generate_summary", AsyncMock(side_effect=ValueError("模拟模型失败"))
        ):
            with self.assertRaises(HTTPException) as raised:
                await summary_routes.create_summary(self.analysis_id, {"filters": filters})

        self.assertEqual(raised.exception.status_code, 502)
        db = self.sessions()
        self.assertEqual(db.query(AISummary).count(), 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
