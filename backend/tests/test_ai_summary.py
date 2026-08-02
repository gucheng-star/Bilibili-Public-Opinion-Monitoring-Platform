from datetime import datetime, timedelta
import json
import unittest

from services.ai_summary import (
    MAX_SAMPLE_CHARACTERS,
    MAX_SAMPLE_COMMENTS,
    apply_filters,
    build_summary_messages,
    input_signature,
    normalize_filters,
    select_representative_comments,
)


def make_comment(index, *, label="positive", llm_label="joy", gender="男", region="广东"):
    return {
        "id": index,
        "username": f"user-{index}",
        "content": f"第{index}条具有代表性的评论内容" + ("观点" * (index % 5)),
        "likes": index,
        "gender": gender,
        "ip_location": f"IP属地：{region}",
        "post_time": datetime(2026, 7, 1) + timedelta(hours=index),
        "sentiment_label": label,
        "sentiment_llm_label": llm_label,
    }


class AISummaryTests(unittest.TestCase):
    def test_normalize_and_apply_all_filters_with_inclusive_end_date(self):
        comments = [
            make_comment(1, label="positive", gender="男", region="广东"),
            make_comment(2, label="negative", gender="女", region="北京"),
        ]
        filters = normalize_filters({
            "gender": "male",
            "dateFrom": "2026-07-01",
            "dateTo": "2026-07-01",
            "region": "广东",
            "sentiment": "positive",
        }, "nlp")

        matched = apply_filters(comments, filters, "nlp")

        self.assertEqual([comment["id"] for comment in matched], [1])
        with self.assertRaises(ValueError):
            normalize_filters({"sentiment": "joy"}, "nlp")

    def test_llm_mode_uses_new_main_emotion_labels(self):
        comments = [
            make_comment(1, llm_label="support"),
            make_comment(2, llm_label="anger"),
        ]
        filters = normalize_filters({"sentiment": "support"}, "llm")

        matched = apply_filters(comments, filters, "llm")

        self.assertEqual([comment["id"] for comment in matched], [1])

    def test_sampling_is_deterministic_bounded_and_private(self):
        labels = ["neutral", "joy", "support", "anticipation", "surprise", "anger", "sadness", "concern", "disgust"]
        comments = [make_comment(i, llm_label=labels[i % len(labels)]) for i in range(1, 121)]

        first = select_representative_comments(comments, "llm")
        second = select_representative_comments(list(reversed(comments)), "llm")

        self.assertEqual(first, second)
        self.assertLessEqual(len(first), MAX_SAMPLE_COMMENTS)
        self.assertLessEqual(sum(len(item["content"]) for item in first), MAX_SAMPLE_CHARACTERS)
        self.assertIn(120, [comment["likes"] for comment in first])
        self.assertTrue(set(labels).issubset({comment["sentiment"] for comment in first}))
        self.assertTrue(all("id" not in comment and "username" not in comment for comment in first))

    def test_input_hash_tracks_content_and_mode_label_changes(self):
        comments = [make_comment(1)]
        original = input_signature(comments, "nlp")
        comments[0]["content"] = "已经改变"
        changed_content = input_signature(comments, "nlp")
        comments[0]["sentiment_label"] = "negative"
        changed_label = input_signature(comments, "nlp")

        self.assertNotEqual(original, changed_content)
        self.assertNotEqual(changed_content, changed_label)

    def test_prompt_marks_samples_untrusted_without_private_fields(self):
        samples = select_representative_comments([make_comment(1)], "nlp")
        messages = build_summary_messages({"total": 1}, samples)
        prompt = json.dumps(messages, ensure_ascii=False)

        self.assertIn("不可信", prompt)
        self.assertNotIn("user-1", prompt)
        self.assertIn("120至220字", prompt)


if __name__ == "__main__":
    unittest.main()
