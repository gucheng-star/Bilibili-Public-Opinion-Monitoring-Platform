"""Independent API contract for conservatively sampled danmaku tasks."""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import desc

from models.database import Analysis, DanmakuAnalysis, DanmakuSample, SessionLocal
from services.bilibili import get_video_info
from services.danmaku import (
    DanmakuFetchResult,
    fetch_sampled_danmaku,
    MAX_SAMPLES_PER_SEGMENT,
    segment_count_for_duration,
)
from services.danmaku_timeline import analyze_danmaku_items, annotate_samples, build_timeline
from services.logging_config import get_logger, get_request_id, log_event, reset_request_id, set_request_id
from services.runtime_state import activity


router = APIRouter(prefix="/api/danmaku")
logger = get_logger("danmaku_api")
DEFAULT_SAMPLES_PER_SEGMENT = 100
DEFAULT_REQUEST_DELAY = 3.0


def _safe_error_message() -> str:
    return "弹幕获取失败，可重试"


def _task_payload(task: DanmakuAnalysis, timeline: dict | None = None) -> dict:
    payload = {
        "danmaku_analysis_id": task.id,
        "analysis_id": task.analysis_id,
        "bv": task.bv,
        "part_index": task.part_index,
        "attempt_index": task.attempt_index,
        "part_title": task.part_title,
        "video_duration_seconds": task.video_duration_seconds,
        "status": task.status,
        "sample_limit": task.sample_limit,
        "request_delay": task.request_delay,
        "segment_count": task.segment_count,
        "requested_segments": task.requested_segments,
        "requested_segment_indexes": json.loads(task.requested_segment_indexes or "[]"),
        "successful_segments": task.successful_segments,
        "kept_count": task.kept_count,
        "ignored_count": task.ignored_count,
        "failed_segment_indexes": json.loads(task.failed_segment_indexes or "[]"),
        "error_msg": task.error_msg,
    }
    if timeline is not None:
        payload["timeline"] = timeline
    return payload


def _timeline_payload(db, task: DanmakuAnalysis) -> dict:
    """Read sampled data only; retrieval state remains visible to the client."""
    samples = list(task.samples)
    if annotate_samples(samples):
        db.commit()
    timeline = build_timeline(
        duration_seconds=task.video_duration_seconds,
        requested_segment_indexes=json.loads(task.requested_segment_indexes or "[]"),
        failed_segment_indexes=json.loads(task.failed_segment_indexes or "[]"),
        samples=samples,
    )
    failed_segments = json.loads(task.failed_segment_indexes or "[]")
    if task.status == "error" and not samples:
        state = "failed"
    elif task.status in {"pending", "fetching"} and not samples:
        state = "not_sampled"
    elif failed_segments:
        state = "partial"
    elif task.status == "done" and not samples:
        state = "sampled_empty"
    elif task.status == "done":
        state = "ready"
    else:
        state = "partial"
    timeline["state"] = state
    return timeline


def _select_page(info: dict, part_index: int) -> dict:
    pages = info.get("pages") or []
    for page in pages:
        if page.get("page") == part_index:
            return page
    raise HTTPException(400, "所选分 P 不存在或无法获取 CID")


async def _run_danmaku_task(
    danmaku_analysis_id: int,
    *,
    request_id: str | None = None,
) -> bool:
    token = set_request_id(request_id)
    try:
        with activity("danmaku"):
            return await _run_danmaku_task_inner(danmaku_analysis_id)
    finally:
        reset_request_id(token)


async def _run_danmaku_task_inner(danmaku_analysis_id: int) -> bool:
    db = SessionLocal()
    try:
        task = db.get(DanmakuAnalysis, danmaku_analysis_id)
        if not task:
            return False
        task.status = "fetching"
        task.error_msg = None
        db.commit()
        log_event(logger, "INFO", "danmaku.task_started", "弹幕抽样任务已开始", analysis_id=task.analysis_id, task_type="danmaku_sampling")
        persisted_sample_count = 0

        def report_progress(result: DanmakuFetchResult) -> None:
            nonlocal persisted_sample_count
            new_samples = result.kept[persisted_sample_count:]
            analyze_danmaku_items(new_samples)
            for sample in new_samples:
                db.add(DanmakuSample(
                    danmaku_analysis_id=task.id,
                    content=sample["content"],
                    progress_ms=sample["progress_ms"],
                    segment_index=sample["segment_index"],
                    sentiment_label=sample["sentiment_label"],
                    sentiment_score=sample["sentiment_score"],
                ))
            task.requested_segments = result.requested_segments
            task.requested_segment_indexes = json.dumps(result.requested_segment_indexes)
            task.successful_segments = result.successful_segments
            task.kept_count = len(result.kept)
            task.ignored_count = result.ignored_count
            task.failed_segment_indexes = json.dumps(result.failed_segments)
            db.commit()
            persisted_sample_count = len(result.kept)

        async with httpx.AsyncClient(timeout=30) as client:
            result = await fetch_sampled_danmaku(
                client,
                task.cid,
                task.video_duration_seconds,
                task.sample_limit,
                request_delay=task.request_delay,
                progress_callback=report_progress,
            )
        report_progress(result)
        if result.successful_segments == 0:
            task.status = "error"
            task.error_msg = _safe_error_message()
            db.commit()
            log_event(logger, "WARNING", "danmaku.task_failed", "所有弹幕分段获取失败", analysis_id=task.analysis_id, task_type="danmaku_sampling")
            return False
        task.status = "partial" if result.failed_segments else "done"
        task.error_msg = None
        db.commit()
        log_event(logger, "INFO", "danmaku.task_completed", "弹幕抽样任务已完成", analysis_id=task.analysis_id, task_type="danmaku_sampling", count=task.kept_count, partial=bool(result.failed_segments))
        return True
    except Exception as exc:
        db.rollback()
        task = db.get(DanmakuAnalysis, danmaku_analysis_id)
        if task:
            task.status = "error"
            task.error_msg = _safe_error_message()
            db.commit()
        log_event(logger, "ERROR", "danmaku.task_failed", "弹幕抽样任务失败", analysis_id=None, task_type="danmaku_sampling", exception=exc)
        return False
    finally:
        db.close()


