from datetime import datetime
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import summary_routes
from models.database import AISummary, Analysis, Base, Comment
from services.ai_summary import filter_signature, input_signature
from services.sentiment_contract import LLM_SENTIMENT_SCHEMA_V2


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

    async def test_role_mode_combinations_coexist_and_stale_independently(self):
        config = {"provider": "deepseek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "fallback_model": "", "api_key": "secret"}
        generator = AsyncMock(return_value=("角色简评", "deepseek-chat", 1))
        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(summary_routes, "generate_summary", generator):
            quick = await summary_routes.create_summary(self.analysis_id, {"filters": {}, "interpretationView": "creator", "reportMode": "quick"})
            standard = await summary_routes.create_summary(self.analysis_id, {"filters": {}, "interpretationView": "creator", "reportMode": "standard"})
        self.assertNotEqual(quick["id"], standard["id"])
        self.assertEqual(standard["thinking_status"], "unsupported")
        self.assertEqual(generator.await_count, 2)
        db = self.sessions()
        db.query(Comment).first().content = "输入改变后不应复用旧报告"
        db.commit()
        db.close()
        listed = summary_routes.list_summaries(self.analysis_id)
        self.assertTrue(all(item["stale"] for item in listed))

    async def test_all_role_mode_combinations_are_cached_independently(self):
        config = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "fallback_model": "",
            "api_key": "secret",
        }
        generator = AsyncMock(return_value=("角色简评", "deepseek-v4-flash", 1))
        requests = [
            {"filters": {}, "interpretationView": view, "reportMode": mode}
            for view in ("public_opinion", "pr_risk", "creator", "news_editor")
            for mode in ("quick", "standard")
        ]
        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(
            summary_routes, "generate_summary", generator
        ):
            created = [
                await summary_routes.create_summary(self.analysis_id, request)
                for request in requests
            ]
            cached = [
                await summary_routes.create_summary(self.analysis_id, request)
                for request in requests
            ]

        self.assertEqual(generator.await_count, 8)
        self.assertEqual({item["id"] for item in created}, {item["id"] for item in cached})
        db = self.sessions()
        self.assertEqual(db.query(AISummary).count(), 8)
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

    async def test_duplicate_mode_is_recomputed_server_side_and_quality_context_is_complete(self):
        db = self.sessions()
        original = db.query(Comment).first()
        db.add_all([
            Comment(
                analysis_id=self.analysis_id,
                rpid=2,
                username="第二个重复账号",
                gender="女",
                ip_location="北京",
                content=original.content,
                likes=999,
                sentiment_label="negative",
                sentiment_score=0.1,
                post_time=datetime(2026, 7, 2, 12, 0),
            ),
            Comment(
                analysis_id=self.analysis_id,
                rpid=3,
                username="独立账号",
                gender="女",
                ip_location="北京",
                content="独立的真实评论",
                likes=1,
                sentiment_label="neutral",
                sentiment_score=0.5,
                post_time=datetime(2026, 7, 3, 12, 0),
            ),
        ])
        db.commit()
        db.close()
        config = {
            "provider": "custom", "base_url": "https://example.com/v1",
            "model": "mock-model", "fallback_model": "", "api_key": "secret",
        }
        received = {}

        async def fake_generate(comments, mode, _config, quality_context):
            received["comment_ids"] = [item["id"] for item in comments]
            received["mode"] = mode
            received["quality_context"] = quality_context
            return "模拟总结", "mock-model", len(comments)

        filters = {"duplicateMode": "deduplicate"}
        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(
            summary_routes, "generate_summary", new=AsyncMock(side_effect=fake_generate)
        ):
            response = await summary_routes.create_summary(self.analysis_id, {
                "filters": filters,
                # Deliberately untrusted client data must not become model input.
                "comments": [{"id": 999, "content": "伪造评论", "username": "泄漏对象"}],
            })

        self.assertEqual(response["matched_count"], 2)
        self.assertEqual(received["mode"], "nlp")
        self.assertNotIn(999, received["comment_ids"])
        self.assertEqual(len(received["comment_ids"]), 2)
        self.assertEqual(received["quality_context"], {
            "original_comment_count": 3,
            "duplicate_group_count": 1,
            "duplicate_involved_comments": 2,
            "duplicate_mode": "deduplicate",
            "after_duplicate_filter_count": 2,
            "final_matched_count": 2,
        })

    async def test_all_three_duplicate_modes_have_isolated_cache_records(self):
        db = self.sessions()
        original = db.query(Comment).first()
        db.add(Comment(
            analysis_id=self.analysis_id,
            rpid=2,
            content=original.content,
            likes=1,
            sentiment_label="positive",
            sentiment_score=0.9,
            post_time=datetime(2026, 7, 2, 12, 0),
        ))
        db.add(Comment(
            analysis_id=self.analysis_id,
            rpid=3,
            content="不重复的评论",
            likes=1,
            sentiment_label="neutral",
            sentiment_score=0.5,
            post_time=datetime(2026, 7, 3, 12, 0),
        ))
        db.commit()
        db.close()
        config = {
            "provider": "custom", "base_url": "https://example.com/v1",
            "model": "mock-model", "fallback_model": "", "api_key": "secret",
        }
        generator = AsyncMock(return_value=("模拟总结", "mock-model", 1))

        with patch.object(summary_routes, "get_task_config", return_value=config), patch.object(
            summary_routes, "generate_summary", generator
        ):
            responses = [
                await summary_routes.create_summary(self.analysis_id, {"filters": {"duplicateMode": mode}})
                for mode in ("include", "deduplicate", "exclude_groups")
            ]

        self.assertEqual(generator.await_count, 3)
        self.assertEqual(len({item["filter_hash"] for item in responses}), 3)
        self.assertEqual([item["matched_count"] for item in responses], [3, 2, 1])

    async def test_legacy_cache_without_duplicate_mode_is_reused_as_include(self):
        db = self.sessions()
        comment = db.query(Comment).first()
        legacy_filters = {
            "gender": "all", "dateFrom": "", "dateTo": "", "region": "", "sentiment": "all",
        }
        _, legacy_hash = filter_signature(legacy_filters)
        comments = [{
            "id": comment.id, "rpid": comment.rpid, "content": comment.content,
            "likes": comment.likes, "gender": comment.gender, "ip_location": comment.ip_location,
            "post_time": comment.post_time, "sentiment_label": comment.sentiment_label,
            "sentiment_llm_label": "",
        }]
        db.add(AISummary(
            analysis_id=self.analysis_id,
            filter_json=json.dumps(legacy_filters),
            filter_hash=legacy_hash,
            input_hash=input_signature(comments, "nlp"),
            summary_text="历史总结",
            provider="custom",
            model="legacy-model",
            matched_count=1,
            sampled_count=1,
        ))
        db.commit()
        db.close()

        listed = summary_routes.list_summaries(self.analysis_id)
        self.assertEqual(listed[0]["filters"]["duplicateMode"], "include")

        with patch.object(summary_routes, "get_task_config") as config, patch.object(
            summary_routes, "generate_summary", new=AsyncMock()
        ) as generator:
            response = await summary_routes.create_summary(self.analysis_id, {"filters": {}})

        self.assertEqual(response["summary_text"], "历史总结")
        self.assertEqual(response["filters"]["duplicateMode"], "include")
        config.assert_not_called()
        generator.assert_not_awaited()

    async def test_llm_summary_requires_full_v2_or_explicit_covered_subset(self):
        db = self.sessions()
        analysis = db.get(Analysis, self.analysis_id)
        analysis.mode = "llm"
        analysis.sentiment_llm_schema_version = 0
        first = db.query(Comment).first()
        first.sentiment_llm_label = "trust"
        first.sentiment_llm_style = "plain"
        first.sentiment_llm_schema_version = LLM_SENTIMENT_SCHEMA_V2
        db.add(Comment(
            analysis_id=self.analysis_id, rpid=2, content="尚未完成的评论", likes=1,
            sentiment_label="neutral", post_time=datetime(2026, 7, 2, 12, 0),
        ))
        db.commit()
        db.close()

        with self.assertRaises(HTTPException) as blocked:
            await summary_routes.create_summary(self.analysis_id, {"filters": {}})
        self.assertEqual(blocked.exception.status_code, 409)

        received = {}

        async def fake_generate(comments, mode, _config, quality_context):
            received["comments"] = comments
            received["mode"] = mode
            received["coverage"] = quality_context["v2_coverage"]
            return "已覆盖子集简报", "mock", len(comments)

        with patch.object(summary_routes, "get_task_config", return_value={"api_key": "test", "provider": "custom"}), patch.object(
            summary_routes, "generate_summary", new=AsyncMock(side_effect=fake_generate),
        ):
            response = await summary_routes.create_summary(self.analysis_id, {
                "filters": {}, "useV2CoveredSubset": True,
            })

        self.assertEqual(response["matched_count"], 1)
        self.assertEqual(received["mode"], "llm")
        self.assertEqual([comment["rpid"] for comment in received["comments"]], [1])
        self.assertEqual(received["coverage"]["scope"], "v2_covered_subset")
        self.assertEqual(received["coverage"]["v2_pending_comments"], 1)


if __name__ == "__main__":
    unittest.main()
