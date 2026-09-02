import os
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from sqlalchemy import desc, func
from models.database import SessionLocal, Analysis, AnalysisGroupItem, Comment, SentimentResult, init_db
from services.bilibili import get_video_info, fetch_comments
from services.sentiment import batch_analyze, summarize_sentiment
from services.sentiment_llm import batch_analyze_llm, summarize_sentiment_llm
from services.wordcloud_gen import generate_wordcloud, get_top_keywords
from services.region import analyze_region
from services.heat import analyze_heat
from services.settings_store import get_task_config
from services.runtime_state import activity
from services.comment_quality import annotate_exact_duplicates, build_duplicate_statistics
from services.ai_summary import apply_filters, normalize_filters
from services.sentiment_contract import (
    LLM_SENTIMENT_SCHEMA_V2,
    V2_EMOTION_LABELS,
    V2_STYLE_LABELS,
)
from services.logging_config import (
    get_logger,
    get_request_id,
    log_event,
    reset_request_id,
    set_request_id,
)
from services.sentiment_test_fixtures import (
    FIXTURE_VIDEO_TITLE,
    build_fixture_comments,
    fixture_case_catalog,
)

router = APIRouter(prefix='/api')
logger = get_logger("analysis")
TEST_FIXTURES_ENABLED = os.getenv("BILI_ENABLE_TEST_FIXTURES", "").lower() == "1"


def _require_test_fixtures_enabled():
    if not TEST_FIXTURES_ENABLED:
        raise HTTPException(404, 'Test fixtures are disabled')


@router.get('/test-fixtures/sentiment')
def get_sentiment_test_fixture_catalog():
    """Return fixed expected labels for local manual evaluation."""
    _require_test_fixtures_enabled()
    return {'title': FIXTURE_VIDEO_TITLE, 'cases': fixture_case_catalog()}


