"""应用配置"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# B站 API 配置
BILIBILI_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
BILIBILI_REFERER = "https://www.bilibili.com"

# 抓取配置
MAX_COMMENTS = 100
REQUEST_DELAY = 3.0

def _load_stopwords() -> set[str]:
    """从项目根目录的 stopwords.txt 加载停用词"""
    import os
    stopwords_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stopwords.txt")
    stopwords = set()
    if os.path.exists(stopwords_path):
        with open(stopwords_path, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word:
                    stopwords.add(word)
    return stopwords

STOPWORDS = _load_stopwords()
BILIBILI_COOKIE = ""  # No longer hardcoded; see services/auth.py
