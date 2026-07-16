"""情感分析服务 —— 基于 SnowNLP"""

from snownlp import SnowNLP


def analyze_sentiment(text: str) -> tuple[str, float]:
    """分析单条文本的情感，返回 (标签, 分数)"""
    if not text or not text.strip():
        return ("neutral", 0.5)
    try:
        s = SnowNLP(text)
        score = s.sentiments
    except Exception:
        return ("neutral", 0.5)

    if score > 0.6:
        return ("positive", round(score, 4))
    elif score < 0.4:
        return ("negative", round(score, 4))
    else:
        return ("neutral", round(score, 4))


def batch_analyze(comments: list[dict]) -> list[dict]:
    """批量分析评论情感"""
    results = []
    for c in comments:
        label, score = analyze_sentiment(c.get("content", ""))
        c["sentiment_label"] = label
        c["sentiment_score"] = score
        results.append(c)
    return results


def summarize_sentiment(comments: list[dict]) -> dict:
    """汇总情感统计"""
    positive = sum(1 for c in comments if c.get("sentiment_label") == "positive")
    negative = sum(1 for c in comments if c.get("sentiment_label") == "negative")
    neutral = sum(1 for c in comments if c.get("sentiment_label") == "neutral")
    return {
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "total": len(comments),
    }
