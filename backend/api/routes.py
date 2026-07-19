import httpx
import json
import os
from fastapi import APIRouter, HTTPException, BackgroundTasks
from sqlalchemy import desc
from models.database import SessionLocal, Analysis, Comment, SentimentResult, init_db
from services.bilibili import get_video_info, fetch_comments
from services.sentiment import batch_analyze, summarize_sentiment
from services.sentiment_llm import batch_analyze_llm, summarize_sentiment_llm
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

async def _run_analysis(analysis_id: int, bv: str, avid: int, max_comments: int = 100, delay: float = 3.0, mode: str = "nlp"):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis: return
        analysis.status = 'fetching'; analysis.mode = mode
        db.commit()
        async with httpx.AsyncClient(timeout=30) as client:
            comments_raw = await fetch_comments(client, avid, max_comments=max_comments, delay=delay)
        if not comments_raw:
            analysis.status = 'error'; analysis.error_msg = 'No comments fetched'; db.commit(); return
        analysis.status = 'analyzing'; analysis.total_comments = len(comments_raw); db.commit()

        if mode == "llm":
            settings_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as sf:
                    settings = json.load(sf)
                api_key = settings.get("api_key", "")
            else:
                api_key = ""
            if not api_key:
                analysis.status = 'error'; analysis.error_msg = 'API Key not configured'; db.commit(); return
            comments_analyzed = await batch_analyze_llm(comments_raw, api_key)
            for c in comments_analyzed:
                db.add(Comment(analysis_id=analysis_id, rpid=c['rpid'], username=c['username'],
                    gender=c['gender'], ip_location=c['ip_location'], content=c['content'],
                    likes=c['likes'], sentiment_label=c.get('sentiment_label', ''),
                    sentiment_score=c.get('sentiment_score', 0),
                    sentiment_llm_label=c.get('sentiment_llm_label', ''), post_time=c['post_time']))
            s = summarize_sentiment_llm(comments_analyzed)
            db.add(SentimentResult(analysis_id=analysis_id, positive_count=0, negative_count=0, neutral_count=0,
                llm_joy=s['joy'], llm_anger=s['anger'], llm_sadness=s['sadness'],
                llm_surprise=s['surprise'], llm_fear=s['fear'], llm_disgust=s['disgust'],
                llm_anticipation=s['anticipation'], llm_trust=s['trust']))
        else:
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
    mode = req.get('mode', 'nlp')
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
        background_tasks.add_task(_run_analysis, analysis.id, bv, info['avid'], max_comments, request_delay, mode=mode)
        return {'analysis_id':analysis.id,'bv':bv,'video_title':info['title'],
            'video_cover':info['cover'],'video_play':info['play'],'status':'pending','mode':mode}
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
        if a.status != 'done': return {'status':a.status,'message':'Analysis not complete','mode':a.mode}
        comments = db.query(Comment).filter_by(analysis_id=analysis_id).all()
        s = db.query(SentimentResult).filter_by(analysis_id=analysis_id).first()
        cl = [{'id':c.id,'rpid':c.rpid,'username':c.username,'gender':c.gender,
            'ip_location':c.ip_location,'content':c.content,'likes':c.likes,
            'sentiment_label':c.sentiment_label,'sentiment_score':c.sentiment_score,
            'sentiment_llm_label':c.sentiment_llm_label if c.sentiment_llm_label else '',
            'post_time':c.post_time.isoformat() if c.post_time else None} for c in comments]
        result = {'analysis_id':a.id,'bv':a.bv,'video_title':a.video_title,
            'video_cover':a.video_cover,'video_play':a.video_play,
            'mode':a.mode,
            'total_comments':a.total_comments,'created_at':a.created_at.isoformat() if a.created_at else None,
            'sentiment':{'positive':s.positive_count if s else 0,'negative':s.negative_count if s else 0,'neutral':s.neutral_count if s else 0},
            'gender':_calc_gender(cl),'region':analyze_region(cl),'heat':analyze_heat(cl),
            'keywords':get_top_keywords(cl, top_n=500),'comments':cl}
        if a.mode == 'llm' and s:
            result['sentiment_llm'] = {
                'joy':s.llm_joy,'anger':s.llm_anger,'sadness':s.llm_sadness,
                'surprise':s.llm_surprise,'fear':s.llm_fear,'disgust':s.llm_disgust,
                'anticipation':s.llm_anticipation,'trust':s.llm_trust,
            }
        return result
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

@router.delete('/history/{analysis_id}')
def delete_history(analysis_id: int):
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(id=analysis_id).first()
        if not a: raise HTTPException(404, 'Not found')
        db.delete(a); db.commit()
        return {'deleted': True}
    except Exception as e:
        db.rollback(); raise HTTPException(500, str(e))
    finally:
        db.close()

def _calc_gender(comments):
    return {'male':sum(1 for c in comments if c.get('gender')=='?'),
        'female':sum(1 for c in comments if c.get('gender')=='?'),
        'unknown':sum(1 for c in comments if c.get('gender')=='??')}
