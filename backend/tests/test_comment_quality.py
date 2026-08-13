from datetime import datetime, timedelta
import time
import unittest

from services.comment_quality import (
    annotate_exact_duplicates,
    apply_duplicate_mode,
    build_duplicate_statistics,
)


def comment(identifier, content, *, rpid=None, post_time=None):
    return {
        "id": identifier,
        "rpid": identifier if rpid is None else rpid,
        "content": content,
        "post_time": post_time,
    }


class ExactDuplicateQualityTests(unittest.TestCase):
    def test_exact_matching_keeps_all_character_differences_separate(self):
        comments = [
            comment(1, "完全相同"),
            comment(2, "完全相同"),
            comment(3, "完全相同 "),
            comment(4, "完全相同\n"),
            comment(5, "ABC"),
            comment(6, "abc"),
            comment(7, "ＡＢＣ"),
            comment(8, "赞👍"),
            comment(9, "赞👍️"),
            comment(10, "有\u200b零宽字符"),
            comment(11, "有零宽字符"),
        ]

        annotated = annotate_exact_duplicates(comments)

        duplicate_ids = [item["id"] for item in annotated if item["is_exact_duplicate"]]
        self.assertEqual(duplicate_ids, [1, 2])
        self.assertTrue(annotated[0]["duplicate_group_key"].startswith("sha256:"))
        self.assertNotIn("完全相同", annotated[0]["duplicate_group_key"])

    def test_missing_and_empty_content_do_not_form_groups_but_space_does(self):
        comments = [
            comment(1, None),
            comment(2, None),
            comment(3, ""),
            comment(4, ""),
            comment(5, "   "),
            comment(6, "   "),
        ]

        annotated = annotate_exact_duplicates(comments)

        self.assertFalse(any(item["is_exact_duplicate"] for item in annotated[:4]))
        self.assertTrue(all(item["is_exact_duplicate"] for item in annotated[4:]))
        self.assertEqual(build_duplicate_statistics(annotated), {
            "group_count": 1,
            "involved_comments": 2,
            "duplicate_excess": 1,
            "involved_ratio": 2 / 6,
        })

    def test_canonical_selection_uses_time_then_rpid_then_database_id(self):
        earliest = datetime(2026, 8, 1, 8)
        comments = [
            comment(9, "同一内容", rpid=30, post_time=earliest + timedelta(minutes=1)),
            comment(8, "同一内容", rpid=20, post_time=earliest),
            comment(7, "同一内容", rpid=10, post_time=earliest),
            comment(6, "同一内容", rpid=10, post_time=earliest),
            comment(5, "缺失时间", rpid=1, post_time=None),
            comment(4, "缺失时间", rpid=99, post_time=None),
        ]

        annotated = annotate_exact_duplicates(comments)
        canonical_ids = {
            item["id"] for item in annotated if item["is_duplicate_canonical"]
        }

        self.assertEqual(canonical_ids, {6, 5})

    def test_three_modes_have_stable_counts_and_never_mutate_original_records(self):
        comments = [
            comment(3, "重复", post_time=datetime(2026, 8, 2)),
            comment(1, "重复", post_time=datetime(2026, 8, 1)),
            comment(2, "独立", post_time=datetime(2026, 8, 3)),
        ]
        annotated = annotate_exact_duplicates(comments)

        self.assertEqual([item["id"] for item in apply_duplicate_mode(annotated, "include")], [3, 1, 2])
        self.assertEqual([item["id"] for item in apply_duplicate_mode(annotated, "deduplicate")], [1, 2])
        self.assertEqual([item["id"] for item in apply_duplicate_mode(annotated, "exclude_groups")], [2])
        self.assertNotIn("is_exact_duplicate", comments[0])
        with self.assertRaises(ValueError):
            apply_duplicate_mode(annotated, "remove")

    def test_thousand_comments_are_annotated_and_aggregated_in_linear_time(self):
        comments = [
            comment(index, f"独立评论-{index}", post_time=datetime(2026, 8, 1))
            for index in range(1, 981)
        ] + [
            comment(981 + index, "重复样本", post_time=datetime(2026, 8, 1))
            for index in range(20)
        ]

        started = time.perf_counter()
        annotated = annotate_exact_duplicates(comments)
        statistics = build_duplicate_statistics(annotated)
        elapsed = time.perf_counter() - started

        self.assertEqual(len(annotated), 1_000)
        self.assertEqual(statistics["group_count"], 1)
        self.assertEqual(statistics["involved_comments"], 20)
        self.assertEqual(statistics["duplicate_excess"], 19)
        # Wide enough for loaded Windows CI while still detecting accidental quadratic work.
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
