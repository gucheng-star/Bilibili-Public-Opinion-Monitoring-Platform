import asyncio
from datetime import datetime
import json
import unittest
from collections import Counter
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import group_routes, routes
from models.database import Analysis, AnalysisGroupItem, AnalysisGroupSummary, Base, Comment
from services.analysis_groups import select_group_representative_comments


class AnalysisGroupRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        with self.engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        db = self.sessions()
        first = Analysis(bv="BV1GROUPA", avid=1, video_title="来源 A", status="done", mode="nlp", total_comments=2)
        second = Analysis(bv="BV1GROUPB", avid=2, video_title="来源 B", status="done", mode="nlp", total_comments=1)
        db.add_all([first, second])
        db.flush()
        db.add_all([
            Comment(analysis_id=first.id, rpid=1, content="相同文本", likes=9, gender="男", ip_location="广东", sentiment_label="positive", post_time=datetime(2026, 8, 1, 9)),
            Comment(analysis_id=first.id, rpid=2, content="相同文本", likes=2, gender="女", ip_location="广东", sentiment_label="positive", post_time=datetime(2026, 8, 1, 10)),
            Comment(analysis_id=second.id, rpid=3, content="相同文本", likes=3, gender="女", ip_location="北京", sentiment_label="negative", post_time=datetime(2026, 8, 2, 9)),
        ])
        db.commit()
        self.first_id, self.second_id = first.id, second.id
        db.close()
        self.group_patch = patch.object(group_routes, "SessionLocal", self.sessions)
        self.history_patch = patch.object(routes, "SessionLocal", self.sessions)
        self.group_patch.start()
        self.history_patch.start()

    def tearDown(self):
        self.group_patch.stop()
        self.history_patch.stop()
        self.engine.dispose()

    def _create_group(self):
        return group_routes.post_group({
            "name": "发布会争议", "description": "测试", "analysis_ids": [self.first_id, self.second_id],
        })

    def test_crud_validation_and_history_delete_keeps_event(self):
        with self.assertRaises(HTTPException) as too_few:
            group_routes.post_group({"name": "x", "analysis_ids": [self.first_id]})
        self.assertEqual(too_few.exception.status_code, 400)
        group = self._create_group()
        self.assertEqual(group["member_count"], 2)
        self.assertEqual(group["total_comments"], 3)
        self.assertTrue(group["is_analyzable"])
        history_item = next(item for item in routes.get_history() if item["id"] == self.first_id)
        self.assertEqual(history_item["affected_group_count"], 1)
        with self.assertRaises(HTTPException) as duplicate_bv:
            group_routes.patch_group(group["id"], {"analysis_ids": [self.first_id, self.first_id]})
        self.assertEqual(duplicate_bv.exception.status_code, 400)

        deleted = routes.delete_history(self.first_id)
        self.assertEqual(deleted["affected_group_count"], 1)
        remaining = group_routes.get_group_detail(group["id"])
        self.assertEqual(remaining["member_status"], "insufficient_members")
        db = self.sessions()
        self.assertEqual(db.query(AnalysisGroupItem).filter_by(group_id=group["id"]).count(), 1)
        self.assertEqual(db.query(Analysis).filter_by(id=self.second_id).count(), 1)
        db.close()

    def test_scoped_duplicates_filters_and_llm_readiness(self):
        group = self._create_group()
        dedup_filters = json.dumps({"duplicateMode": "deduplicate"})
        result = group_routes.get_group_results(group["id"], mode="nlp", filters=dedup_filters)
        self.assertEqual(result["total_comments"], 3)
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual([item["matched_count"] for item in result["source_distribution"]], [1, 1])
        first_source = [item for item in result["comments"] if item["source_analysis_id"] == self.first_id]
        self.assertEqual(first_source[0]["duplicate_group_size"], 2)
        second_source = [item for item in result["comments"] if item["source_analysis_id"] == self.second_id]
        self.assertEqual(second_source[0]["duplicate_group_size"], 1)

        source_only = group_routes.get_group_results(
            group["id"], mode="nlp", filters=json.dumps({"sourceAnalysisId": self.second_id}),
        )
        self.assertEqual(source_only["matched_count"], 1)
        keyword_response = group_routes.post_group_keywords(group["id"], {
            "mode": "nlp", "filters": {"sourceAnalysisId": self.second_id},
        })
        self.assertEqual(keyword_response["matched_count"], 1)

        db = self.sessions()
        first = db.get(Analysis, self.first_id)
        first.mode = "llm"
        for comment in db.query(Comment).filter_by(analysis_id=self.first_id):
            comment.sentiment_llm_label = "support"
        db.commit()
        db.close()
        with self.assertRaises(HTTPException) as unavailable:
            group_routes.get_group_results(group["id"], mode="llm")
        self.assertEqual(unavailable.exception.status_code, 409)
        self.assertTrue(unavailable.exception.detail["missing_members"])

    async def test_group_reanalysis_only_queues_missing_source_comments(self):
        group = self._create_group()
        db = self.sessions()
        first = db.get(Analysis, self.first_id)
        first.mode = "llm"
        for comment in db.query(Comment).filter_by(analysis_id=self.first_id):
            comment.sentiment_llm_label = "support"
        parent = db.query(Comment).filter_by(analysis_id=self.second_id, rpid=3).first()
        parent.sentiment_llm_label = "neutral"
        db.add(Comment(
            analysis_id=self.second_id, rpid=4, root_rpid=3, parent_rpid=3,
            content="这条回复需要补齐标签", post_time=datetime(2026, 8, 2, 10),
        ))
        db.commit()
        db.close()

        background_tasks = BackgroundTasks()
        with patch.object(group_routes, "get_task_config", return_value={"api_key": "test-key"}):
            response = await group_routes.post_group_reanalyze(group["id"], background_tasks)

        self.assertEqual(response["status"], "analyzing")
        self.assertEqual(response["started_analysis_ids"], [self.second_id])
        self.assertEqual(len(background_tasks.tasks), 1)
        queued = background_tasks.tasks[0].args[0]
        self.assertEqual(queued[0]["analysis_id"], self.second_id)
        self.assertEqual([comment["rpid"] for comment in queued[0]["target_comments"]], [4])
        self.assertEqual(
            [comment["rpid"] for comment in queued[0]["context_comments"]],
            [3, 4],
        )

        async def fake_batch(comments, _config, progress_callback=None, context_comments=None):
            self.assertEqual([comment["rpid"] for comment in comments], [4])
            self.assertEqual([comment["rpid"] for comment in context_comments], [3, 4])
            progress_callback(1)
            comments[0]["sentiment_llm_label"] = "joy"
            comments[0]["sentiment_llm_style"] = "plain"
            return comments

        with patch.object(routes, "batch_analyze_llm", new=AsyncMock(side_effect=fake_batch)):
            await group_routes._run_group_reanalyze(queued, {"api_key": "test-key"})

        db = self.sessions()
        try:
            first_labels = [comment.sentiment_llm_label for comment in db.query(Comment).filter_by(analysis_id=self.first_id)]
            self.assertEqual(first_labels, ["support", "support"])
            self.assertEqual(db.query(Comment).filter_by(analysis_id=self.second_id, rpid=4).one().sentiment_llm_label, "joy")
            self.assertEqual(db.get(Analysis, self.second_id).mode, "llm")
        finally:
            db.close()
        self.assertTrue(group_routes.get_group_reanalyze_status(group["id"])["ready"])

    async def test_group_reanalysis_keeps_running_while_nlp_results_are_read(self):
        group = self._create_group()
        background_tasks = BackgroundTasks()
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_batch(comments, _config, progress_callback=None, context_comments=None):
            started.set()
            await release.wait()
            for comment in comments:
                comment["sentiment_llm_label"] = "neutral"
                comment["sentiment_llm_style"] = "plain"
            if progress_callback:
                progress_callback(len(comments))
            return comments

        with (
            patch.object(group_routes, "get_task_config", return_value={"api_key": "test-key"}),
            patch.object(routes, "batch_analyze_llm", new=AsyncMock(side_effect=fake_batch)),
        ):
            response = await group_routes.post_group_reanalyze(group["id"], background_tasks)
            self.assertEqual(response["status"], "analyzing")
            worker = asyncio.create_task(background_tasks())
            await asyncio.wait_for(started.wait(), timeout=1)

            # Reading the always-available NLP view is independent of the
            # server-side worker and must not cancel or replace it.
            nlp_result = group_routes.get_group_results(group["id"], mode="nlp")
            self.assertEqual(nlp_result["matched_count"], 3)
            self.assertFalse(worker.done())

            release.set()
            await asyncio.wait_for(worker, timeout=1)

        self.assertTrue(group_routes.get_group_reanalyze_status(group["id"])["ready"])

    async def test_shared_source_is_claimed_once_across_events(self):
        first_group = self._create_group()
        second_group = group_routes.post_group({
            "name": "共享来源的另一个事件",
            "analysis_ids": [self.first_id, self.second_id],
        })
        first_tasks = BackgroundTasks()
        second_tasks = BackgroundTasks()

        with patch.object(group_routes, "get_task_config", return_value={"api_key": "test-key"}):
            first_response = await group_routes.post_group_reanalyze(first_group["id"], first_tasks)
            with self.assertRaises(HTTPException) as duplicate_start:
                await group_routes.post_group_reanalyze(second_group["id"], second_tasks)

        self.assertEqual(first_response["status"], "analyzing")
        self.assertEqual(len(first_tasks.tasks), 1)
        self.assertEqual(duplicate_start.exception.status_code, 409)
        self.assertEqual(len(second_tasks.tasks), 0)

    async def test_group_summary_caches_and_becomes_stale(self):
        group = self._create_group()
        config = {"provider": "custom", "api_key": "secret", "model": "mock", "base_url": "https://example.com"}
        generator = AsyncMock(return_value=("事件简报", "mock", 2))
        with patch.object(group_routes, "get_task_config", return_value=config), patch.object(
            group_routes, "generate_group_summary", generator,
        ):
            first = await group_routes.post_group_summary(group["id"], {"filters": {}})
            second = await group_routes.post_group_summary(group["id"], {"filters": {}})
        self.assertEqual(generator.await_count, 1)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["sampled_count"], 2)
        db = self.sessions()
        comment = db.query(Comment).filter_by(analysis_id=self.second_id).first()
        comment.content = "来源已更新"
        db.commit()
        self.assertEqual(db.query(AnalysisGroupSummary).count(), 1)
        db.close()
        listed = group_routes.list_group_summaries(group["id"])
        self.assertTrue(listed[0]["stale"])

    def test_delete_group_does_not_delete_source_analyses(self):
        group = self._create_group()
        self.assertTrue(group_routes.delete_group(group["id"])["deleted"])
        db = self.sessions()
        self.assertEqual(db.query(Analysis).count(), 2)
        self.assertEqual(db.query(AnalysisGroupItem).count(), 0)
        db.close()

    def test_group_summary_sampling_balances_sources_strata_and_privacy(self):
        rows = []
        comments = []
        for source_id, label, title in ((1, "positive", "来源一"), (2, "negative", "来源二"), (3, "neutral", "来源三")):
            analysis = Analysis(id=source_id, bv=f"BV{source_id}", video_title=title, status="done", mode="nlp")
            item = AnalysisGroupItem(group_id=1, analysis_id=source_id, position=source_id)
            rows.append((item, analysis))
            for offset in range(60):
                comments.append({
                    "id": source_id * 100 + offset,
                    "source_analysis_id": source_id,
                    "source_video_title": title,
                    "content": (f"{title}-{label}-{offset}-" + "x" * 290),
                    "likes": 1000 - offset if source_id == 1 else 100 - offset,
                    "sentiment_label": label,
                    "post_time": f"2026-08-{1 + offset % 16:02d}T{offset % 24:02d}:00:00",
                    "username": "不得发送",
                    "rpid": source_id * 100 + offset,
                })
        samples = select_group_representative_comments(comments, rows, "nlp")
        self.assertEqual(len(samples), 40)
        self.assertEqual({sample["source_video_title"] for sample in samples}, {"来源一", "来源二", "来源三"})
        by_source = Counter(sample["source_video_title"] for sample in samples)
        self.assertTrue(all(by_source[title] >= 4 for title in ("来源一", "来源二", "来源三")))
        self.assertLessEqual(max(by_source.values()) - min(by_source.values()), 1)
        self.assertEqual({sample["sentiment"] for sample in samples}, {"positive", "negative", "neutral"})
        self.assertGreater(len({sample["time"][:10] for sample in samples}), 3)
        self.assertLessEqual(sum(len(sample["content"]) for sample in samples), 12_000)
        self.assertTrue(all("username" not in sample and "id" not in sample and "rpid" not in sample for sample in samples))


if __name__ == "__main__":
    unittest.main()
