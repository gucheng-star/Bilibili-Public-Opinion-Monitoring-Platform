"""API routes for multi-video opinion events (AnalysisGroup)."""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy.orm import selectinload

from models.database import Analysis, AnalysisGroup, AnalysisGroupItem, AnalysisGroupSummary, Comment, SessionLocal
from services.ai_summary import apply_filters, filter_signature, normalize_filters
from services.analysis_groups import (
    GroupValidationError,
    build_group_result,
    create_group,
    generate_group_summary,
    get_group,
    group_comments,
    group_input_signature,
    group_metadata,
    group_quality_context,
    group_rows,
    llm_readiness,
    member_signature,
    select_group_representative_comments,
    update_group,
)
from services.llm_client import LLMRequestError
from services.ai_summary import LLM_LABELS
from services.runtime_state import activity
from services.settings_store import get_task_config
from services.wordcloud_gen import get_top_keywords
from api import routes as analysis_routes


router = APIRouter(prefix="/api")


def _require_group(db, group_id: int):
    group = get_group(db, group_id)
    if not group:
        raise HTTPException(404, "舆情事件不存在")
    return group


def _filters(value, mode: str) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "筛选条件必须是 JSON 对象") from exc
    try:
        return normalize_filters(value, mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _ensure_llm_ready(db, group_id: int) -> None:
    rows = group_rows(db, group_id)
    readiness = llm_readiness(rows, group_comments(db, group_id))
    if not readiness["ready"]:
        raise HTTPException(409, {"message": "部分来源视频尚未完成大模型情绪分析", **readiness})


def group_reanalysis_status(db, group: AnalysisGroup) -> dict:
    """Return durable, source-aggregated LLM backfill progress for one event."""
    rows = group_rows(db, group.id)
    comments = group_comments(db, group.id)
    readiness = llm_readiness(rows, comments)
    comments_by_source: dict[int, list[dict]] = {}
    for comment in comments:
        comments_by_source.setdefault(int(comment["source_analysis_id"]), []).append(comment)

    total_comments = 0
    processed_comments = 0
    errors: list[dict] = []
    for _item, analysis in rows:
        source_comments = comments_by_source.get(analysis.id, [])
        total = len(source_comments)
        total_comments += total
        valid = sum(comment.get("sentiment_llm_label", "") in LLM_LABELS for comment in source_comments)
        # Successful validated sub-batches commit their labels and callback
        # progress together; use that durable count while a source is running.
        processed_comments += min(total, analysis.processed_comments or 0) if analysis.status == "analyzing" else valid
        if analysis.error_msg and valid < total:
            errors.append({"analysis_id": analysis.id, "video_title": analysis.video_title or analysis.bv, "message": analysis.error_msg})

    if readiness["ready"]:
        status = "done"
        processed_comments = total_comments
    elif any(analysis.status == "analyzing" for _item, analysis in rows):
        status = "analyzing"
    elif errors:
        status = "error"
    else:
        status = "pending"
    return {
        "group_id": group.id,
        "status": status,
        "ready": readiness["ready"],
        "total_comments": total_comments,
        "processed_comments": processed_comments,
        "pending_comments": max(0, total_comments - processed_comments),
        "missing_members": readiness["missing_members"],
        "errors": errors,
    }


async def _run_group_reanalyze(work_items: list[dict], llm_config: dict[str, str]) -> None:
    """Backfill event members sequentially, leaving batch concurrency to the LLM service."""
    with activity("llm_sentiment"):
        for work in work_items:
            await analysis_routes._run_reanalyze_inner(
                work["analysis_id"], work["target_comments"], llm_config,
                context_comments=work["context_comments"], failure_mode=work["failure_mode"],
            )


def _summary_payload(summary: AnalysisGroupSummary, stale: bool, filters: dict[str, str] | None = None) -> dict:
    return {
        "id": summary.id,
        "group_id": summary.group_id,
        "mode": summary.analysis_mode,
        "filters": filters or json.loads(summary.filter_json),
        "filter_hash": summary.filter_hash,
        "summary_text": summary.summary_text,
        "provider": summary.provider,
        "model": summary.model,
        "matched_count": summary.matched_count,
        "sampled_count": summary.sampled_count,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
        "stale": stale,
    }


@router.post("/analysis-groups")
def post_group(req: dict):
    db = SessionLocal()
    try:
        group = create_group(db, req.get("name"), req.get("description"), req.get("analysis_ids"))
        db.commit()
        db.refresh(group)
        return group_metadata(db, group)
    except GroupValidationError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/analysis-groups")
def list_groups(limit: int = 50):
    db = SessionLocal()
    try:
        safe_limit = min(max(limit, 1), 100)
        groups = (
            db.query(AnalysisGroup)
            .options(selectinload(AnalysisGroup.items).joinedload(AnalysisGroupItem.analysis))
            .order_by(AnalysisGroup.updated_at.desc()).limit(safe_limit).all()
        )
        return [
            group_metadata(db, group, [(item, item.analysis) for item in group.items])
            for group in groups
        ]
    finally:
        db.close()


@router.get("/analysis-groups/{group_id}")
def get_group_detail(group_id: int):
    db = SessionLocal()
    try:
        return group_metadata(db, _require_group(db, group_id))
    finally:
        db.close()


@router.patch("/analysis-groups/{group_id}")
def patch_group(group_id: int, req: dict):
    db = SessionLocal()
    try:
        group = update_group(db, _require_group(db, group_id), req)
        db.commit()
        db.refresh(group)
        return group_metadata(db, group)
    except HTTPException:
        db.rollback()
        raise
    except GroupValidationError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.delete("/analysis-groups/{group_id}")
def delete_group(group_id: int):
    db = SessionLocal()
    try:
        group = _require_group(db, group_id)
        db.delete(group)
        db.commit()
        return {"deleted": True, "ok": True, "group_id": group_id}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/analysis-groups/{group_id}/results")
def get_group_results(group_id: int, mode: str = "nlp", filters: str | None = None):
    db = SessionLocal()
    try:
        group = _require_group(db, group_id)
        normalized = _filters(filters, mode)
        if mode == "llm":
            _ensure_llm_ready(db, group_id)
        try:
            return build_group_result(db, group, mode, normalized)
        except GroupValidationError as exc:
            status = 409 if "不足" in str(exc) or "部分来源" in str(exc) else 400
            raise HTTPException(status, str(exc)) from exc
    finally:
        db.close()


@router.get("/analysis-groups/{group_id}/reanalyze/status")
def get_group_reanalyze_status(group_id: int):
    db = SessionLocal()
    try:
        return group_reanalysis_status(db, _require_group(db, group_id))
    finally:
        db.close()


@router.post("/analysis-groups/{group_id}/reanalyze")
async def post_group_reanalyze(group_id: int, background_tasks: BackgroundTasks):
    """Explicitly backfill only missing LLM labels for an event's source videos."""
    db = SessionLocal()
    try:
        group = _require_group(db, group_id)
        rows = group_rows(db, group_id)
        if len(rows) < 2:
            raise HTTPException(409, "该舆情事件当前不足 2 个有效来源视频")
        if any(analysis.status == "analyzing" for _item, analysis in rows):
            raise HTTPException(409, "事件的大模型情感分析正在进行中")
        unavailable = [analysis.video_title or analysis.bv for _item, analysis in rows if analysis.status != "done"]
        if unavailable:
            raise HTTPException(409, "以下来源视频尚未完成：" + "、".join(unavailable))

        work_items: list[dict] = []
        legacy_ready = []
        for _item, analysis in rows:
            context_comments = analysis_routes._stored_comment_data(
                db.query(Comment).filter_by(analysis_id=analysis.id).all(),
            )
            target_comments = [
                comment for comment in context_comments
                if comment.get("sentiment_llm_label", "") not in LLM_LABELS
            ]
            if not target_comments:
                if analysis.mode != "llm":
                    analysis.mode = "llm"
                    analysis.processed_comments = len(context_comments)
                    legacy_ready.append(analysis.id)
                continue
            claimed = (
                db.query(Analysis)
                .filter(Analysis.id == analysis.id, Analysis.status == "done")
                .update({
                    Analysis.status: "analyzing",
                    Analysis.error_msg: None,
                    Analysis.total_comments: len(context_comments),
                    Analysis.processed_comments: len(context_comments) - len(target_comments),
                }, synchronize_session=False)
            )
            if claimed != 1:
                raise HTTPException(409, f"来源视频“{analysis.video_title or analysis.bv}”已在其他任务中处理中")
            work_items.append({
                "analysis_id": analysis.id,
                "target_comments": target_comments,
                "context_comments": context_comments,
                "failure_mode": analysis.mode or "nlp",
            })

        if work_items:
            config = get_task_config("sentiment")
            if not config.get("api_key"):
                raise HTTPException(400, "请先配置情绪分析 API Key")
        db.commit()
        status = group_reanalysis_status(db, group)
        status["started_analysis_ids"] = [work["analysis_id"] for work in work_items]
        status["already_ready_analysis_ids"] = legacy_ready
        status["target_comments"] = sum(len(work["target_comments"]) for work in work_items)
        if work_items:
            background_tasks.add_task(_run_group_reanalyze, work_items, config)
        return status
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/analysis-groups/{group_id}/keywords")
def post_group_keywords(group_id: int, req: dict):
    db = SessionLocal()
    try:
        _require_group(db, group_id)
        mode = str(req.get("mode", "nlp") or "nlp")
        normalized = _filters(req.get("filters"), mode)
        if mode == "llm":
            _ensure_llm_ready(db, group_id)
        comments = group_comments(db, group_id)
        matched = apply_filters(comments, normalized, mode)
        return {"matched_count": len(matched), "keywords": get_top_keywords(matched, top_n=500)}
    finally:
        db.close()


@router.get("/analysis-groups/{group_id}/summaries")
def list_group_summaries(group_id: int):
    db = SessionLocal()
    try:
        _require_group(db, group_id)
        rows = group_rows(db, group_id)
        comments = group_comments(db, group_id)
        current_member_signature = member_signature(rows)
        response = []
        for summary in db.query(AnalysisGroupSummary).filter_by(group_id=group_id).all():
            try:
                filters = normalize_filters(json.loads(summary.filter_json), summary.analysis_mode)
                matched = apply_filters(comments, filters, summary.analysis_mode)
                current_input_hash = group_input_signature(rows, matched, summary.analysis_mode)
                stale = (
                    summary.member_signature != current_member_signature
                    or summary.input_hash != current_input_hash
                )
            except (ValueError, json.JSONDecodeError):
                filters = None
                stale = True
            response.append(_summary_payload(summary, stale, filters))
        return response
    finally:
        db.close()


@router.post("/analysis-groups/{group_id}/summaries")
async def post_group_summary(group_id: int, req: dict):
    db = SessionLocal()
    try:
        _require_group(db, group_id)
        mode = str(req.get("mode", "nlp") or "nlp")
        if mode not in {"nlp", "llm"}:
            raise HTTPException(422, "无效的分析模式")
        normalized = _filters(req.get("filters"), mode)
        rows = group_rows(db, group_id)
        if len(rows) < 2:
            raise HTTPException(409, "该舆情事件当前不足 2 个有效来源视频")
        if mode == "llm":
            _ensure_llm_ready(db, group_id)
        all_comments = group_comments(db, group_id)
        matched = apply_filters(all_comments, normalized, mode)
        if not matched:
            raise HTTPException(400, "当前筛选条件下没有可总结的评论")
        filter_json, filter_hash = filter_signature(normalized)
        current_member_signature = member_signature(rows)
        current_input_hash = group_input_signature(rows, matched, mode)
        existing = db.query(AnalysisGroupSummary).filter_by(
            group_id=group_id, analysis_mode=mode, filter_hash=filter_hash,
        ).first()
        if (
            existing and existing.member_signature == current_member_signature
            and existing.input_hash == current_input_hash and not bool(req.get("regenerate", False))
        ):
            return _summary_payload(existing, False, normalized)
        try:
            config = get_task_config("summary")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not config.get("api_key"):
            raise HTTPException(400, "请先配置智能总结 API Key")
        with activity("ai_summary"):
            summary_text, used_model, sampled_count = await generate_group_summary(
                matched, rows, mode, config, group_quality_context(all_comments, normalized, matched),
            )
        if existing:
            existing.member_signature = current_member_signature
            existing.filter_json = filter_json
            existing.input_hash = current_input_hash
            existing.summary_text = summary_text
            existing.provider = config["provider"]
            existing.model = used_model
            existing.matched_count = len(matched)
            existing.sampled_count = sampled_count
            record = existing
        else:
            record = AnalysisGroupSummary(
                group_id=group_id, analysis_mode=mode, member_signature=current_member_signature,
                filter_json=filter_json, filter_hash=filter_hash, input_hash=current_input_hash,
                summary_text=summary_text, provider=config["provider"], model=used_model,
                matched_count=len(matched), sampled_count=sampled_count,
            )
            db.add(record)
        db.commit()
        db.refresh(record)
        return _summary_payload(record, False, normalized)
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, LLMRequestError) as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, "生成事件简报失败") from exc
    finally:
        db.close()