@router.post('/test-fixtures/sentiment')
def create_sentiment_test_fixture():
    """Persist fixed synthetic comments without calling any crawl endpoint."""
    _require_test_fixtures_enabled()
    comments = batch_analyze(build_fixture_comments())
    summary = summarize_sentiment(comments)
    db = SessionLocal()
    try:
        analysis = Analysis(
            bv='TEST-SENTIMENT-24', avid=0, video_title=FIXTURE_VIDEO_TITLE,
            video_cover='', video_play=0, status='done', mode='nlp',
            total_comments=len(comments),
        )
        db.add(analysis)
        db.flush()
        for comment in comments:
            db.add(Comment(
                analysis_id=analysis.id, rpid=comment['rpid'], root_rpid=comment['root_rpid'],
                parent_rpid=comment['parent_rpid'], username=comment['username'],
                gender=comment['gender'], ip_location=comment['ip_location'], content=comment['content'],
                likes=comment['likes'], sentiment_label=comment['sentiment_label'],
                sentiment_score=comment['sentiment_score'], post_time=comment['post_time'],
            ))
        db.add(SentimentResult(
            analysis_id=analysis.id, positive_count=summary['positive'],
            negative_count=summary['negative'], neutral_count=summary['neutral'],
        ))
        db.commit()
        return {
            'analysis_id': analysis.id, 'status': 'done', 'mode': 'nlp',
            'total_comments': len(comments), 'fixture_cases': fixture_case_catalog(),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@router.get('/video/{bv}')
async def get_video(bv: str):
    async with httpx.AsyncClient(timeout=15) as client:
        info = await get_video_info(client, bv)
    if not info: raise HTTPException(404, 'Video not found')
    return info

async def _run_analysis(
    analysis_id: int, bv: str, avid: int, max_comments: int = 100,
    delay: float = 3.0, mode: str = "nlp", request_id: str | None = None,
):
    token = set_request_id(request_id)
    try:
        with activity("analysis"):
            log_event(logger, "INFO", "analysis.task_started", "视频分析任务已开始", analysis_id=analysis_id, task_type="single_video_analysis")
            return await _run_analysis_inner(analysis_id, bv, avid, max_comments, delay, mode)
    finally:
        reset_request_id(token)


async def _run_analysis_inner(analysis_id: int, bv: str, avid: int, max_comments: int = 100, delay: float = 3.0, mode: str = "nlp"):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            log_event(logger, "WARNING", "analysis.task_aborted", "分析记录已不存在，任务已中止", analysis_id=analysis_id, task_type="single_video_analysis")
            return False
        analysis.status = 'fetching'; analysis.mode = mode; analysis.total_comments = 0
        db.commit()
        log_event(logger, "INFO", "analysis.fetch_started", "开始抓取评论", analysis_id=analysis_id, task_type="single_video_analysis")

        def report_fetch_progress(count: int):
            analysis.total_comments = count
            db.commit()

        async with httpx.AsyncClient(timeout=30) as client:
            comments_raw = await fetch_comments(
                client,
                avid,
                max_comments=max_comments,
                delay=delay,
                progress_callback=report_fetch_progress,
            )
        if not comments_raw:
            analysis.status = 'error'; analysis.error_msg = 'No comments fetched'; db.commit()
            log_event(logger, "WARNING", "analysis.task_failed", "未抓取到可分析评论", analysis_id=analysis_id, task_type="single_video_analysis")
            return False
        analysis.status = 'analyzing'; analysis.total_comments = len(comments_raw); db.commit()

        if mode == "llm":
            log_event(logger, "INFO", "analysis.llm_started", "开始大模型情绪分析", analysis_id=analysis_id, task_type="single_video_analysis", count=len(comments_raw))
            llm_config = get_task_config("sentiment")
            if not llm_config.get("api_key"):
                analysis.status = 'error'; analysis.error_msg = 'API Key not configured'; db.commit()
                log_event(logger, "WARNING", "analysis.task_failed", "情绪分析配置缺失", analysis_id=analysis_id, task_type="single_video_analysis")
                return False
            comments_analyzed = await batch_analyze_llm(comments_raw, llm_config)
            for c in comments_analyzed:
                db.add(Comment(analysis_id=analysis_id, rpid=c['rpid'], root_rpid=c.get('root_rpid'),
                    parent_rpid=c.get('parent_rpid'), username=c['username'],
                    gender=c['gender'], ip_location=c['ip_location'], content=c['content'],
                    likes=c['likes'], sentiment_label=c.get('sentiment_label', ''),
                    sentiment_score=c.get('sentiment_score', 0),
                    sentiment_llm_label=c.get('sentiment_llm_label', ''),
                    sentiment_llm_style=c.get('sentiment_llm_style', 'plain'), post_time=c['post_time']))
            s = summarize_sentiment_llm(comments_analyzed)
            db.add(SentimentResult(analysis_id=analysis_id, positive_count=0, negative_count=0, neutral_count=0,
                llm_neutral=s['neutral'], llm_joy=s['joy'], llm_support=s['support'],
                llm_anger=s['anger'], llm_sadness=s['sadness'], llm_surprise=s['surprise'],
                llm_disgust=s['disgust'], llm_anticipation=s['anticipation'], llm_concern=s['concern'],
                llm_sarcasm=s['sarcasm']))
        else:
            log_event(logger, "INFO", "analysis.local_nlp_started", "开始本地情绪分析", analysis_id=analysis_id, task_type="single_video_analysis", count=len(comments_raw))
            comments_analyzed = batch_analyze(comments_raw)
            for c in comments_analyzed:
                db.add(Comment(analysis_id=analysis_id, rpid=c['rpid'], root_rpid=c.get('root_rpid'),
                    parent_rpid=c.get('parent_rpid'), username=c['username'],
                    gender=c['gender'], ip_location=c['ip_location'], content=c['content'],
                    likes=c['likes'], sentiment_label=c['sentiment_label'],
                    sentiment_score=c['sentiment_score'], post_time=c['post_time']))
            s = summarize_sentiment(comments_analyzed)
            db.add(SentimentResult(analysis_id=analysis_id, positive_count=s['positive'],
                negative_count=s['negative'], neutral_count=s['neutral']))
            log_event(logger, "INFO", "analysis.local_nlp_completed", "本地情绪分析已完成", analysis_id=analysis_id, task_type="single_video_analysis", count=len(comments_analyzed))
        analysis.status = 'done'; db.commit()
        log_event(logger, "INFO", "analysis.database_commit_completed", "分析结果已写入数据库", analysis_id=analysis_id, task_type="single_video_analysis", count=len(comments_analyzed))
        log_event(logger, "INFO", "analysis.task_completed", "视频分析任务已完成", analysis_id=analysis_id, task_type="single_video_analysis", count=len(comments_analyzed))
        return True
    except Exception as e:
        log_event(logger, "ERROR", "analysis.task_failed", "视频分析任务失败", analysis_id=analysis_id, task_type="single_video_analysis", exception=e)
        db.rollback()
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if a: a.status = 'error'; a.error_msg = str(e); db.commit()
        return False
    finally:
        db.close()

@router.post('/analyze')
async def start_analysis(req: dict, background_tasks: BackgroundTasks):
    bv = req.get('bv', '').strip()
    max_comments = min(max(req.get('max_comments', 100), 20), 10000)
    request_delay = min(max(req.get('request_delay', 3.0), 1.0), 60.0)
    # New analyses always start with local Python NLP. LLM sentiment analysis
    # is an explicit second step exposed only by /reanalyze/{analysis_id}.
    mode = 'nlp'
    if not bv or not bv.startswith('BV'):
        raise HTTPException(400, 'Please enter a valid BV number')
    async with httpx.AsyncClient(timeout=15) as client:
        info = await get_video_info(client, bv)
    if not info:
        raise HTTPException(404, 'Video not found or inaccessible')
    db = SessionLocal()
    try:
        analysis = Analysis(bv=bv, avid=info['avid'], video_title=info['title'], mode=mode,
            video_cover=info['cover'], video_play=info['play'], status='pending')
        db.add(analysis); db.commit(); db.refresh(analysis)
        log_event(logger, "INFO", "analysis.task_created", "视频分析任务已创建", analysis_id=analysis.id, task_type="single_video_analysis")
        background_tasks.add_task(
            _run_analysis, analysis.id, bv, info['avid'], max_comments, request_delay,
            mode=mode, request_id=get_request_id(),
        )
        return {'analysis_id':analysis.id,'bv':bv,'video_title':info['title'],
            'video_cover':info['cover'],'video_play':info['play'],'status':'pending','mode':mode}
    except Exception as e:
        log_event(logger, "ERROR", "analysis.task_create_failed", "创建视频分析任务失败", task_type="single_video_analysis", exception=e)
        db.rollback(); raise HTTPException(500, str(e))
    finally:
        db.close()

def _stored_comment_data(comments: list[Comment]) -> list[dict]:
    return [
        {
            'rpid': comment.rpid, 'root_rpid': comment.root_rpid, 'parent_rpid': comment.parent_rpid,
            'username': comment.username, 'gender': comment.gender,
            'ip_location': comment.ip_location, 'content': comment.content, 'likes': comment.likes,
            'post_time': comment.post_time,
            'sentiment_llm_label': comment.sentiment_llm_label or '',
            'sentiment_llm_style': comment.sentiment_llm_style or 'plain',
            'sentiment_llm_schema_version': comment.sentiment_llm_schema_version,
        }
        for comment in comments
    ]


def _is_v2_llm_result(label: object, style: object) -> bool:
    return label in V2_EMOTION_LABELS and style in V2_STYLE_LABELS


def _safe_reanalysis_error(_error: Exception | None = None) -> str:
    """Keep persisted status actionable without serializing model/provider input."""
    return "大模型情绪分析未完成，请检查配置后仅补齐待处理评论"


def _finalize_v2_reanalysis(db, analysis: Analysis) -> bool:
    """Write the V2 analysis/result boundary only after full comment coverage."""
    comments = db.query(Comment).filter_by(analysis_id=analysis.id).all()
    if not comments or any(comment.sentiment_llm_schema_version != LLM_SENTIMENT_SCHEMA_V2 for comment in comments):
        return False
    counts = {label: 0 for label in V2_EMOTION_LABELS}
    for comment in comments:
        if not _is_v2_llm_result(comment.sentiment_llm_label, comment.sentiment_llm_style):
            return False
        counts[comment.sentiment_llm_label] += 1
    values = {
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count": 0,
        "llm_neutral": counts["neutral"],
        "llm_joy": counts["joy"],
        "llm_trust": counts["trust"],
        "llm_anticipation": counts["anticipation"],
        "llm_surprise": counts["surprise"],
        "llm_anger": counts["anger"],
        "llm_sadness": counts["sadness"],
        "llm_fear": counts["fear"],
        "llm_disgust": counts["disgust"],
        "llm_support": 0,
        "llm_concern": 0,
        "llm_sarcasm": 0,
        "sentiment_llm_schema_version": LLM_SENTIMENT_SCHEMA_V2,
    }
    result = db.query(SentimentResult).filter_by(analysis_id=analysis.id).first()
    if result:
        for field, value in values.items():
            setattr(result, field, value)
    else:
        db.add(SentimentResult(analysis_id=analysis.id, **values))
    analysis.sentiment_llm_schema_version = LLM_SENTIMENT_SCHEMA_V2
    analysis.status = "done"
    analysis.mode = "llm"
    analysis.processed_comments = len(comments)
    analysis.error_msg = None
    return True


@router.post('/reanalyze/{analysis_id}')
async def reanalyze(analysis_id: int, background_tasks: BackgroundTasks):
    """Re-analyze existing comments with LLM sentiment analysis.
    Only works when current mode is 'nlp' and target mode is 'llm'.
    Reuses stored comments, skips B站 fetching."""
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a:
            raise HTTPException(404, 'Analysis not found')
        if a.status != 'done':
            raise HTTPException(400, f'Analysis not complete (current: {a.status})')
        # Keep the persisted mode as NLP until the LLM pass succeeds so a
        # provider failure never destroys access to the existing result.
        # Load existing comments
        all_comments = _stored_comment_data(db.query(Comment).filter_by(analysis_id=analysis_id).all())
        comments_data = [
            comment for comment in all_comments
            if comment.get('sentiment_llm_schema_version') != LLM_SENTIMENT_SCHEMA_V2
        ]
        if not comments_data:
            _finalize_v2_reanalysis(db, a)
            db.commit()
            return {'analysis_id': analysis_id, 'status': 'done', 'mode': 'llm', 'skipped': True}
        llm_config = get_task_config("sentiment")
        if not llm_config.get("api_key"):
            raise HTTPException(400, 'API Key not configured')
        # Progress is based on the stored comments, not just the comments that
        # require a model call. Existing valid labels are retained as completed.
        a.status = 'analyzing'; a.error_msg = None
        a.total_comments = len(all_comments); a.processed_comments = len(all_comments) - len(comments_data)
        db.commit()

        # Run LLM in background
        log_event(logger, "INFO", "reanalyze.task_created", "大模型重分析任务已创建", analysis_id=analysis_id, task_type="llm_reanalysis", count=len(comments_data))
        background_tasks.add_task(
            _run_reanalyze, analysis_id, comments_data, llm_config, all_comments, a.mode,
            request_id=get_request_id(),
        )
        return {'analysis_id': analysis_id, 'status': 'analyzing', 'mode': 'llm'}
    except HTTPException:
        raise
    except Exception as e:
        log_event(logger, "ERROR", "reanalyze.task_create_failed", "创建大模型重分析任务失败", analysis_id=analysis_id, task_type="llm_reanalysis", exception=e)
        db.rollback()
        a2 = db.query(Analysis).filter_by(id=analysis_id).first()
        if a2: a2.status = 'error'; a2.error_msg = _safe_reanalysis_error(e); db.commit()
        raise HTTPException(500, _safe_reanalysis_error(e))
    finally:
        db.close()


async def _run_reanalyze(
    analysis_id: int, comments_data: list[dict], llm_config: dict[str, str],
    context_comments: list[dict] | None = None, failure_mode: str = 'nlp',
    request_id: str | None = None,
):
    """Background task: re-analyze existing comments with LLM."""
    token = set_request_id(request_id)
    try:
        with activity("llm_sentiment"):
            log_event(logger, "INFO", "reanalyze.task_started", "大模型重分析任务已开始", analysis_id=analysis_id, task_type="llm_reanalysis", count=len(comments_data))
            await _run_reanalyze_inner(
                analysis_id, comments_data, llm_config, context_comments=context_comments, failure_mode=failure_mode,
            )
    finally:
        reset_request_id(token)


async def _run_reanalyze_inner(
    analysis_id: int, comments_data: list[dict], llm_config: dict[str, str],
    *, context_comments: list[dict] | None = None, failure_mode: str = 'nlp',
):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            return False
        initial_processed = db.query(Comment).filter_by(
            analysis_id=analysis_id,
            sentiment_llm_schema_version=LLM_SENTIMENT_SCHEMA_V2,
        ).count()
        persisted_rpids: set[str] = set()

        def report_progress(processed_comments: int):
            # ``batch_analyze_llm`` mutates only a validated completed batch
            # before invoking this callback.  Persist those labels together
            # with progress so a later failed batch never discards successful
            # work or sends it to the paid model again on the next attempt.
            for comment in comments_data:
                label = comment.get("sentiment_llm_label", "")
                style = comment.get("sentiment_llm_style", "plain")
                comment_id = str(comment.get("rpid"))
                if not _is_v2_llm_result(label, style) or comment_id in persisted_rpids:
                    continue
                db.query(Comment).filter_by(analysis_id=analysis_id, rpid=comment.get("rpid")).update({
                    "sentiment_llm_label": label,
                    "sentiment_llm_style": style,
                    "sentiment_llm_schema_version": LLM_SENTIMENT_SCHEMA_V2,
                })
                persisted_rpids.add(comment_id)
            db.query(Analysis).filter_by(id=analysis_id).update({
                'processed_comments': min(
                    analysis.total_comments or len(context_comments or comments_data),
                    initial_processed + processed_comments,
                ),
            })
            db.commit()
            log_event(logger, "INFO", "reanalyze.batch_completed", "大模型批次结果已持久化", analysis_id=analysis_id, task_type="llm_reanalysis", count=initial_processed + processed_comments)

        # Run LLM analysis
        batch_kwargs = {
            'progress_callback': report_progress,
            'video_title': analysis.video_title,
        }
        if context_comments is not None:
            batch_kwargs['context_comments'] = context_comments
        comments_analyzed = await batch_analyze_llm(comments_data, llm_config, **batch_kwargs)
        # Test doubles and future service changes cannot bypass the V2 boundary:
        # persist a final validated sweep before the analysis-level upgrade.
        report_progress(len(comments_analyzed))
        db.refresh(analysis)
        if not _finalize_v2_reanalysis(db, analysis):
            raise RuntimeError("大模型情绪结果未完成 V2 覆盖")
        db.commit()
        log_event(logger, "INFO", "reanalyze.database_commit_completed", "大模型重分析结果已写入数据库", analysis_id=analysis_id, task_type="llm_reanalysis", count=analysis.total_comments)
        log_event(logger, "INFO", "reanalyze.task_completed", "大模型重分析任务已完成", analysis_id=analysis_id, task_type="llm_reanalysis", count=analysis.total_comments)
        return True
    except Exception as e:
        log_event(logger, "ERROR", "reanalyze.task_failed", "大模型重分析任务失败", analysis_id=analysis_id, task_type="llm_reanalysis", exception=e)
        db.rollback()
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if a:
            a.status = 'done'
            a.mode = failure_mode
            a.error_msg = _safe_reanalysis_error(e)
            db.commit()
        return False
    finally:
        db.close()


@router.get('/status/{analysis_id}')
def get_status(analysis_id: int):
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a: raise HTTPException(404, 'Not found')
        v2_target_count = db.query(Comment).filter_by(analysis_id=analysis_id).count()
        v2_completed_count = db.query(Comment).filter_by(
            analysis_id=analysis_id,
            sentiment_llm_schema_version=LLM_SENTIMENT_SCHEMA_V2,
        ).count()
        error_summary = _safe_reanalysis_error() if a.error_msg else None
        return {'analysis_id':a.id,'status':a.status,'total_comments':a.total_comments,
            'processed_comments':a.processed_comments,'error_msg':error_summary,
            'error_summary':error_summary,
            'v2_target_count':v2_target_count,
            'v2_completed_count':v2_completed_count,
            'v2_pending_count':v2_target_count - v2_completed_count}
    finally: db.close()


@router.get('/results/{analysis_id}')
def get_results(analysis_id: int):
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a: raise HTTPException(404, 'Not found')
        if a.status != 'done': return {'status':a.status,'message':'Analysis not complete','mode':a.mode}
        comments = db.query(Comment).filter_by(analysis_id=analysis_id).all()
        s = db.query(SentimentResult).filter_by(analysis_id=analysis_id).first()
        cl = [{'id':c.id,'rpid':c.rpid,'root_rpid':c.root_rpid,'parent_rpid':c.parent_rpid,
            'username':c.username,'gender':c.gender,
            'ip_location':c.ip_location,'content':c.content,'likes':c.likes,
            'sentiment_label':c.sentiment_label,'sentiment_score':c.sentiment_score,
            'sentiment_llm_label':c.sentiment_llm_label if c.sentiment_llm_label else '',
            'sentiment_llm_style':c.sentiment_llm_style or 'plain',
            'post_time':c.post_time.isoformat() if c.post_time else None} for c in comments]
        cl = annotate_exact_duplicates(cl)
        result = {'analysis_id':a.id,'bv':a.bv,'video_title':a.video_title,
            'video_cover':a.video_cover,'video_play':a.video_play,
            'mode':a.mode,
            'total_comments':a.total_comments,'created_at':a.created_at.isoformat() if a.created_at else None,
            'sentiment':{'positive':s.positive_count if s else 0,'negative':s.negative_count if s else 0,'neutral':s.neutral_count if s else 0},
            'gender':_calc_gender(cl),'region':analyze_region(cl),'heat':analyze_heat(cl),
            'keywords':get_top_keywords(cl, top_n=500),
            'duplicate_statistics':build_duplicate_statistics(cl),'comments':cl}
        if a.mode == 'llm' and s:
            if (
                a.sentiment_llm_schema_version == LLM_SENTIMENT_SCHEMA_V2
                and s.sentiment_llm_schema_version == LLM_SENTIMENT_SCHEMA_V2
            ):
                result['sentiment_llm'] = {
                    'neutral':s.llm_neutral,'joy':s.llm_joy,'trust':s.llm_trust,
                    'anticipation':s.llm_anticipation,'surprise':s.llm_surprise,'anger':s.llm_anger,
                    'sadness':s.llm_sadness,'fear':s.llm_fear,'disgust':s.llm_disgust,
                }
            else:
                result['sentiment_llm'] = {
                    'neutral':s.llm_neutral,'joy':s.llm_joy,'support':s.llm_support or s.llm_trust,
                    'anticipation':s.llm_anticipation,'surprise':s.llm_surprise,'anger':s.llm_anger,
                    'sadness':s.llm_sadness,'concern':s.llm_concern or s.llm_fear,'disgust':s.llm_disgust,
                    'sarcasm':s.llm_sarcasm,
                }
        return result
    finally: db.close()


@router.post('/keywords/{analysis_id}')
def get_filtered_keywords(analysis_id: int, req: dict):
    """Rebuild keywords from the same final collection used by filtered views.

    This endpoint is entirely local: it only reads SQLite and runs the existing
    deterministic duplicate/filter/word-segmentation services. It never calls
    either configured LLM task.
    """
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            raise HTTPException(404, 'Not found')
        if analysis.status != 'done':
            raise HTTPException(400, 'Analysis not complete')
        try:
            filters = normalize_filters(req.get('filters'), analysis.mode)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        comments = annotate_exact_duplicates([{
            'id': comment.id,
            'rpid': comment.rpid,
            'content': comment.content,
            'gender': comment.gender,
            'ip_location': comment.ip_location,
            'post_time': comment.post_time,
            'sentiment_label': comment.sentiment_label,
            'sentiment_llm_label': comment.sentiment_llm_label or '',
        } for comment in db.query(Comment).filter_by(analysis_id=analysis_id).all()])
        matched = apply_filters(comments, filters, analysis.mode)
        return {
            'matched_count': len(matched),
            'keywords': get_top_keywords(matched, top_n=500),
        }
    finally:
        db.close()

@router.get('/wordcloud/{analysis_id}')
def get_wordcloud(analysis_id: int):
    db = SessionLocal()
    try:
        comments = db.query(Comment).filter_by(analysis_id=analysis_id).all()
        if not comments: raise HTTPException(404, 'No comments')
        return {'base64':generate_wordcloud([{'content':c.content} for c in comments])}
    finally: db.close()

@router.get('/history')
def get_history(limit: int = 20):
    db = SessionLocal()
    try:
        analyses = db.query(Analysis).order_by(desc(Analysis.created_at)).limit(limit).all()
        analysis_ids = [analysis.id for analysis in analyses]
        affected_counts = dict(
            db.query(AnalysisGroupItem.analysis_id, func.count(AnalysisGroupItem.id))
            .filter(AnalysisGroupItem.analysis_id.in_(analysis_ids))
            .group_by(AnalysisGroupItem.analysis_id)
            .all()
        ) if analysis_ids else {}
        return [{'id':a.id,'bv':a.bv,'video_title':a.video_title,'video_cover':a.video_cover,
            'total_comments':a.total_comments,'status':a.status,'mode':a.mode,
            'affected_group_count':affected_counts.get(a.id, 0),
            'created_at':a.created_at.isoformat() if a.created_at else None}
            for a in analyses]
    finally: db.close()

@router.delete('/history/{analysis_id}')
def delete_history(analysis_id: int):
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a: raise HTTPException(404, 'Not found')
        affected_group_count = db.query(AnalysisGroupItem).filter_by(analysis_id=analysis_id).count()
        db.query(AnalysisGroupItem).filter_by(analysis_id=analysis_id).delete(synchronize_session=False)
        db.delete(a); db.commit()
        return {'deleted': True, 'affected_group_count': affected_group_count}
    except HTTPException:
        db.rollback(); raise
    except Exception as e:
        db.rollback(); raise HTTPException(500, str(e)) from e
    finally:
        db.close()

def _calc_gender(comments):
    return {'male':sum(1 for c in comments if c.get('gender')=='?'),
        'female':sum(1 for c in comments if c.get('gender')=='?'),
        'unknown':sum(1 for c in comments if c.get('gender')=='??')}
