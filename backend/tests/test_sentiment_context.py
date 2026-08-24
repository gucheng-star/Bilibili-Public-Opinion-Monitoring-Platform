import json
import unittest
from unittest.mock import AsyncMock, patch

from services.sentiment_llm import (
    FEW_SHOT_EXAMPLES, _analyze_comment_batch, _build_comment_contexts,
    _build_few_shot_messages, batch_analyze_llm,
)


class SentimentContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.comments = [
            {"rpid": 10, "content": "root text", "root_rpid": 10, "parent_rpid": None},
            {"rpid": 11, "content": "parent text", "root_rpid": 10, "parent_rpid": 10},
            {"rpid": 12, "content": "target text", "root_rpid": 10, "parent_rpid": 11},
        ]

    def test_builds_only_ancestor_context_for_replies(self):
        contexts = _build_comment_contexts(self.comments)

        self.assertNotIn("10", contexts)
        self.assertEqual(contexts["11"], {"root_comment": "root text"})
        self.assertEqual(
            contexts["12"],
            {"root_comment": "root text", "parent_comment": "parent text"},
        )

    def test_few_shot_examples_use_the_batch_items_protocol(self):
        messages = _build_few_shot_messages()

        self.assertEqual(len(messages) % 2, 0)
        for user_message, assistant_message in zip(messages[::2], messages[1::2]):
            prompt_items = json.loads(user_message["content"])["comments"]
            result_items = json.loads(assistant_message["content"])["items"]
            self.assertLessEqual(len(prompt_items), 5)
            self.assertEqual([item["id"] for item in result_items], [item["id"] for item in prompt_items])
        self.assertEqual(
            sum(len(json.loads(message["content"])["comments"]) for message in messages[::2]),
            len(FEW_SHOT_EXAMPLES),
        )

    async def test_sends_context_but_labels_only_the_target_comment(self):
        contexts = _build_comment_contexts(self.comments)
        fake_response = {"items": [{"id": "item-1", "label": "joy", "confidence": 0.9}]}

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response)
        ) as call_llm:
            labels = await _analyze_comment_batch([self.comments[2]], {}, contexts)

        self.assertEqual(labels, {"12": {"label": "joy", "style": "plain"}})
        request_text = call_llm.await_args.args[0][-1]["content"]
        self.assertIn('"id": "item-1"', request_text)
        self.assertNotIn('"id": "12"', request_text)
        self.assertIn('"root_comment": "root text"', request_text)
        self.assertIn('"parent_comment": "parent text"', request_text)
        self.assertIn("Classify the item's text only", request_text)

    async def test_uses_short_batch_ids_and_maps_a_long_bilibili_rpid_back_locally(self):
        comment = {
            "rpid": 310116267393,
            "content": "计划生育是我国的基本国策，生不生、生多少都是自愿的",
        }
        fake_response = {
            "items": [{"id": "item-1", "label": "neutral", "confidence": 0.9}],
        }

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response),
        ) as call_llm:
            labels = await _analyze_comment_batch([comment], {}, {})

        self.assertEqual(labels, {"310116267393": {"label": "neutral", "style": "plain"}})
        request_text = call_llm.await_args.args[0][-1]["content"]
        self.assertIn('"id": "item-1"', request_text)
        self.assertNotIn("310116267393", request_text)

    async def test_reports_the_protocol_field_without_echoing_model_output(self):
        fake_response = {
            "items": [{"id": "model-invented-id", "label": "neutral"}],
        }

        with (
            patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response)),
            self.assertRaisesRegex(ValueError, "包含意外的批次条目 ID") as raised,
        ):
            await _analyze_comment_batch([self.comments[0]], {}, {})

        self.assertNotIn("model-invented-id", str(raised.exception))

    async def test_logs_bounded_invalid_label_without_comment_or_api_key(self):
        comment = {
            "rpid": 310116267393,
            "content": "不应进入协议诊断日志的评论正文",
        }
        fake_response = {
            "items": [{"id": "item-1", "label": "neutral "}],
        }
        config = {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "secret-api-key-must-not-be-logged",
        }

        with (
            patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response)),
            self.assertLogs("services.sentiment_llm", level="WARNING") as captured,
            self.assertRaisesRegex(ValueError, "包含非法情感标签"),
        ):
            await _analyze_comment_batch([comment], config, {})

        diagnostic = "\n".join(captured.output)
        self.assertIn('provider="deepseek"', diagnostic)
        self.assertIn('model="deepseek-v4-flash"', diagnostic)
        self.assertIn('label="neutral "', diagnostic)
        self.assertIn("label_type=str", diagnostic)
        self.assertNotIn(comment["content"], diagnostic)
        self.assertNotIn(config["api_key"], diagnostic)

    async def test_accepts_sarcasm_as_one_main_label_without_retry(self):
        response = {"items": [{"id": "item-1", "label": "sarcasm"}]}

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=response),
        ) as call_llm:
            labels = await _analyze_comment_batch([self.comments[2]], {}, {})

        self.assertEqual(labels, {"12": {"label": "sarcasm", "style": "plain"}})
        self.assertEqual(call_llm.await_count, 1)
        request_text = call_llm.await_args.args[0][-1]["content"]
        self.assertIn("disgust、sarcasm", request_text)
        self.assertNotIn('"style":', request_text)

    async def test_keeps_context_when_parent_and_reply_are_in_different_batches(self):
        comments = self.comments + [
            {"rpid": 13, "content": "other 1"},
            {"rpid": 14, "content": "other 2"},
            {"rpid": 15, "content": "other 3"},
        ]
        received_contexts = []

        async def fake_analyze(batch, _config, contexts):
            received_contexts.append(contexts)
            return {str(comment["rpid"]): {"label": "joy", "style": "plain"} for comment in batch}

        with patch("services.sentiment_llm._analyze_batch_with_retry", side_effect=fake_analyze):
            analyzed = await batch_analyze_llm(comments, {}, concurrency=1)

        self.assertEqual(len(received_contexts), 2)
        self.assertEqual(
            received_contexts[0]["12"],
            {"root_comment": "root text", "parent_comment": "parent text"},
        )
        self.assertTrue(all(comment["sentiment_llm_label"] == "joy" for comment in analyzed))
        self.assertTrue(all(comment["sentiment_llm_style"] == "plain" for comment in analyzed))

    async def test_reanalysis_uses_completed_parent_only_as_context(self):
        parent, target = self.comments[1], self.comments[2]
        received_targets = []
        received_contexts = []

        async def fake_analyze(batch, _config, contexts):
            received_targets.extend(comment["rpid"] for comment in batch)
            received_contexts.append(contexts)
            return {str(comment["rpid"]): {"label": "joy", "style": "plain"} for comment in batch}

        with patch("services.sentiment_llm._analyze_batch_with_retry", side_effect=fake_analyze):
            analyzed = await batch_analyze_llm(
                [target], {}, concurrency=1, context_comments=[parent, target],
            )

        self.assertEqual(received_targets, [12])
        self.assertEqual(received_contexts[0]["12"], {"parent_comment": "parent text"})
        self.assertEqual(analyzed[0]["sentiment_llm_label"], "joy")

    async def test_reports_every_completed_batch_including_blank_comments(self):
        comments = [
            {"rpid": index, "content": "" if index in {2, 7} else f"comment {index}"}
            for index in range(1, 8)
        ]
        progress = []

        async def fake_analyze(batch, _config, _contexts):
            return {
                str(comment["rpid"]): {"label": "neutral", "style": "plain"}
                for comment in batch
            }

        with patch("services.sentiment_llm._analyze_batch_with_retry", side_effect=fake_analyze) as analyze:
            analyzed = await batch_analyze_llm(
                comments, {}, concurrency=1, progress_callback=progress.append,
            )

        self.assertEqual(analyze.await_count, 2)
        self.assertEqual(progress[-1], 7)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress, [1, 5, 6, 7])
        self.assertEqual(analyzed[1]["sentiment_llm_label"], "neutral")

    async def test_recovers_a_malformed_five_comment_batch_by_splitting_it(self):
        comments = [
            {"rpid": index, "content": f"comment {index}"}
            for index in range(1, 6)
        ]
        call_sizes = []

        async def fake_analyze(batch, _config, _contexts):
            call_sizes.append(len(batch))
            if len(batch) == 5:
                try:
                    raise ValueError("模型返回了重复的评论 ID")
                except ValueError as cause:
                    raise RuntimeError("LLM batch failed after 3 attempts") from cause
            return {
                str(comment["rpid"]): {"label": "neutral", "style": "plain"}
                for comment in batch
            }

        with patch("services.sentiment_llm._analyze_batch_with_retry", side_effect=fake_analyze):
            analyzed = await batch_analyze_llm(comments, {}, concurrency=1)

        self.assertEqual(call_sizes, [5, 2, 3])
        self.assertTrue(all(comment["sentiment_llm_label"] == "neutral" for comment in analyzed))

    async def test_does_not_split_a_network_failure_into_more_paid_requests(self):
        comments = [
            {"rpid": index, "content": f"comment {index}"}
            for index in range(1, 6)
        ]
        network_failure = RuntimeError("模型服务响应超时")

        with patch(
            "services.sentiment_llm._analyze_batch_with_retry",
            new=AsyncMock(side_effect=network_failure),
        ) as analyze:
            with self.assertRaisesRegex(RuntimeError, "模型服务响应超时"):
                await batch_analyze_llm(comments, {}, concurrency=1)

        self.assertEqual(analyze.await_count, 1)


if __name__ == "__main__":
    unittest.main()