@router.post("")
async def start_danmaku_sampling(req: dict, background_tasks: BackgroundTasks):
    """Start (or retry) a task only after an explicit user action."""
    raw_sample_limit = req.get("sample_limit")
    try:
        part_index = int(req.get("part_index", 1))
        request_delay = float(req.get("request_delay", DEFAULT_REQUEST_DELAY))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "弹幕抓取参数无效") from exc
    if part_index < 1:
        raise HTTPException(400, "分 P 序号无效")
    if not 1.0 <= request_delay <= 60.0:
        raise HTTPException(400, "请求间隔必须在 1 到 60 秒之间")

    analysis_id = req.get("analysis_id")
    db = SessionLocal()
    try:
        source = None
        bv = str(req.get("bv") or "").strip()
        if analysis_id is not None:
            source = db.get(Analysis, analysis_id)
            if not source:
                raise HTTPException(404, "原视频分析不存在")
            bv = source.bv
        if not bv.startswith("BV"):
            raise HTTPException(400, "请输入有效的 BV 号")

        async with httpx.AsyncClient(timeout=15) as client:
            info = await get_video_info(client, bv)
        if not info:
            raise HTTPException(404, "视频不存在或暂时无法访问")
        page = _select_page(info, part_index)
        cid = int(page.get("cid") or 0)
        duration_seconds = int(page.get("duration") or 0)
        if cid <= 0 or duration_seconds <= 0:
            raise HTTPException(400, "所选分 P 缺少可用的弹幕时长或 CID")
        segment_count = segment_count_for_duration(duration_seconds)
        try:
            sample_limit = int(raw_sample_limit) if raw_sample_limit is not None else segment_count * DEFAULT_SAMPLES_PER_SEGMENT
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "弹幕抓取参数无效") from exc
        max_sample_limit = segment_count * MAX_SAMPLES_PER_SEGMENT
        if not 1 <= sample_limit <= max_sample_limit:
            raise HTTPException(400, f"本次抽样上限必须在 1 到 {max_sample_limit} 条之间")

        previous_task = (
            db.query(DanmakuAnalysis).filter_by(analysis_id=source.id, part_index=part_index)
            .order_by(desc(DanmakuAnalysis.attempt_index), desc(DanmakuAnalysis.id)).first()
            if source else db.query(DanmakuAnalysis).filter_by(bv=bv, cid=cid)
            .order_by(desc(DanmakuAnalysis.attempt_index), desc(DanmakuAnalysis.id)).first()
        )
        if previous_task and previous_task.status in {"pending", "fetching"}:
            raise HTTPException(409, "弹幕抽样任务正在进行中")
        task = DanmakuAnalysis(
            analysis_id=source.id if source else None,
            bv=bv,
            avid=info["avid"],
            cid=cid,
            part_index=part_index,
            part_title=page.get("part", ""),
            attempt_index=(previous_task.attempt_index + 1) if previous_task else 1,
            video_duration_seconds=duration_seconds,
            status="pending",
            sample_limit=sample_limit,
            request_delay=request_delay,
            segment_count=segment_count,
        )
        db.add(task)
        db.flush()

        task.avid = info["avid"]
        task.cid = cid
        task.part_index = part_index
        task.part_title = page.get("part", "")
        task.video_duration_seconds = duration_seconds
        task.status = "pending"
        task.sample_limit = sample_limit
        task.request_delay = request_delay
        task.segment_count = segment_count
        task.requested_segments = 0
        task.requested_segment_indexes = "[]"
        task.successful_segments = 0
        task.kept_count = 0
        task.ignored_count = 0
        task.failed_segment_indexes = "[]"
        task.error_msg = None
        db.commit()
        db.refresh(task)
        background_tasks.add_task(_run_danmaku_task, task.id, request_id=get_request_id())
        log_event(logger, "INFO", "danmaku.task_created", "弹幕抽样任务已创建", analysis_id=task.analysis_id, task_type="danmaku_sampling")
        return _task_payload(task, _timeline_payload(db, task))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        log_event(logger, "ERROR", "danmaku.task_create_failed", "创建弹幕抽样任务失败", task_type="danmaku_sampling", exception=exc)
        raise HTTPException(500, "创建弹幕抽样任务失败") from exc
    finally:
        db.close()


@router.get("/by-analysis/{analysis_id}")
def get_danmaku_sampling_for_analysis(analysis_id: int, part_index: int | None = None):
    db = SessionLocal()
    try:
        query = db.query(DanmakuAnalysis).filter_by(analysis_id=analysis_id)
        if part_index is not None:
            query = query.filter_by(part_index=part_index)
        task = query.order_by(desc(DanmakuAnalysis.updated_at), desc(DanmakuAnalysis.id)).first()
        if not task:
            raise HTTPException(404, "该视频尚未开始弹幕抽样")
        return _task_payload(task, _timeline_payload(db, task))
    finally:
        db.close()


@router.get("/{danmaku_analysis_id}")
def get_danmaku_sampling(danmaku_analysis_id: int):
    """Read persisted progress without starting network work."""
    db = SessionLocal()
    try:
        task = db.get(DanmakuAnalysis, danmaku_analysis_id)
        if not task:
            raise HTTPException(404, "弹幕抽样任务不存在")
        return _task_payload(task, _timeline_payload(db, task))
    finally:
        db.close()
