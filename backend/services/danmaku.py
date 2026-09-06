"""Bilibili segmented danmaku retrieval with conservative deterministic sampling."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from math import ceil
from typing import Awaitable, Callable

import httpx

from config import REQUEST_DELAY
from services.bilibili import _headers
from services.logging_config import get_logger, log_event


SEGMENT_SECONDS = 6 * 60
MAX_SAMPLES_PER_SEGMENT = 500
SEGMENT_RETRY_ATTEMPTS = 3
NORMAL_DANMAKU_MODES = set(range(1, 7))
logger = get_logger("danmaku")


@dataclass(frozen=True)
class SegmentPlan:
    """A requested six-minute segment and its deterministic sample target."""

    index: int
    target_count: int


@dataclass
class DanmakuFetchResult:
    requested_segments: int = 0
    requested_segment_indexes: list[int] = field(default_factory=list)
    successful_segments: int = 0
    kept: list[dict] = field(default_factory=list)
    ignored_count: int = 0
    failed_segments: list[int] = field(default_factory=list)


def segment_count_for_duration(duration_seconds: int | float) -> int:
    return max(1, ceil(max(0, duration_seconds) / SEGMENT_SECONDS))


def _evenly_spaced_indices(total: int, count: int) -> list[int]:
    """Choose sorted, distinct positions spanning a finite zero-based range."""
    if total <= 0 or count <= 0:
        return []
    count = min(total, count)
    if count == total:
        return list(range(total))
    return [((2 * index + 1) * total) // (2 * count) for index in range(count)]


def build_segment_plan(duration_seconds: int | float, sample_limit: int) -> list[SegmentPlan]:
    """Evenly allocate a total target across the real six-minute segments."""
    if sample_limit < 1:
        raise ValueError("弹幕抓取上限必须至少为 1")
    segment_count = segment_count_for_duration(duration_seconds)
    if sample_limit > segment_count * MAX_SAMPLES_PER_SEGMENT:
        raise ValueError("弹幕抓取上限超过当前视频的分段保护上限")
    candidate_indexes = (
        list(range(segment_count))
        if sample_limit >= segment_count
        else _evenly_spaced_indices(segment_count, sample_limit)
    )
    requested_indexes = candidate_indexes
    if sample_limit < segment_count:
        return [SegmentPlan(index=index, target_count=1) for index in requested_indexes]

    targets = [sample_limit // len(requested_indexes)] * len(requested_indexes)
    for index in _evenly_spaced_indices(len(requested_indexes), sample_limit % len(requested_indexes)):
        targets[index] += 1
    return [SegmentPlan(index=index, target_count=target) for index, target in zip(requested_indexes, targets)]


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
    raise ValueError("oversized protobuf varint")


def _protobuf_fields(data: bytes):
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        field_number, wire_type = key >> 3, key & 0x07
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            value, offset = data[offset:offset + 8], offset + 8
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            value, offset = data[offset:offset + length], offset + length
            if len(value) != length:
                raise ValueError("truncated protobuf field")
        elif wire_type == 5:
            value, offset = data[offset:offset + 4], offset + 4
            if len(value) != 4:
                raise ValueError("truncated protobuf field")
        else:
            raise ValueError("unsupported protobuf wire type")
        yield field_number, wire_type, value


def parse_segment_payload(payload: bytes) -> tuple[list[dict], int]:
    """Return ordinary-pool text danmaku and the count filtered by pool/content.

    The endpoint returns a protobuf ``DmSegMobileReply``.  We decode only the
    fields this feature is permitted to retain: progress, content and pool.
    """
    retained: list[dict] = []
    ignored = 0
    for field_number, wire_type, element in _protobuf_fields(payload):
        if field_number != 1 or wire_type != 2:
            continue
        progress_ms = 0
        mode = 0
        content = ""
        pool = 0
        try:
            for elem_field, elem_wire, value in _protobuf_fields(element):
                if elem_field == 2 and elem_wire == 0:
                    progress_ms = int(value)
                elif elem_field == 3 and elem_wire == 0:
                    mode = int(value)
                elif elem_field == 7 and elem_wire == 2:
                    content = bytes(value).decode("utf-8", errors="replace")
                elif elem_field == 11 and elem_wire == 0:
                    pool = int(value)
        except ValueError:
            ignored += 1
            continue
        if pool != 0 or mode not in NORMAL_DANMAKU_MODES or not content.strip():
            ignored += 1
            continue
        retained.append({"content": content, "progress_ms": progress_ms})
    return retained, ignored


def select_uniform_samples(items: list[dict], target_count: int) -> list[dict]:
    """Take deterministic, evenly positioned samples from one requested segment."""
    if target_count <= 0 or not items:
        return []
    ordered = sorted(items, key=lambda item: (item["progress_ms"], item["content"]))
    count = min(target_count, len(ordered))
    positions = _evenly_spaced_indices(len(ordered), count)
    return [ordered[index] for index in positions]


async def _get_segment_with_retry(
    client: httpx.AsyncClient,
    cid: int,
    segment_index: int,
    *,
    request_delay: float,
    sleep: Callable[[float], Awaitable[None]],
) -> bytes | None:
    for attempt in range(SEGMENT_RETRY_ATTEMPTS):
        try:
            response = await client.get(
                "https://api.bilibili.com/x/v2/dm/web/seg.so",
                params={"type": 1, "oid": cid, "segment_index": segment_index + 1},
                headers=_headers(),
            )
            if response.status_code == 200:
                return response.content
            log_event(logger, "WARNING", "danmaku.segment_request_failed", "弹幕分段接口返回异常状态", segment_index=segment_index, status_code=response.status_code)
        except Exception as exc:
            log_event(logger, "WARNING", "danmaku.segment_request_failed", "弹幕分段请求失败", segment_index=segment_index, exception=exc)
        if attempt + 1 < SEGMENT_RETRY_ATTEMPTS:
            await sleep(request_delay)
    return None


async def fetch_sampled_danmaku(
    client: httpx.AsyncClient,
    cid: int,
    duration_seconds: int | float,
    sample_limit: int,
    *,
    request_delay: float = REQUEST_DELAY,
    progress_callback: Callable[[DanmakuFetchResult], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> DanmakuFetchResult:
    """Request planned segments sequentially and report only completed real work."""
    plan = build_segment_plan(duration_seconds, sample_limit)
    result = DanmakuFetchResult()
    for position, segment in enumerate(plan):
        payload = await _get_segment_with_retry(
            client, cid, segment.index, request_delay=request_delay, sleep=sleep,
        )
        result.requested_segments += 1
        result.requested_segment_indexes.append(segment.index)
        if payload is None:
            result.failed_segments.append(segment.index)
        else:
            try:
                ordinary, ignored = parse_segment_payload(payload)
            except ValueError:
                result.failed_segments.append(segment.index)
                ordinary, ignored = [], 0
                log_event(logger, "WARNING", "danmaku.segment_parse_failed", "弹幕分段解析失败", segment_index=segment.index)
            else:
                result.successful_segments += 1
                result.ignored_count += ignored
                for item in select_uniform_samples(ordinary, segment.target_count):
                    result.kept.append({**item, "segment_index": segment.index})
        if progress_callback:
            progress_callback(result)
        if position + 1 < len(plan):
            await sleep(request_delay)
    return result
