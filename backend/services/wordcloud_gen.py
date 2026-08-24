"""词云生成服务"""

import base64
import io
import re
from collections import Counter

import jieba
from wordcloud import WordCloud
from PIL import Image
import numpy as np

from config import STOPWORDS, WORDCLOUD_WIDTH, WORDCLOUD_HEIGHT, WORDCLOUD_MAX_WORDS


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


def generate_wordcloud(comments: list[dict]) -> str:
    """根据评论列表生成词云图，返回 base64 PNG"""
    filtered = _extract_keyword_words(comments)

    if not filtered:
        return ""

    word_counts = dict(Counter(filtered).most_common(WORDCLOUD_MAX_WORDS))

    # 使用默认字体（Windows 中文字体路径）
    font_path = None
    for candidate in [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]:
        try:
            from pathlib import Path
            if Path(candidate).exists():
                font_path = candidate
                break
        except Exception:
            continue

    wc = WordCloud(
        width=WORDCLOUD_WIDTH,
        height=WORDCLOUD_HEIGHT,
        font_path=font_path,
        background_color="white",
        max_words=WORDCLOUD_MAX_WORDS,
        collocations=False,
    )
    wc.generate_from_frequencies(word_counts)

    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def get_top_keywords(comments: list[dict], top_n: int = 20) -> list[dict]:
    """获取高频关键词列表"""
    counter = Counter(_extract_keyword_words(comments))
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]
