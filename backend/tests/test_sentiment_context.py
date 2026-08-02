import unittest
from unittest.mock import AsyncMock, patch

from services.sentiment_llm import _analyze_comment_batch, _build_comment_contexts, batch_analyze_llm


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

    async def test_sends_context_but_labels_only_the_target_comment(self):
        contexts = _build_comment_contexts(self.comments)
        fake_response = {"items": [{"id": "12", "label": "joy", "style": "meme", "confidence": 0.9}]}

        with patch(
            "services.sentiment_llm._call_llm", new=AsyncMock(return_value=fake_response)
        ) as call_llm:
            labels = await _analyze_comment_batch([self.comments[2]], {}, contexts)

        self.assertEqual(labels, {"12": {"label": "joy", "style": "meme"}})
        request_text = call_llm.await_args.args[0][-1]["content"]
        self.assertIn('"id": "12"', request_text)
        self.assertIn('"root_comment": "root text"', request_text)
        self.assertIn('"parent_comment": "parent text"', request_text)
        self.assertIn("Classify the item's text only", request_text)

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


if __name__ == "__main__":
    unittest.main()
