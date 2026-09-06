"""Local NLP and honest playback-time aggregation for sampled danmaku."""

from __future__ import annotations

from collections import Counter
from math import ceil
from typing import Iterable

from services.danmaku import SEGMENT_SECONDS
from services.sentiment import analyze_sentiment


SENTIMENT_LABELS = ("positive", "neutral", "negative")
# Keep ordinary videos readable while preserving exact millisecond boundaries.
BUCKET_SECONDS = (5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)
TARGET_BUCKET_COUNT = 48


def choose_bucket_seconds(duration_seconds: int) -> int:
    """Choose the smallest stable width that yields no more than 48 buckets."""
    duration = max(1, int(duration_seconds))
    for seconds in BUCKET_SECONDS:
        if ceil(duration / seconds) <= TARGET_BUCKET_COUNT:
            return seconds
    return BUCKET_SECONDS[-1]


def annotate_samples(samples: Iterable[object]) -> bool:
    """Fill missing or invalid local NLP labels without any model-service call."""
    changed = False
    for sample in samples:
        if (
            getattr(sample, "sentiment_label", None) not in SENTIMENT_LABELS
            or getattr(sample, "sentiment_score", None) is None
        ):
            label, score = analyze_sentiment(getattr(sample, "content", ""))
            sample.sentiment_label = label
            sample.sentiment_score = score
            changed = True
    return changed


def analyze_danmaku_items(items: Iterable[dict]) -> None:
    """Attach the same local NLP result before a newly fetched item is stored."""
    for item in items:
        label, score = analyze_sentiment(str(item.get("content") or ""))
        item["sentiment_label"] = label
        item["sentiment_score"] = score


def _bucket_coverage(
    start_ms: int,
    end_ms: int,
    *,
    requested_segments: set[int],
    failed_segments: set[int],
) -> tuple[str, list[str]]:
    """Describe retrieval coverage, never inferring absent segments as zero."""
    first = start_ms // (SEGMENT_SECONDS * 1000)
    last = max(first, (max(start_ms, end_ms - 1)) // (SEGMENT_SECONDS * 1000))
    details = []
    for index in range(first, last + 1):
        if index in failed_segments:
            details.append("failed")
        elif index in requested_segments:
            details.append("sampled")
        else:
            details.append("not_sampled")
    distinct = list(dict.fromkeys(details))
    if len(distinct) == 1:
        return distinct[0], distinct
    return "partial", distinct


def build_timeline(
    *,
    duration_seconds: int,
    requested_segment_indexes: Iterable[int],
    failed_segment_indexes: Iterable[int],
    samples: Iterable[object],
) -> dict:
    """Aggregate exact ``progress_ms`` into adaptive playback buckets.

    Every playback bucket carries acquisition coverage.  Counts therefore mean
    sampled counts only and a zero is never presented as evidence for an
    unrequested or failed video segment.
    """
    duration_ms = max(1, int(duration_seconds)) * 1000
    bucket_seconds = choose_bucket_seconds(duration_seconds)
    width_ms = bucket_seconds * 1000
    bucket_count = ceil(duration_ms / width_ms)
    requested = {int(index) for index in requested_segment_indexes if int(index) >= 0}
    failed = {int(index) for index in failed_segment_indexes if int(index) >= 0}
    counts: dict[int, Counter] = {}
    sampled_count = 0
    for sample in samples:
        progress_ms = getattr(sample, "progress_ms", None)
        label = getattr(sample, "sentiment_label", None)
        if not isinstance(progress_ms, int) or not 0 <= progress_ms < duration_ms:
            continue
        if label not in SENTIMENT_LABELS:
            continue
        index = min(progress_ms // width_ms, bucket_count - 1)
        counts.setdefault(index, Counter())[label] += 1
        sampled_count += 1

    buckets = []
    for index in range(bucket_count):
        start_ms = index * width_ms
        end_ms = min(duration_ms, start_ms + width_ms)
        coverage, detail = _bucket_coverage(
            start_ms, end_ms,
            requested_segments=requested,
            failed_segments=failed,
        )
        bucket = counts.get(index, Counter())
        positive = bucket["positive"]
        neutral = bucket["neutral"]
        negative = bucket["negative"]
        buckets.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "total": positive + neutral + negative,
            "coverage": coverage,
            "coverage_detail": detail,
        })

    return {
        "bucket_seconds": bucket_seconds,
        "buckets": buckets,
        "sampled_count": sampled_count,
    }
