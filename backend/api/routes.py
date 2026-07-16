import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from sqlalchemy import desc
from models.database import SessionLocal, Analysis, Comment, SentimentResult, init_db
from services.bilibili import get_video_info, fetch_comments
from services.sentiment import batch_analyze, summarize_sentiment
from services.wordcloud_gen import generate_wordcloud, get_top_keywords
from services.region import analyze_region
from services.heat import analyze_heat

router = APIRouter(prefix='/api')

@router.get('/video/{bv}')
async def get_video(bv: str):
    async with httpx.AsyncClient(timeout=15) as client:
        info = await get_video_info(client, bv)
    if not info: raise HTTPException(404, 'Video not found')
    return info

async def _run_analysis(analysis_id: int, bv: str, avid: int, max_comments: int = 100, delay: float = 3.0):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis: return
        analysis.status = 'fetching'
        db.commit()
        async with httpx.AsyncClient(timeout=30) as client:
            comments_raw = await fetch_comments(client, avid, max_comments=max_comments, delay=delay)
        if not comments_raw:
            analysis.status = 'error'; analysis.error_msg = 'No comments fetched'; db.commit(); return
        analysis.status = 'analyzing'; analysis.total_comments = len(comments_raw); db.commit()
        comments_analyzed = batch_analyze(comments_raw)
        for c in comments_analyzed:
            db.add(Comment(analysis_id=analysis_id, rpid=c['rpid'], username=c['username'],
                gender=c['gender'], ip_location=c['ip_location'], content=c['content'],
                likes=c['likes'], sentiment_label=c['sentiment_label'],
                sentiment_score=c['sentiment_score'], post_time=c['post_time']))
        s = summarize_sentiment(comments_analyzed)
        db.add(SentimentResult(analysis_id=analysis_id, positive_count=s['positive'],
            negative_count=s['negative'], neutral_count=s['neutral']))
        analysis.status = 'done'; db.commit()
    except Exception as e:
        db.rollback()
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if a: a.status = 'error'; a.error_msg = str(e); db.commit()
    finally:
        db.close()

@router.post('/analyze')
async def start_analysis(req: dict, background_tasks: BackgroundTasks):
    bv = req.get('bv', '').strip()
    max_comments = min(max(req.get('max_comments', 100), 20), 10000)
    request_delay = min(max(req.get('request_delay', 3.0), 1.0), 60.0)
    if not bv or not bv.startswith('BV'):
        raise HTTPException(400, 'Please enter a valid BV number')
    async with httpx.AsyncClient(timeout=15) as client:
        info = await get_video_info(client, bv)
    if not info:
        raise HTTPException(404, 'Video not found or inaccessible')
    db = SessionLocal()
    try:
        analysis = Analysis(bv=bv, avid=info['avid'], video_title=info['title'],
            video_cover=info['cover'], video_play=info['play'], status='pending')
        db.add(analysis); db.commit(); db.refresh(analysis)
        background_tasks.add_task(_run_analysis, analysis.id, bv, info['avid'], max_comments, request_delay)
        return {'analysis_id':analysis.id,'bv':bv,'video_title':info['title'],
            'video_cover':info['cover'],'video_play':info['play'],'status':'pending'}
    except Exception as e:
        db.rollback(); raise HTTPException(500, str(e))
    finally:
        db.close()

@router.get('/status/{analysis_id}')
def get_status(analysis_id: int):
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a: raise HTTPException(404, 'Not found')
        return {'analysis_id':a.id,'status':a.status,'total_comments':a.total_comments,'error_msg':a.error_msg}
    finally: db.close()

@router.get('/results/{analysis_id}')
def get_results(analysis_id: int):
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a: raise HTTPException(404, 'Not found')
        if a.status != 'done': return {'status':a.status,'message':'Analysis not complete'}
        comments = db.query(Comment).filter_by(analysis_id=analysis_id).all()
        s = db.query(SentimentResult).filter_by(analysis_id=analysis_id).first()
        cl = [{'id':c.id,'rpid':c.rpid,'username':c.username,'gender':c.gender,
            'ip_location':c.ip_location,'content':c.content,'likes':c.likes,
            'sentiment_label':c.sentiment_label,'sentiment_score':c.sentiment_score,
            'post_time':c.post_time.isoformat() if c.post_time else None} for c in comments]
        return {'analysis_id':a.id,'bv':a.bv,'video_title':a.video_title,
            'video_cover':a.video_cover,'video_play':a.video_play,
            'total_comments':a.total_comments,'created_at':a.created_at.isoformat() if a.created_at else None,
            'sentiment':{'positive':s.positive_count if s else 0,'negative':s.negative_count if s else 0,'neutral':s.neutral_count if s else 0},
            'gender':_calc_gender(cl),'region':analyze_region(cl),'heat':analyze_heat(cl),
            'keywords':get_top_keywords(cl),'comments':cl}
    finally: db.close()

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
        return [{'id':a.id,'bv':a.bv,'video_title':a.video_title,'video_cover':a.video_cover,
            'total_comments':a.total_comments,'status':a.status,
            'created_at':a.created_at.isoformat() if a.created_at else None}
            for a in db.query(Analysis).order_by(desc(Analysis.created_at)).limit(limit).all()]
    finally: db.close()

def _calc_gender(comments):
    return {'male':sum(1 for c in comments if c.get('gender')=='男'),
        'female':sum(1 for c in comments if c.get('gender')=='女'),
        'unknown':sum(1 for c in comments if c.get('gender')=='保密')}