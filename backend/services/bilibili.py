"""B站 API 客户端 —— 视频信息、评论抓取、WBI签名"""

import asyncio
import hashlib
import random
import time
import urllib.parse
from datetime import datetime

import httpx

from config import BILIBILI_USER_AGENT, BILIBILI_REFERER, REQUEST_DELAY, MAX_COMMENTS
from utils.bv_av import bv2av

WBI_MIXIN_KEY_CACHE = {"key": "", "img_url": "", "sub_url": ""}


async def _get_wbi_keys(client: httpx.AsyncClient) -> str:
    """获取 WBI 签名所需的 mixin key"""
    if WBI_MIXIN_KEY_CACHE["key"]:
        return WBI_MIXIN_KEY_CACHE["key"]

    resp = await client.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"Referer": BILIBILI_REFERER, "User-Agent": BILIBILI_USER_AGENT},
    )
    data = resp.json().get("data", {})
    img_url = data.get("wbi_img", {}).get("img_url", "")
    sub_url = data.get("wbi_img", {}).get("sub_url", "")

    if img_url and sub_url:
        img_key = img_url.split("/")[-1].split(".")[0]
        sub_key = sub_url.split("/")[-1].split(".")[0]
        mixin = img_key + sub_key
        mixin_key = ""
        for c in mixin:
            mixin_key += c if c.isdigit() or c.isalpha() else ""
        WBI_MIXIN_KEY_CACHE["key"] = mixin_key
        return mixin_key
    return ""


def _wbi_sign(params: dict, mixin_key: str) -> dict:
    """对请求参数进行 WBI 签名"""
    sorted_params = sorted(params.items())
    query = urllib.parse.urlencode(sorted_params)
    sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = sign
    params["wts"] = params.get("wts", int(time.time()))
    return params


async def get_video_info(client: httpx.AsyncClient, bv: str) -> dict | None:
    """获取视频基础信息"""
    resp = await client.get(
        f"https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bv},
        headers={"Referer": BILIBILI_REFERER, "User-Agent": BILIBILI_USER_AGENT},
    )
    if resp.status_code != 200:
        return None
    j = resp.json()
    if j.get("code") != 0:
        return None
    d = j["data"]
    return {
        "bv": bv,
        "avid": d.get("aid", 0),
        "title": d.get("title", ""),
        "cover": d.get("pic", ""),
        "play": d.get("stat", {}).get("view", 0),
        "comment_count": d.get("stat", {}).get("reply", 0),
    }


async def fetch_comments(client: httpx.AsyncClient, avid: int, progress_callback=None) -> list[dict]:
    """抓取视频评论（分页，带 WBI 签名）"""
    mixin_key = await _get_wbi_keys(client)
    all_comments = []
    page = 1
    page_size = 40

    while len(all_comments) < MAX_COMMENTS:
        params = {
            "oid": avid,
            "type": 1,
            "mode": 3,
            "ps": page_size,
            "pn": page,
            "wts": int(time.time()),
        }
        if mixin_key:
            params = _wbi_sign(params, mixin_key)

        try:
            resp = await client.get(
                "https://api.bilibili.com/x/v2/reply/wbi/main",
                params=params,
                headers={"Referer": BILIBILI_REFERER, "User-Agent": BILIBILI_USER_AGENT},
            )
        except Exception as e:
            print(f"Request failed on page {page}: {e}")
            break

        if resp.status_code != 200:
            break
        j = resp.json()
        if j.get("code") != 0:
            break

        replies = j.get("data", {}).get("replies", [])
        if not replies:
            break

        for reply in replies:
            member = reply.get("member", {})
            ctrl = reply.get("reply_control", {})
            all_comments.append({
                "rpid": reply.get("rpid", 0),
                "username": member.get("uname", ""),
                "gender": _map_gender(member.get("sex", "")),
                "ip_location": ctrl.get("location", ""),
                "content": reply.get("content", {}).get("message", ""),
                "likes": reply.get("like", 0),
                "post_time": datetime.fromtimestamp(reply.get("ctime", 0)),
            })

        page += 1
        if progress_callback:
            progress_callback(len(all_comments), page - 1)
        await asyncio.sleep(REQUEST_DELAY + random.uniform(0, 0.3))

    return all_comments


def _map_gender(sex: str) -> str:
    """B站性别字段映射"""
    mapping = {"男": "男", "女": "女"}
    return mapping.get(sex, "保密")
