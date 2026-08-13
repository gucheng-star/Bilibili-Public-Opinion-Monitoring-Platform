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
    normalize_filters,
)
from services.llm_client import LLMRequestError
from services.settings_store import get_task_config
from services.runtime_state import activity
from services.comment_quality import (
    annotate_exact_duplicates,
    apply_duplicate_mode,
    build_duplicate_statistics,
)


router = APIRouter(prefix="/api")


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
                matched = apply_filters(comments, filters, analysis.mode)
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
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        filter_json, filter_hash = filter_signature(filters)
        comments = annotate_exact_duplicates([
            _comment_dict(comment) for comment in db.query(Comment).filter_by(analysis_id=analysis_id).all()
        ])
        matched = apply_filters(comments, filters, analysis.mode)
        if not matched:
            raise HTTPException(400, "当前筛选条件下没有可总结的评论")
        current_input_hash = input_signature(matched, analysis.mode)
        existing = db.query(AISummary).filter_by(
            analysis_id=analysis_id,
            filter_hash=filter_hash,
        ).first()
        if not existing and filters["duplicateMode"] == "include":
            legacy_filters = {key: value for key, value in filters.items() if key != "duplicateMode"}
            _, legacy_hash = filter_signature(legacy_filters)
            existing = db.query(AISummary).filter_by(
                analysis_id=analysis_id,
                filter_hash=legacy_hash,
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
            summary_text, used_model, sampled_count = await generate_summary(
                matched, analysis.mode, config, quality_context
            )
        if existing:
            existing.filter_json = filter_json
            existing.filter_hash = filter_hash
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
        return _serialize(record, current_input_hash, filters)
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, LLMRequestError) as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, "生成总结失败") from exc
    finally:
        db.close()
