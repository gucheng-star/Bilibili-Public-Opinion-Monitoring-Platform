import unittest
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import danmaku_routes
from models.database import Analysis, Base, DanmakuAnalysis, DanmakuSample
from services.danmaku import DanmakuFetchResult


class DanmakuRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        session = self.sessions()
        session.add(Analysis(bv="BV1TEST00000", avid=123, video_title="测试视频", status="done"))
        session.commit()
        self.analysis_id = session.query(Analysis).one().id
        session.close()

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def video_info():
        return {
            "bv": "BV1TEST00000", "avid": 123, "title": "测试视频", "duration": 720,
            "pages": [
                {"page": 1, "cid": 456, "part": "P1", "duration": 720},
                {"page": 2, "cid": 789, "part": "P2", "duration": 60},
            ],
        }

    async def test_start_explicitly_creates_independent_task_without_fetching_comments(self):
        tasks = BackgroundTasks()
        with (
            patch.object(danmaku_routes, "SessionLocal", self.sessions),
            patch.object(danmaku_routes, "get_video_info", new=AsyncMock(return_value=self.video_info())),
        ):
            response = await danmaku_routes.start_danmaku_sampling(
                {"analysis_id": self.analysis_id, "part_index": 2, "sample_limit": 10}, tasks,
            )
        self.assertEqual(response["status"], "pending")
        self.assertEqual(response["cid"], 789)
        self.assertEqual(response["segment_count"], 1)
        self.assertEqual(response["timeline"]["state"], "not_sampled")
        self.assertTrue(all(bucket["coverage"] == "not_sampled" for bucket in response["timeline"]["buckets"]))
        self.assertEqual(len(tasks.tasks), 1)
        session = self.sessions()
        try:
            task = session.get(DanmakuAnalysis, response["danmaku_analysis_id"])
            self.assertEqual(task.analysis_id, self.analysis_id)
            self.assertEqual(task.kept_count, 0)
            self.assertEqual(session.query(DanmakuSample).count(), 0)
        finally:
            session.close()

    async def test_runner_persists_real_progress_and_partial_failure_without_comment_records(self):
        session = self.sessions()
        task = DanmakuAnalysis(
            analysis_id=self.analysis_id, bv="BV1TEST00000", avid=123, cid=456,
            video_duration_seconds=720, sample_limit=2, segment_count=2,
        )
        session.add(task)
        session.commit()
        task_id = task.id
        session.close()

        async def fake_fetch(_client, _cid, _duration, _limit, *, progress_callback):
            result = DanmakuFetchResult(requested_segments=2, requested_segment_indexes=[0, 1], successful_segments=1)
            result.kept.append({"content": "保留 A", "progress_ms": 1000, "segment_index": 0})
            progress_callback(result)
            result.successful_segments = 1
            result.failed_segments = [1]
            progress_callback(result)
            return result

        with (
            patch.object(danmaku_routes, "SessionLocal", self.sessions),
            patch.object(danmaku_routes, "fetch_sampled_danmaku", new=AsyncMock(side_effect=fake_fetch)),
        ):
            self.assertTrue(await danmaku_routes._run_danmaku_task_inner(task_id))

        session = self.sessions()
        try:
            saved = session.get(DanmakuAnalysis, task_id)
            self.assertEqual(saved.status, "done")
            self.assertEqual((saved.requested_segments, saved.successful_segments, saved.kept_count), (2, 1, 1))
            self.assertEqual(saved.failed_segment_indexes, "[1]")
            self.assertEqual(saved.requested_segment_indexes, "[0, 1]")
            sample = session.query(DanmakuSample).filter_by(danmaku_analysis_id=task_id).one()
            self.assertIn(sample.sentiment_label, {"positive", "neutral", "negative"})
            self.assertIsNotNone(sample.sentiment_score)
            self.assertEqual(session.query(Analysis).filter_by(id=self.analysis_id).one().total_comments, 0)
        finally:
            session.close()

    async def test_each_selected_part_has_an_independent_task_for_the_same_source_video(self):
        first = BackgroundTasks()
        second = BackgroundTasks()
        with (
            patch.object(danmaku_routes, "SessionLocal", self.sessions),
            patch.object(danmaku_routes, "get_video_info", new=AsyncMock(return_value=self.video_info())),
        ):
            first_response = await danmaku_routes.start_danmaku_sampling(
                {"analysis_id": self.analysis_id, "part_index": 1, "sample_limit": 2}, first,
            )
            second_response = await danmaku_routes.start_danmaku_sampling(
                {"analysis_id": self.analysis_id, "part_index": 2, "sample_limit": 2}, second,
            )
        self.assertNotEqual(first_response["danmaku_analysis_id"], second_response["danmaku_analysis_id"])
        session = self.sessions()
        try:
            self.assertEqual(session.query(DanmakuAnalysis).filter_by(analysis_id=self.analysis_id).count(), 2)
        finally:
            session.close()
        with patch.object(danmaku_routes, "SessionLocal", self.sessions):
            selected = danmaku_routes.get_danmaku_sampling_for_analysis(self.analysis_id, part_index=2)
        self.assertEqual(selected["part_index"], 2)

    async def test_runner_marks_all_segment_failure_as_retryable_error(self):
        session = self.sessions()
        task = DanmakuAnalysis(
            analysis_id=self.analysis_id, bv="BV1TEST00000", avid=123, cid=456,
            video_duration_seconds=60, sample_limit=1, segment_count=1,
        )
        session.add(task)
        session.commit()
        task_id = task.id
        session.close()
        failed = DanmakuFetchResult(requested_segments=1, failed_segments=[0])

        with (
            patch.object(danmaku_routes, "SessionLocal", self.sessions),
            patch.object(danmaku_routes, "fetch_sampled_danmaku", new=AsyncMock(return_value=failed)),
        ):
            self.assertFalse(await danmaku_routes._run_danmaku_task_inner(task_id))

        with patch.object(danmaku_routes, "SessionLocal", self.sessions):
            response = danmaku_routes.get_danmaku_sampling(task_id)
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error_msg"], "弹幕获取失败，可重试")
        self.assertEqual(response["timeline"]["state"], "failed")
        self.assertTrue(all(bucket["coverage"] == "failed" for bucket in response["timeline"]["buckets"]))

    async def test_progress_and_samples_commit_together_when_later_fetch_crashes(self):
        session = self.sessions()
        task = DanmakuAnalysis(
            analysis_id=self.analysis_id, bv="BV1TEST00000", avid=123, cid=456,
            video_duration_seconds=720, sample_limit=2, segment_count=2,
        )
        session.add(task)
        session.commit()
        task_id = task.id
        session.close()

        async def crash_after_progress(_client, _cid, _duration, _limit, *, progress_callback):
            partial = DanmakuFetchResult(
                requested_segments=1, requested_segment_indexes=[0], successful_segments=1,
                kept=[{"content": "已完成片段", "progress_ms": 1000, "segment_index": 0}],
            )
            progress_callback(partial)
            raise RuntimeError("injected later fetch crash")

        with (
            patch.object(danmaku_routes, "SessionLocal", self.sessions),
            patch.object(danmaku_routes, "fetch_sampled_danmaku", new=AsyncMock(side_effect=crash_after_progress)),
        ):
            self.assertFalse(await danmaku_routes._run_danmaku_task_inner(task_id))

        session = self.sessions()
        try:
            saved = session.get(DanmakuAnalysis, task_id)
            sample_count = session.query(DanmakuSample).filter_by(danmaku_analysis_id=task_id).count()
            self.assertEqual((saved.kept_count, sample_count), (1, 1))
        finally:
            session.close()

    async def test_failed_retry_keeps_prior_completed_samples(self):
        session = self.sessions()
        previous = DanmakuAnalysis(
            analysis_id=self.analysis_id, bv="BV1TEST00000", avid=123, cid=456,
            video_duration_seconds=720, sample_limit=2, segment_count=2, status="done",
            kept_count=1,
        )
        session.add(previous)
        session.flush()
        session.add(DanmakuSample(
            danmaku_analysis_id=previous.id, content="旧样本", progress_ms=1000, segment_index=0,
        ))
        session.commit()
        previous_id = previous.id
        session.close()
        tasks = BackgroundTasks()
        with (
            patch.object(danmaku_routes, "SessionLocal", self.sessions),
            patch.object(danmaku_routes, "get_video_info", new=AsyncMock(return_value=self.video_info())),
        ):
            response = await danmaku_routes.start_danmaku_sampling(
                {"analysis_id": self.analysis_id, "part_index": 1, "sample_limit": 2}, tasks,
            )
        self.assertNotEqual(response["danmaku_analysis_id"], previous_id)
        session = self.sessions()
        try:
            self.assertEqual(session.query(DanmakuSample).filter_by(danmaku_analysis_id=previous_id).count(), 1)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
