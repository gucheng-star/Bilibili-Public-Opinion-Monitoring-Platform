import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.danmaku_timeline import (
    annotate_samples,
    build_timeline,
    choose_bucket_seconds,
)


class DanmakuTimelineTests(unittest.TestCase):
    def test_bucket_width_scales_with_video_duration(self):
        self.assertEqual(choose_bucket_seconds(60), 5)
        self.assertEqual(choose_bucket_seconds(720), 15)
        self.assertEqual(choose_bucket_seconds(3600), 120)

    def test_exact_progress_is_aggregated_without_rounding_playback_time(self):
        samples = [
            SimpleNamespace(progress_ms=14_999, sentiment_label="positive"),
            SimpleNamespace(progress_ms=15_000, sentiment_label="negative"),
            SimpleNamespace(progress_ms=719_999, sentiment_label="neutral"),
        ]
        timeline = build_timeline(
            duration_seconds=720,
            requested_segment_indexes=[0, 1],
            failed_segment_indexes=[],
            samples=samples,
        )
        self.assertEqual(timeline["bucket_seconds"], 15)
        self.assertEqual(timeline["buckets"][0]["positive"], 1)
        self.assertEqual(timeline["buckets"][0]["total"], 1)
        self.assertEqual(timeline["buckets"][1]["negative"], 1)
        self.assertEqual(timeline["buckets"][-1]["neutral"], 1)

    def test_coverage_distinguishes_unrequested_successful_and_failed_segments(self):
        timeline = build_timeline(
            duration_seconds=1_080,
            requested_segment_indexes=[0, 1],
            failed_segment_indexes=[1],
            samples=[],
        )
        # 1,080 seconds selects 30-second buckets: 0-360 sampled, 360-720 failed,
        # and the final six-minute segment was never requested.
        self.assertEqual(timeline["buckets"][0]["coverage"], "sampled")
        self.assertEqual(timeline["buckets"][12]["coverage"], "failed")
        self.assertEqual(timeline["buckets"][24]["coverage"], "not_sampled")
        self.assertTrue(all(item["total"] == 0 for item in timeline["buckets"]))

    def test_missing_or_invalid_labels_are_reanalysed_locally(self):
        samples = [
            SimpleNamespace(content="待分析", sentiment_label=None, sentiment_score=None),
            SimpleNamespace(content="错误标签", sentiment_label="other", sentiment_score=0.2),
        ]
        with patch("services.danmaku_timeline.analyze_sentiment", return_value=("neutral", 0.5)) as analyze:
            self.assertTrue(annotate_samples(samples))
        self.assertEqual(analyze.call_count, 2)
        self.assertEqual([(item.sentiment_label, item.sentiment_score) for item in samples], [("neutral", 0.5), ("neutral", 0.5)])


if __name__ == "__main__":
    unittest.main()
