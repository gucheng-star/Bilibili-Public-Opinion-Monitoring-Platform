"""词云关键词提取服务。"""

import re
from collections import Counter

import jieba

from config import STOPWORDS


_BILIBILI_EMOTE_PATTERN = re.compile(r"\[[^\[\]\r\n]{1,32}\]")


def _extract_keyword_words(comments: list[dict]) -> list[str]:
    """分词前移除 B 站短方括号表情，同时保留同名普通文本。"""
    text_parts = []
    for comment in comments:
        content = comment.get("content", "")
        if isinstance(content, str) and content:
            text_parts.append(_BILIBILI_EMOTE_PATTERN.sub(" ", content))

    all_text = " ".join(text_parts)
    if not all_text.strip():
        return []

    words = jieba.lcut(all_text)
    return [
        word
        for raw_word in words
        if len(word := raw_word.strip()) >= 2 and word not in STOPWORDS
    ]


def get_top_keywords(comments: list[dict], top_n: int = 20) -> list[dict]:
    """获取高频关键词列表"""
    counter = Counter(_extract_keyword_words(comments))
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]
