"""LLM sentiment analysis service using Alibaba Bailian Qwen (OpenAI-compatible)

Plutchik's 8 emotion categories: joy, anger, sadness, surprise, fear, disgust, anticipation, trust
"""

import json
import httpx

BAILIAN_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BAILIAN_MODEL = "qwen-turbo"

EIGHT_LABELS = ["joy", "anger", "sadness", "surprise", "fear", "disgust", "anticipation", "trust"]

SYSTEM_PROMPT = (
    'You are an emotion analysis expert. Analyze the comment and choose the best '
    'matching emotion label. Only choose from: joy, anger, sadness, surprise, fear, '
    'disgust, anticipation, trust. Reply with JSON only: '
    '{"label": "joy", "confidence": 0.95}'
)


async def analyze_sentiment_llm(text: str, api_key: str) -> dict:
    """Call Bailian API to analyze a single comment. Returns {"label": str, "confidence": float}."""
    if not text or not text.strip():
        return {"label": "neutral", "confidence": 0.5}

    payload = {
        "model": BAILIAN_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 50,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BAILIAN_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            parsed = json.loads(content)
            label = parsed.get("label", "neutral")
            confidence = float(parsed.get("confidence", 0.5))
            if label not in EIGHT_LABELS:
                label = "neutral"
            return {"label": label, "confidence": round(confidence, 4)}
    except Exception:
        return {"label": "neutral", "confidence": 0.5}


async def batch_analyze_llm(comments: list[dict], api_key: str) -> list[dict]:
    """Batch analyze comments one by one via LLM API."""
    results = []
    for c in comments:
        llm_result = await analyze_sentiment_llm(c.get("content", ""), api_key)
        c["sentiment_llm_label"] = llm_result["label"]
        results.append(c)
    return results


def summarize_sentiment_llm(comments: list[dict]) -> dict:
    """Count 8-category distribution."""
    counts = {label: 0 for label in EIGHT_LABELS}
    for c in comments:
        label = c.get("sentiment_llm_label", "neutral")
        if label in counts:
            counts[label] += 1
    return {
        "joy": counts["joy"],
        "anger": counts["anger"],
        "sadness": counts["sadness"],
        "surprise": counts["surprise"],
        "fear": counts["fear"],
        "disgust": counts["disgust"],
        "anticipation": counts["anticipation"],
        "trust": counts["trust"],
    }
