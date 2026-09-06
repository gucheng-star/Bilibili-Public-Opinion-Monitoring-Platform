import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes
from models.database import Analysis, Base
from services.comment_collection import CommentCollectionResult


class CommentCollectionRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.video = {
            "avid": 42, "title": "测试视频", "cover": "", "play": 1,
            "comment_count": 24,
        }

    def tearDown(self):
        self.engine.dispose()

    async def test_start_validates_public_count_and_persists_capture_parameters(self):
        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_video_info", new=AsyncMock(return_value={**self.video, "comment_count": 0})),
        ):
            with self.assertRaises(HTTPException) as unavailable:
                await routes.start_analysis({"bv": "BV1TEST00000"}, BackgroundTasks())
        self.assertEqual(unavailable.exception.status_code, 409)

        tasks = BackgroundTasks()
        large_video = {**self.video, "comment_count": 10_001}
        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_video_info", new=AsyncMock(return_value=large_video)),
        ):
            response = await routes.start_analysis(
                {"bv": "BV1TEST00000", "max_comments": 10_001, "request_delay": 2.5}, tasks,
            )
        self.assertEqual(response["comment_target_count"], 10_001)
        self.assertEqual(response["comment_request_delay"], 2.5)
        self.assertEqual(response["comment_collection_status"], "pending")
        self.assertEqual(tasks.tasks[0].args[3:5], (10_001, 2.5))
        db = self.sessions()
        try:
            analysis = db.get(Analysis, response["analysis_id"])
            self.assertEqual((analysis.comment_target_count, analysis.comment_request_delay), (10_001, 2.5))
        finally:
            db.close()

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_video_info", new=AsyncMock(return_value={**self.video, "comment_count": 1})),
        ):
            low_response = await routes.start_analysis(
                {"bv": "BV1TEST00001", "max_comments": 1, "request_delay": 3}, BackgroundTasks(),
            )
        self.assertEqual(low_response["comment_target_count"], 1)

    async def test_partial_collection_is_saved_as_readable_result(self):
        db = self.sessions()
        analysis = Analysis(
            bv="BV1TEST00000", avid=42, video_title="测试视频", status="pending",
            comment_target_count=5, comment_request_delay=3,
        )
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id
        db.close()
        partial = CommentCollectionResult(
            comments=[{
                "rpid": 1, "root_rpid": 1, "parent_rpid": None, "username": "u",
                "gender": "保密", "ip_location": "", "content": "很好", "likes": 0,
                "post_time": datetime.now(),
            }],
            target_count=5, collection_status="partial", termination_reason="source_exhausted",
            error_summary="不应暴露的上游文本",
        )
        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "fetch_comments", new=AsyncMock(return_value=partial)),
        ):
            self.assertTrue(await routes._run_analysis_inner(analysis_id, "BV1TEST00000", 42, 5, 3))
            result = routes.get_results(analysis_id)
        self.assertEqual(result["comment_collection_status"], "partial")
        self.assertEqual((result["comment_fetched_count"], result["comment_target_count"]), (1, 5))
        self.assertEqual(result["comment_error_summary"], "评论获取未完成，已保存部分结果，可重新采集")

    async def test_empty_collection_never_returns_upstream_error_text(self):
        db = self.sessions()
        analysis = Analysis(bv="BV1TEST00000", avid=42, video_title="测试视频", status="pending")
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id
        db.close()
        failed = CommentCollectionResult([], 5, "failed", "invalid_response", "token=secret")
        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "fetch_comments", new=AsyncMock(return_value=failed)),
        ):
            self.assertFalse(await routes._run_analysis_inner(analysis_id, "BV1TEST00000", 42, 5, 3))
            status = routes.get_status(analysis_id)
        self.assertEqual(status["comment_error_summary"], "评论获取失败，可重新采集")
        self.assertNotIn("secret", status["comment_error_summary"])
