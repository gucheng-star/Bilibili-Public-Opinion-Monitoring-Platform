import json
import unittest
from unittest.mock import AsyncMock, patch

from services.sentiment_llm import (
    FEW_SHOT_EXAMPLES, _analyze_comment_batch, _build_comment_contexts,
    _build_few_shot_messages, _build_llm_batches, _build_protocol_payload,
    _serialize_payload, batch_analyze_llm, summarize_sentiment_llm,
)
from services.sentiment_contract import V1_EMOTION_LABELS, V2_EMOTION_LABELS, V2_STYLE_LABELS


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
            prompt_payload = json.loads(user_message["content"])
            prompt_items = prompt_payload["comments"]
            result_items = json.loads(assistant_message["content"])["items"]
            self.assertLessEqual(len(prompt_items), 10)
            self.assertEqual([item["id"] for item in result_items], [item["id"] for item in prompt_items])
            self.assertLessEqual(len(prompt_payload.get("video_context", {})), 1)
        self.assertEqual(
            sum(len(json.loads(message["content"])["comments"]) for message in messages[::2]),
            len(FEW_SHOT_EXAMPLES),
        )
        self.assertEqual({example["emotion"] for example in FEW_SHOT_EXAMPLES}, V2_EMOTION_LABELS)
        self.assertEqual({example["style"] for example in FEW_SHOT_EXAMPLES}, V2_STYLE_LABELS)

        prompt_payloads = [json.loads(message["content"]) for message in messages[::2]]
        context_example = next(
            payload
            for payload in prompt_payloads
            if "video_context" in payload
        )
        target = next(
            item
            for item in context_example["comments"]
            if "root_comment" in item and "parent_comment" in item
        )
        self.assertIn("愤怒", context_example["video_context"]["title"])
        self.assertIn("气", target["root_comment"])
        self.assertIn("气", target["parent_comment"])
        assistant_message = messages[prompt_payloads.index(context_example) * 2 + 1]
        result_by_id = {item["id"]: item for item in json.loads(assistant_message["content"])["items"]}
        self.assertEqual(result_by_id[target["id"]], {"id": target["id"], "emotion": "trust", "style": "plain"})

    def test_summary_retains_v1_compatibility_keys_alongside_v2_counts(self):
        counts = summarize_sentiment_llm([
            {"sentiment_llm_label": "trust"},
            {"sentiment_llm_label": "fear"},
            {"sentiment_llm_label": "anger"},
        ])

        self.assertEqual(set(counts), V1_EMOTION_LABELS | V2_EMOTION_LABELS)
        self.assertEqual(counts["trust"], 1)
        self.assertEqual(counts["fear"], 1)
        self.assertEqual(counts["anger"], 1)
        self.assertEqual(counts["support"], 0)
        self.assertEqual(counts["concern"], 0)
        self.assertEqual(counts["sarcasm"], 0)

    async def test_sends_context_but_labels_only_the_target_comment(self):
        contexts = _build_comment_contexts(self.comments)
        fake_response = {"items": [{"id": "item-1", "emotion": "joy", "style": "plain"}]}

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response)
        ) as call_llm:
            labels = await _analyze_comment_batch([self.comments[2]], {}, contexts)

        self.assertEqual(labels, {"12": {"emotion": "joy", "style": "plain"}})
        payload = json.loads(call_llm.await_args.args[0][-1]["content"])
        self.assertEqual(payload["comments"][0]["id"], "item-1")
        self.assertNotIn("12", call_llm.await_args.args[0][-1]["content"])
        self.assertEqual(payload["comments"][0]["root_comment"], "root text")
        self.assertEqual(payload["comments"][0]["parent_comment"], "parent text")

    async def test_uses_short_batch_ids_and_maps_a_long_bilibili_rpid_back_locally(self):
        comment = {
            "rpid": 310116267393,
            "content": "计划生育是我国的基本国策，生不生、生多少都是自愿的",
        }
        fake_response = {
            "items": [{"id": "item-1", "emotion": "neutral", "style": "plain"}],
        }

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response),
        ) as call_llm:
            labels = await _analyze_comment_batch([comment], {}, {})

        self.assertEqual(labels, {"310116267393": {"emotion": "neutral", "style": "plain"}})
        request_text = call_llm.await_args.args[0][-1]["content"]
        self.assertIn('"id":"item-1"', request_text)
        self.assertNotIn("310116267393", request_text)

    async def test_reports_the_protocol_field_without_echoing_model_output(self):
        fake_response = {
            "items": [{"id": "model-invented-id", "emotion": "neutral", "style": "plain"}],
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
            "items": [{"id": "item-1", "emotion": "neutral ", "style": "plain"}],
        }
        config = {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "secret-api-key-must-not-be-logged",
        }

        with (
            patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response)),
            self.assertLogs("services.sentiment_llm", level="WARNING") as captured,
            self.assertRaisesRegex(ValueError, "包含非法情感或表达风格"),
        ):
            await _analyze_comment_batch([comment], config, {})

        diagnostic = "\n".join(captured.output)
        self.assertIn('provider="deepseek"', diagnostic)
        self.assertIn('model="deepseek-v4-flash"', diagnostic)
        self.assertIn('emotion="neutral "', diagnostic)
        self.assertNotIn(comment["content"], diagnostic)
        self.assertNotIn(config["api_key"], diagnostic)

    async def test_accepts_sarcasm_as_style_without_retry(self):
        response = {"items": [{"id": "item-1", "emotion": "anger", "style": "sarcasm"}]}

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=response),
        ) as call_llm:
            labels = await _analyze_comment_batch([self.comments[2]], {}, {})

        self.assertEqual(labels, {"12": {"emotion": "anger", "style": "sarcasm"}})
        self.assertEqual(call_llm.await_count, 1)
        system_prompt = call_llm.await_args.args[0][0]["content"]
        self.assertIn("sarcasm > rhetorical > meme > hyperbole > plain", system_prompt)

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

        self.assertEqual(len(received_contexts), 1)
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

        self.assertEqual(analyze.await_count, 1)
        self.assertEqual(progress[-1], 7)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress, [2, 7])
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

    async def test_strict_v2_response_rejects_extra_fields_ids_and_enums(self):
        invalid_responses = [
            {"items": [], "extra": True},
            {"items": [{"id": "item-1", "emotion": "neutral", "style": "plain", "reason": "x"}]},
            {"items": [{"id": "item-1", "emotion": "neutral", "style": "plain"}, {"id": "item-1", "emotion": "joy", "style": "plain"}]},
            {"items": [{"id": "item-1", "emotion": "support", "style": "plain"}]},
            {"items": [{"id": "item-1", "emotion": "neutral", "style": "unknown"}]},
        ]
        for response in invalid_responses:
            with self.subTest(response=response), patch(
                "services.sentiment_llm._call_llm", new=AsyncMock(return_value=response),
            ):
                with self.assertRaises(ValueError):
                    await _analyze_comment_batch([self.comments[0]], {}, {})

    async def test_strict_v2_response_rejects_missing_ids_without_extra_fields(self):
        response = {"items": [{"id": "item-1", "emotion": "neutral", "style": "plain"}]}

        with (
            patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=response)),
            self.assertRaisesRegex(ValueError, "缺少评论结果"),
        ):
            await _analyze_comment_batch(self.comments[:2], {}, {})

    async def test_payload_is_bounded_private_and_title_is_sent_once(self):
        root = {"rpid": 1, "content": "根" * 300, "root_rpid": 1, "parent_rpid": None, "username": "private"}
        target = {
            "rpid": 2, "content": "安慰" * 600, "root_rpid": 1, "parent_rpid": 1,
            "username": "secret-user", "ip_location": "secret-ip", "uid": 99,
        }
        contexts = _build_comment_contexts([root, target])
        response = {"items": [{"id": "item-1", "emotion": "trust", "style": "plain"}]}
        with patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=response)) as call_llm:
            labels = await _analyze_comment_batch([target], {}, contexts, video_title="愤怒标题" * 100)
        payload_text = call_llm.await_args.args[0][-1]["content"]
        payload = json.loads(payload_text)
        item = payload["comments"][0]
        self.assertEqual(labels, {"2": {"emotion": "trust", "style": "plain"}})
        self.assertLessEqual(len(payload["video_context"]["title"]), 200)
        self.assertEqual(payload_text.count("video_context"), 1)
        self.assertLessEqual(len(item["text"]), 1000)
        self.assertLessEqual(len(item["root_comment"]), 240)
        self.assertNotIn("parent_comment", item)
        self.assertNotIn("secret-user", payload_text)
        self.assertNotIn("secret-ip", payload_text)
        self.assertNotIn("99", payload_text)
        self.assertIn("不能转移情感", call_llm.await_args.args[0][0]["content"])

    async def test_angry_parent_and_title_do_not_replace_target_label_in_protocol_snapshot(self):
        comments = [
            {"rpid": 1, "content": "根评论", "root_rpid": 1, "parent_rpid": None},
            {"rpid": 2, "content": "气死我了", "root_rpid": 1, "parent_rpid": 1},
            {"rpid": 3, "content": "别难过，抱抱你", "root_rpid": 1, "parent_rpid": 2},
        ]
        response = {"items": [{"id": "item-1", "emotion": "trust", "style": "plain"}]}
        with patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=response)) as call_llm:
            labels = await _analyze_comment_batch(
                [comments[2]], {}, _build_comment_contexts(comments), video_title="愤怒争议视频",
            )
        payload = json.loads(call_llm.await_args.args[0][-1]["content"])
        self.assertEqual(labels, {"3": {"emotion": "trust", "style": "plain"}})
        self.assertEqual(payload["comments"][0]["root_comment"], "根评论")
        self.assertEqual(payload["comments"][0]["parent_comment"], "气死我了")
        self.assertEqual(payload["comments"][0]["text"], "别难过，抱抱你")

    async def test_dynamic_max_tokens_and_blank_comments_do_not_call_model(self):
        response = {"items": [{"id": "item-1", "emotion": "neutral", "style": "plain"}]}
        with patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=response)) as call_llm:
            await _analyze_comment_batch([self.comments[0]], {}, {})
        self.assertEqual(call_llm.await_args.kwargs["temperature"], 0)
        self.assertEqual(call_llm.await_args.kwargs["max_tokens"], 104)
        ten_comments = [
            {"rpid": index, "content": f"comment {index}"}
            for index in range(1, 11)
        ]
        ten_response = {
            "items": [
                {"id": f"item-{index}", "emotion": "neutral", "style": "plain"}
                for index in range(1, 11)
            ],
        }
        with patch("services.sentiment_llm._call_llm", new=AsyncMock(return_value=ten_response)) as call_llm:
            await _analyze_comment_batch(ten_comments, {}, {})
        self.assertEqual(call_llm.await_args.kwargs["max_tokens"], 464)
        with patch("services.sentiment_llm._analyze_batch_with_retry", new=AsyncMock()) as retry:
            blank = await batch_analyze_llm([{"rpid": 1, "content": "   "}], {})
        retry.assert_not_awaited()
        self.assertEqual(blank[0]["sentiment_llm_label"], "neutral")
        self.assertEqual(blank[0]["sentiment_llm_style"], "plain")

    def test_deterministic_ten_item_and_character_budget_batches(self):
        comments = [{"rpid": index, "content": f"comment-{index}"} for index in range(1, 12)]
        first = _build_llm_batches(comments, {})
        second = _build_llm_batches(comments, {})
        self.assertEqual([[item["rpid"] for item in batch] for batch in first], [[item["rpid"] for item in batch] for batch in second])
        self.assertEqual([len(batch) for batch in first], [10, 1])
        long_comments = [{"rpid": index, "content": "x" * 1000} for index in range(1, 11)]
        char_batches = _build_llm_batches(long_comments, {})
        self.assertGreater(len(char_batches), 1)
        for batch in char_batches:
            _, payload = _build_protocol_payload(batch, {})
            self.assertLessEqual(len(_serialize_payload(payload)), 6000)


if __name__ == "__main__":
    unittest.main()
