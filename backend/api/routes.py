"""API 路由"""

import asyncio
import threading
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import desc

from models.database import SessionLocal, Analysis, Comment, SentimentResult, init_db
from services.bilibili import get_video_info, fetch_comments
from services.sentiment import batch_analyze, summarize_sentiment
from services.wordcloud_gen import generate_wordcloud, get_top_keywords
from services.region import analyze_region
from services.heat import analyze_heat

router = APIRouter(prefix="/api")

# 存储异步分析任务的状态
_task_status: dict[int, dict] = {}


def _run_analysis_in_thread(analysis_id: int, bv: str, avid: int):
    """在后台线程中运行完整的分析流程"""
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            return

        analysis.status = "fetching"
        db.commit()

        async def _fetch():
            async with httpx.AsyncClient(timeout=30) as client:
                return await fetch_comments(client, avid)

        comments_raw = asyncio.run(_fetch())

        if not comments_raw:
            analysis.status = "error"
            analysis.error_msg = "未获取到评论数据"
            db.commit()
            return

        analysis.status = "analyzing"
        analysis.total_comments = len(comments_raw)
        db.commit()

        # 情感分析
        comments_analyzed = batch_analyze(comments_raw)

        # 保存评论
        for c in comments_analyzed:
            db.add(Comment(
                analysis_id=analysis_id,
                rpid=c["rpid"],
                username=c["username"],
                gender=c["gender"],
                ip_location=c["ip_location"],
                content=c["content"],
                likes=c["likes"],
                sentiment_label=c["sentiment_label"],
                sentiment_score=c["sentiment_score"],
                post_time=c["post_time"],
            ))

        # 保存情感汇总
        sentiment_summary = summarize_sentiment(comments_analyzed)
        db.add(SentimentResult(
            analysis_id=analysis_id,
            positive_count=sentiment_summary["positive"],
            negative_count=sentiment_summary["negative"],
            neutral_count=sentiment_summary["neutral"],
        ))

        analysis.status = "done"
        db.commit()
    except Exception as e:
        db.rollback()
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if analysis:
            analysis.status = "error"
            analysis.error_msg = str(e)
            db.commit()
    finally:
        db.close()
        _task_status.pop(analysis_id, None)


@router.post("/analyze")
def start_analysis(req: dict):
    """提交 BV 号进行分析"""
    bv = req.get("bv", "").strip()
    if not bv or not bv.startswith("BV"):
        raise HTTPException(400, "请输入有效的 BV 号")

    # 获取视频信息
    async def _get_info():
        async with httpx.AsyncClient(timeout=15) as client:
            return await get_video_info(client, bv)

    info = asyncio.run(_get_info())
    if not info:
        raise HTTPException(404, "视频不存在或无法访问")

    db = SessionLocal()
    try:
        analysis = Analysis(
            bv=bv,
            avid=info["avid"],
            video_title=info["title"],
            video_cover=info["cover"],
            video_play=info["play"],
            status="pending",
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        # 启动后台分析线程
        thread = threading.Thread(
            target=_run_analysis_in_thread,
            args=(analysis.id, bv, info["avid"]),
            daemon=True,
        )
        thread.start()

        return {
            "analysis_id": analysis.id,
            "bv": bv,
            "video_title": info["title"],
            "video_cover": info["cover"],
            "video_play": info["play"],
            "status": "pending",
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/status/{analysis_id}")
def get_status(analysis_id: int):
    """查询分析进度"""
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            raise HTTPException(404, "分析记录不存在")
        return {
            "analysis_id": analysis.id,
            "status": analysis.status,
            "total_comments": analysis.total_comments,
            "error_msg": analysis.error_msg,
        }
    finally:
        db.close()


@router.get("/results/{analysis_id}")
def get_results(analysis_id: int):
    """获取完整分析结果"""
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            raise HTTPException(404, "分析记录不存在")
        if analysis.status != "done":
            return {"status": analysis.status, "message": "分析尚未完成"}

        comments = db.query(Comment).filter_by(analysis_id=analysis_id).all()
        sentiment = db.query(SentimentResult).filter_by(analysis_id=analysis_id).first()

        comments_list = [
            {
                "id": c.id,
                "rpid": c.rpid,
                "username": c.username,
                "gender": c.gender,
                "ip_location": c.ip_location,
                "content": c.content,
                "likes": c.likes,
                "sentiment_label": c.sentiment_label,
                "sentiment_score": c.sentiment_score,
                "post_time": c.post_time.isoformat() if c.post_time else None,
            }
            for c in comments
        ]

        # 各维度分析
        region_data = analyze_region(comments_list)
        heat_data = analyze_heat(comments_list)
        keywords = get_topkeywords(comments_list)

        return {
            "analysis_id": analysis.id,
            "bv": analysis.bv,
            "video_title": analysis.video_title,
            "video_cover": analysis.video_cover,
            "video_play": analysis.video_play,
            "total_comments": analysis.total_comments,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
            "sentiment": {
                "positive": sentiment.positive_count if sentiment else 0,
                "negative": sentiment.negative_count if sentiment else 0,
                "neutral": sentiment.neutral_count if sentiment else 0,
            },
            "gender": _calc_gender(comments_list),
            "region": region_data,
            "heat": heat_data,
            "keywords": keywords,
            "comments": comments_list,
        }
    finally:
        db.close()


@router.get("/wordcloud/{analysis_id}")
def get_wordcloud(analysis_id: int):
    """获取词云图 base64"""
    db = SessionLocal()
    try:
        comments = db.query(Comment).filter_by(analysis_id=analysis_id).all()
        if not comments:
            raise HTTPException(404, "无评论数据")
        comments_list = [{"content": c.content} for c in comments]
        b64 = generate_wordcloud(comments_list)
        return {"base64": b64}
    finally:
        db.close()


@router.get("/history")
def get_history(limit: int = 20):
    """获取历史分析列表"""
    db = SessionLocal()
    try:
        analyses = (
            db.query(Analysis)
            .order_by(desc(Analysis.created_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "id": a.id,
                "bv": a.bv,
                "video_title": a.video_title,
                "video_cover": a.video_cover,
                "total_comments": a.total_comments,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ]
    finally:
        db.close()


def _calc_gender(comments: list[dict]) -> dict:
    """计算性别分布"""
    male = sum(1 for c in comments if c.get("gender") == "男")
    female = sum(1 for c in comments if c.get("gender") == "女")
    unknown = sum(1 for c in comments if c.get("gender") == "保密")
    return {"male": male, "female": female, "unknown": unknown}
