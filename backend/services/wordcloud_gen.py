"""词云生成服务"""

import base64
import io
from collections import Counter

import jieba
from wordcloud import WordCloud
from PIL import Image
import numpy as np

from config import STOPWORDS, WORDCLOUD_WIDTH, WORDCLOUD_HEIGHT, WORDCLOUD_MAX_WORDS


def generate_wordcloud(comments: list[dict]) -> str:
    """根据评论列表生成词云图，返回 base64 PNG"""
    all_text = " ".join(c.get("content", "") for c in comments if c.get("content"))
    if not all_text.strip():
        return ""

    # 分词并过滤停用词
    words = jieba.lcut(all_text)
    filtered = []
    for w in words:
        w = w.strip()
        if len(w) >= 2 and w not in STOPWORDS:
            filtered.append(w)

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
    all_text = " ".join(c.get("content", "") for c in comments if c.get("content"))
    words = jieba.lcut(all_text)
    filtered = [w.strip() for w in words if len(w.strip()) >= 2 and w.strip() not in STOPWORDS]
    counter = Counter(filtered)
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]
