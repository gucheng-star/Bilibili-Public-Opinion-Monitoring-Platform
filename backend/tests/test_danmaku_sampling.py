import unittest
from unittest.mock import AsyncMock, patch

from services.danmaku import (
    MAX_REQUEST_SEGMENTS,
    build_segment_plan,
    fetch_sampled_danmaku,
    parse_segment_payload,
    select_uniform_samples,
)


def varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def field(number: int, value: bytes | int) -> bytes:
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    return varint((number << 3) | 2) + varint(len(value)) + value


def element(progress_ms: int, content: str, pool: int = 0, mode: int = 1) -> bytes:
    return field(2, progress_ms) + field(3, mode) + field(7, content.encode()) + field(11, pool)


def payload(*elements: bytes) -> bytes:
    return b"".join(field(1, item) for item in elements)


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


class DanmakuSamplingTests(unittest.IsolatedAsyncioTestCase):
    def test_segment_plan_for_short_video_and_low_limit_is_reproducible(self):
        self.assertEqual([(item.index, item.target_count) for item in build_segment_plan(50, 100)], [(0, 100)])
        expected = [(0, 1), (2, 1)]
        self.assertEqual([(item.index, item.target_count) for item in build_segment_plan(900, 2)], expected)
        self.assertEqual([(item.index, item.target_count) for item in build_segment_plan(900, 2)], expected)

    def test_long_video_requests_no_more_than_guard_and_spreads_remainder(self):
        plan = build_segment_plan(25 * 360, 100)
        self.assertEqual(len(plan), MAX_REQUEST_SEGMENTS)
        self.assertEqual(sum(item.target_count for item in plan), 100)
        self.assertEqual({item.target_count for item in plan}, {4, 5})
        self.assertEqual(plan[0].index, 0)
        self.assertEqual(plan[-1].index, 24)

    def test_parser_keeps_only_ordinary_pool_and_uniform_sampling_is_not_prefix(self):
        ordinary, ignored = parse_segment_payload(payload(
            element(5000, "第一条"),
            element(1000, "字幕", pool=1),
            element(1000, ""),
            element(1000, "第二条"),
            element(3000, "第三条"),
        ))
        self.assertEqual(ignored, 2)
        self.assertEqual([item["content"] for item in ordinary], ["第一条", "第二条", "第三条"])
        selected = select_uniform_samples(ordinary, 2)
        self.assertEqual([item["content"] for item in selected], ["第二条", "第一条"])

    def test_parser_filters_advanced_and_code_modes_even_in_normal_pool(self):
        ordinary, ignored = parse_segment_payload(payload(
            element(1000, "普通", mode=1),
            element(1200, "普通模式二", mode=2),
            element(1400, "普通模式三", mode=3),
            element(2000, "高级", mode=7),
            element(3000, "代码", mode=8),
        ))
        self.assertEqual([item["content"] for item in ordinary], ["普通", "普通模式二", "普通模式三"])
        self.assertEqual(ignored, 2)

    async def test_partial_segment_failure_remains_honest_and_requests_stay_sequential(self):
        client = FakeClient([
            FakeResponse(200, payload(element(1000, "A"), element(2000, "B"))),
            FakeResponse(500), FakeResponse(500), FakeResponse(500),
        ])
        progress = []
        snapshots = []
        sleep = AsyncMock()
        result = await fetch_sampled_danmaku(
            client, 123, 720, 2,
            progress_callback=lambda item: (progress.append(item), snapshots.append((
                item.requested_segments, list(item.requested_segment_indexes), len(item.kept),
            ))),
            sleep=sleep,
        )
        self.assertEqual(result.requested_segments, 2)
        self.assertEqual(result.requested_segment_indexes, [0, 1])
        self.assertEqual(result.successful_segments, 1)
        self.assertEqual(result.failed_segments, [1])
        self.assertEqual(len(result.kept), 1)
        self.assertEqual([item.successful_segments for item in progress], [1, 1])
        self.assertEqual(snapshots, [(1, [0], 1), (2, [0, 1], 1)])
        self.assertEqual([call[1]["params"]["segment_index"] for call in client.calls], [1, 2, 2, 2])

    async def test_all_failed_segments_return_no_samples_for_retryable_task_status(self):
        client = FakeClient([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
        with patch("services.danmaku.REQUEST_DELAY", 0):
            result = await fetch_sampled_danmaku(client, 123, 50, 1, sleep=AsyncMock())
        self.assertEqual(result.successful_segments, 0)
        self.assertEqual(result.failed_segments, [0])
        self.assertEqual(result.kept, [])


if __name__ == "__main__":
    unittest.main()
