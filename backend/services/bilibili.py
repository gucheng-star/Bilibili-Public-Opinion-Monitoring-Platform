import asyncio, random
from datetime import datetime
import httpx
from config import BILIBILI_USER_AGENT, BILIBILI_REFERER, MAX_COMMENTS, REQUEST_DELAY
from services.auth import get_cookie
from services.logging_config import get_logger, log_event


logger = get_logger("bilibili")

def _headers():
    cookie = get_cookie()
    return {'User-Agent':BILIBILI_USER_AGENT,'Referer':BILIBILI_REFERER,'Cookie':cookie}

async def get_video_info(client: httpx.AsyncClient, bv: str):
    try:
        resp = await client.get('https://api.bilibili.com/x/web-interface/view',
            params={'bvid':bv}, headers=_headers())
    except Exception as exc:
        log_event(logger, "ERROR", "bilibili.video_request_failed", "视频信息请求失败", exception=exc)
        raise
    if resp.status_code != 200:
        log_event(logger, "WARNING", "bilibili.video_request_failed", "视频信息接口返回异常状态", status_code=resp.status_code)
        return None
    j = resp.json()
    if j.get('code') != 0:
        log_event(logger, "WARNING", "bilibili.video_response_rejected", "视频信息接口返回业务错误")
        return None
    d = j['data']
    cover = (d.get('pic','') or '').replace('http://','https://')
    return {'bv':bv,'avid':d.get('aid',0),'title':d.get('title',''),
            'cover':cover,'play':d.get('stat',{}).get('view',0),
            'comment_count':d.get('stat',{}).get('reply',0)}

def _extract_comment(r: dict) -> dict:
    m = r.get('member',{})
    ctrl = r.get('reply_control',{})
    rpid = r.get('rpid', 0)
    root_rpid = r.get('root') or rpid
    parent_rpid = r.get('parent') or None
    return {
        'rpid':rpid,'root_rpid':root_rpid,'parent_rpid':parent_rpid,'username':m.get('uname',''),
        'gender':_map_gender(m.get('sex','')),'ip_location':ctrl.get('location',''),
        'content':r.get('content',{}).get('message',''),'likes':r.get('like',0),
        'post_time':datetime.fromtimestamp(r.get('ctime',0)),
    }

async def fetch_comments(client: httpx.AsyncClient, avid: int, max_comments=None, delay=None, progress_callback=None):
    all_comments = []
    page = 1
    page_size = 20
    limit = max_comments or MAX_COMMENTS
    wait = delay if delay is not None else REQUEST_DELAY
    while len(all_comments) < limit:
        try:
            resp = await client.get('https://api.bilibili.com/x/v2/reply',
                params={'oid':avid,'type':1,'pn':page,'ps':page_size,'sort':2},
                headers=_headers())
        except Exception as e:
            log_event(logger, "ERROR", "bilibili.fetch_page_failed", "评论分页请求失败", batch_index=page, count=len(all_comments), exception=e)
            break
        if resp.status_code != 200:
            log_event(logger, "WARNING", "bilibili.fetch_page_failed", "评论分页接口返回异常状态", batch_index=page, count=len(all_comments), status_code=resp.status_code)
            break
        j = resp.json()
        if j.get('code') != 0:
            log_event(logger, "WARNING", "bilibili.fetch_page_rejected", "评论分页接口返回业务错误", batch_index=page, count=len(all_comments))
            break
        replies = j.get('data',{}).get('replies')
        if replies is None or not replies: break
        for r in replies:
            if not isinstance(r, dict): continue
            if len(all_comments) >= limit: break
            all_comments.append(_extract_comment(r))
            # Extract sub-replies (secondary comments)
            sub_replies = r.get('replies')
            if sub_replies and isinstance(sub_replies, list):
                for sr in sub_replies:
                    if not isinstance(sr, dict): continue
                    if len(all_comments) >= limit: break
                    c = _extract_comment(sr)
                    all_comments.append(c)
        if progress_callback:
            progress_callback(len(all_comments))
        log_event(logger, "INFO", "bilibili.fetch_page_completed", "评论分页抓取已完成", batch_index=page, count=len(all_comments))
        if len(all_comments) >= limit:
            break
        page += 1
        await asyncio.sleep(wait + random.uniform(0, 0.5))
        if page > 50: break
    return all_comments

def _map_gender(sex):
    return {'男':'男','女':'女'}.get(sex,'保密')
