"""应用配置"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(BASE_DIR, 'data.db')}"

# B站 API 配置
BILIBILI_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
BILIBILI_REFERER = "https://www.bilibili.com"

# 抓取配置
MAX_COMMENTS = 1000
REQUEST_DELAY = 0.6

# 词云配置
WORDCLOUD_WIDTH = 800
WORDCLOUD_HEIGHT = 400
WORDCLOUD_MAX_WORDS = 100

STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "如果", "因为", "所以", "但是", "然后", "可以", "还是",
    "这个", "那个", "已经", "知道", "觉得", "感觉", "真的", "就是", "不是",
    "还有", "不过", "而且", "之后", "的话", "现在", "应该", "可能", "一点",
    "up", "up主", "视频", "弹幕", "哈哈", "哈哈哈", "确实", "卧槽", "牛逼",
    "666", "6666", "打卡", "第一", "前排", "来了", "来啦",
}
