"""Persisted AI summaries for an analysis and its applied filters."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from models.database import AISummary, Analysis, Comment, SessionLocal
from services.ai_summary import (
    apply_filters,
    filter_signature,
    generate_summary,
    input_signature,
    is_v2_llm_comment,
    normalize_filters,
    normalize_report_options,
)
from services.sentiment_contract import LLM_SENTIMENT_SCHEMA_V2
from services.llm_client import LLMRequestError, summary_thinking_status
from services.settings_store import get_task_config
from services.runtime_state import activity
from services.comment_quality import (
    annotate_exact_duplicates,
    apply_duplicate_mode,
    build_duplicate_statistics,
)
from services.logging_config import get_logger, log_event


router = APIRouter(prefix="/api")
logger = get_logger("summary")


def _comment_dict(comment: Comment) -> dict:
    return {
        "id": comment.id,
        "rpid": comment.rpid,
        "content": comment.content or "",
        "likes": comment.likes or 0,
        "gender": comment.gender or "",
        "ip_location": comment.ip_location or "",
        "post_time": comment.post_time,
        "sentiment_label": comment.sentiment_label or "",
        "sentiment_llm_label": comment.sentiment_llm_label or "",
        "sentiment_llm_style": comment.sentiment_llm_style or "",
        "sentiment_llm_schema_version": comment.sentiment_llm_schema_version,
    }


def _v2_summary_comments(analysis: Analysis, comments: list[dict]) -> tuple[list[dict], dict]:
    covered = [comment for comment in comments if is_v2_llm_comment(comment)]
    total = len(comments)
    complete = (
        analysis.sentiment_llm_schema_version == LLM_SENTIMENT_SCHEMA_V2
        and len(covered) == total
    )
    return covered, {
        "scope": "all_comments" if complete else "v2_covered_subset",
        "total_comments": total,
        "v2_completed_comments": len(covered),
        "v2_pending_comments": total - len(covered),
        "v2_complete": complete,
    }


def _serialize(
    summary: AISummary,
    current_input_hash: str | None = None,
    normalized_filters: dict[str, str] | None = None,
) -> dict:
    return {
        "id": summary.id,
        "analysis_id": summary.analysis_id,
        "filters": normalized_filters or json.loads(summary.filter_json),
        "filter_hash": summary.filter_hash,
        "interpretation_view": summary.interpretation_view,
        "report_mode": summary.report_mode,
        "thinking_status": summary.thinking_status,
        "summary_text": summary.summary_text,
        "provider": summary.provider,
        "model": summary.model,
        "matched_count": summary.matched_count,
        "sampled_count": summary.sampled_count,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
        "stale": current_input_hash is not None and summary.input_hash != current_input_hash,
    }


@router.get("/summaries/{analysis_id}")
def list_summaries(analysis_id: int):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            raise HTTPException(404, "分析记录不存在")
        comments = annotate_exact_duplicates([
            _comment_dict(comment) for comment in db.query(Comment).filter_by(analysis_id=analysis_id).all()
        ])
        response = []
        for summary in db.query(AISummary).filter_by(analysis_id=analysis_id).all():
            try:
                filters = normalize_filters(json.loads(summary.filter_json), analysis.mode)
                summary_comments = comments
                if analysis.mode == "llm":
                    summary_comments, _coverage = _v2_summary_comments(analysis, comments)
                matched = apply_filters(summary_comments, filters, analysis.mode)
                current_hash = input_signature(matched, analysis.mode)
            except (ValueError, json.JSONDecodeError):
                current_hash = ""
            response.append(_serialize(summary, current_hash, filters if current_hash else None))
        return response
    finally:
        db.close()


@router.post("/summaries/{analysis_id}")
async def create_summary(analysis_id: int, req: dict):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            raise HTTPException(404, "分析记录不存在")
        if analysis.status != "done":
            raise HTTPException(400, "分析尚未完成")
        try:
            filters = normalize_filters(req.get("filters"), analysis.mode)
            interpretation_view, report_mode = normalize_report_options(req)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        filter_json, filter_hash = filter_signature(filters)
        comments = annotate_exact_duplicates([
            _comment_dict(comment) for comment in db.query(Comment).filter_by(analysis_id=analysis_id).all()
        ])
        summary_comments = comments
        coverage = None
        if analysis.mode == "llm":
            summary_comments, coverage = _v2_summary_comments(analysis, comments)
            if not coverage["v2_complete"] and not bool(req.get("useV2CoveredSubset", False)):
                raise HTTPException(409, "V2 大模型情绪尚未覆盖全部评论，请先补齐或明确使用已覆盖子集")
        matched = apply_filters(summary_comments, filters, analysis.mode)
        if not matched:
            raise HTTPException(400, "当前筛选条件下没有可总结的评论")
        current_input_hash = input_signature(matched, analysis.mode)
        existing = db.query(AISummary).filter_by(
            analysis_id=analysis_id,
            filter_hash=filter_hash,
            interpretation_view=interpretation_view,
            report_mode=report_mode,
        ).first()
        if not existing and filters["duplicateMode"] == "include" and interpretation_view == "public_opinion" and report_mode == "quick":
            legacy_filters = {
                key: value for key, value in filters.items()
                if key not in {"duplicateMode", "sourceAnalysisId"}
            }
            _, legacy_hash = filter_signature(legacy_filters)
            existing = db.query(AISummary).filter_by(
                analysis_id=analysis_id,
                filter_hash=legacy_hash,
                interpretation_view=interpretation_view,
                report_mode=report_mode,
            ).first()
        regenerate = bool(req.get("regenerate", False))
        if existing and existing.input_hash == current_input_hash and not regenerate:
            return _serialize(existing, current_input_hash, filters)

        try:
            config = get_task_config("summary")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not config.get("api_key"):
            raise HTTPException(400, "请先配置智能总结 API Key")
        log_event(logger, "INFO", "summary.task_started", "单视频简报生成已开始", analysis_id=analysis_id, task_type="single_video_ai_summary", count=len(matched))
        with activity("ai_summary"):
            duplicate_statistics = build_duplicate_statistics(comments)
            after_duplicate_count = len(apply_duplicate_mode(comments, filters["duplicateMode"]))
            quality_context = {
                "original_comment_count": len(comments),
                "duplicate_group_count": duplicate_statistics["group_count"],
                "duplicate_involved_comments": duplicate_statistics["involved_comments"],
                "duplicate_mode": filters["duplicateMode"],
                "after_duplicate_filter_count": after_duplicate_count,
                "final_matched_count": len(matched),
            }
            if coverage:
                quality_context["v2_coverage"] = coverage
            generation_options = {}
            if interpretation_view != "public_opinion" or report_mode != "quick":
                generation_options = {
                    "interpretation_view": interpretation_view,
                    "report_mode": report_mode,
                }
            summary_text, used_model, sampled_count = await generate_summary(
                matched, analysis.mode, config, quality_context, **generation_options,
            )
        thinking_status = summary_thinking_status(config, report_mode)
        if existing:
            existing.filter_json = filter_json
            existing.filter_hash = filter_hash
            existing.interpretation_view = interpretation_view
            existing.report_mode = report_mode
            existing.thinking_status = thinking_status
            existing.input_hash = current_input_hash
            existing.summary_text = summary_text
            existing.provider = config["provider"]
            existing.model = used_model
            existing.matched_count = len(matched)
            existing.sampled_count = sampled_count
            record = existing
        else:
            record = AISummary(
                analysis_id=analysis_id,
                filter_json=filter_json,
                filter_hash=filter_hash,
                interpretation_view=interpretation_view,
                report_mode=report_mode,
                thinking_status=thinking_status,
                input_hash=current_input_hash,
                summary_text=summary_text,
                provider=config["provider"],
                model=used_model,
                matched_count=len(matched),
                sampled_count=sampled_count,
            )
            db.add(record)
        db.commit()
        db.refresh(record)
        log_event(logger, "INFO", "summary.database_commit_completed", "单视频简报已写入数据库", analysis_id=analysis_id, task_type="single_video_ai_summary", count=sampled_count)
        log_event(logger, "INFO", "summary.task_completed", "单视频简报生成已完成", analysis_id=analysis_id, task_type="single_video_ai_summary", count=sampled_count)
        return _serialize(record, current_input_hash, filters)
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, LLMRequestError) as exc:
        log_event(logger, "ERROR", "summary.task_failed", "单视频简报生成失败", analysis_id=analysis_id, task_type="single_video_ai_summary", exception=exc)
        db.rollback()
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        log_event(logger, "ERROR", "summary.task_failed", "单视频简报生成失败", analysis_id=analysis_id, task_type="single_video_ai_summary", exception=exc)
        db.rollback()
        raise HTTPException(500, "生成总结失败") from exc
    finally:
        db.close()
