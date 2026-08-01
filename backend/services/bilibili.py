import asyncio, random
from datetime import datetime
import httpx
from config import BILIBILI_USER_AGENT, BILIBILI_REFERER, MAX_COMMENTS, REQUEST_DELAY
from services.auth import get_cookie

def _headers():
    cookie = get_cookie()
    return {'User-Agent':BILIBILI_USER_AGENT,'Referer':BILIBILI_REFERER,'Cookie':cookie}

async def get_video_info(client: httpx.AsyncClient, bv: str):
    resp = await client.get('https://api.bilibili.com/x/web-interface/view',
        params={'bvid':bv}, headers=_headers())
    if resp.status_code != 200: return None
    j = resp.json()
    if j.get('code') != 0: return None
    d = j['data']
    cover = (d.get('pic','') or '').replace('http://','https://')
    return {'bv':bv,'avid':d.get('aid',0),'title':d.get('title',''),
            'cover':cover,'play':d.get('stat',{}).get('view',0),
            'comment_count':d.get('stat',{}).get('reply',0)}

def _extract_comment(r: dict) -> dict:
    m = r.get('member',{})
    ctrl = r.get('reply_control',{})
    return {
        'rpid':r.get('rpid',0),'username':m.get('uname',''),
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
            print(f'Page {page} failed: {e}')
            break
        if resp.status_code != 200: break
        j = resp.json()
        if j.get('code') != 0: break
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
        if len(all_comments) >= limit:
            break
        page += 1
        await asyncio.sleep(wait + random.uniform(0, 0.5))
        if page > 50: break
    return all_comments

def _map_gender(sex):
    return {'男':'男','女':'女'}.get(sex,'保密')
