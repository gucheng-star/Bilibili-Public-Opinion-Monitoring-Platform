"""LLM sentiment analysis service using Alibaba Bailian Qwen (OpenAI-compatible)

Plutchik's 8 emotion categories: joy, anger, sadness, surprise, fear, disgust, anticipation, trust
"""

import json
import asyncio
import httpx

BAILIAN_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BAILIAN_MODEL = "qwen-plus"  # 升级到 plus：推理能力更强，成本几乎无感

# 模型回退策略：plus 不可用时自动降级到 turbo
BAILIAN_FALLBACK_MODEL = "qwen-turbo"

EIGHT_LABELS = ["joy", "anger", "sadness", "surprise", "fear", "disgust", "anticipation", "trust"]

# Plutchik 八情绪中文定义（帮助模型理解分类边界）
EMOTION_DESCRIPTIONS = """
joy（喜悦）       — 正向、开心、满足、喜爱、赞美。例如：好可爱、哈哈哈、爷青回、终于等到你
anger（愤怒）     — 强烈的负面情绪、攻击性。例如：真恶心、滚出去、脑残粉、什么垃圾玩意儿
sadness（悲伤）   — 失落、难过、遗憾、惋惜。例如：哭了、破防了、青春结束了、太难过了
surprise（惊讶）  — 出乎意料、震惊，可正向也可负向。例如：卧槽、这谁想得到、居然还有这种操作
fear（恐惧）      — 担忧、不安、害怕、对未来的焦虑。例如：感觉要出事了、别吓我、细思极恐
disgust（厌恶）   — 反感、不适、恶心但非愤怒。例如：生理不适了、太油了、炒热度吃相难看
anticipation（期待）— 期待、盼望、好奇接下来会发生什么。例如：下一期呢！期待！想看后续！
trust（信任）     — 表达信任、认可、支持、忠诚。例如：他说的对、老粉了、一直支持你、靠谱
"""

# B站语境 few-shot 示例：每类一条典型弹幕/评论
FEW_SHOT_EXAMPLES = [
    {"text": "好可爱啊啊啊啊awsl",               "label": "joy",          "reason": "强烈正向喜爱"},
    {"text": "什么垃圾玩意儿退钱",                "label": "anger",        "reason": "攻击性负面情绪"},
    {"text": "我的青春结束了呜呜",                "label": "sadness",      "reason": "失落感伤非愤怒"},
    {"text": "卧槽这波反转？？？",                "label": "surprise",     "reason": "意外震惊"},
    {"text": "细思极恐啊晚上不敢回看了",          "label": "fear",         "reason": "不安恐惧"},
    {"text": "生理不适了求求别播这种内容",        "label": "disgust",      "reason": "反感厌恶非愤怒"},
    {"text": "下周有糖！！等不及了啊啊啊",        "label": "anticipation", "reason": "期待盼望"},
    {"text": "老粉了，你推的我都去看",            "label": "trust",        "reason": "信任与忠诚"},
    # B站特有反语/梗
    {"text": "笑死我了这波操作哈哈哈",            "label": "joy",          "reason": "开心被逗笑"},
    {"text": "就这？就这？就这？",                "label": "disgust",      "reason": "轻蔑不适非愤怒"},
    {"text": "6",                                 "label": "surprise",     "reason": "B站6表示离谱/震惊"},
    {"text": "典",                                "label": "disgust",      "reason": "B站典=典中典，讽刺居高临下感"},
    {"text": "急了急了急了",                      "label": "anger",        "reason": "嘲讽对方破防发怒"},
    {"text": "泪目",                              "label": "sadness",      "reason": "感动落泪，偏悲伤"},
]

SYSTEM_PROMPT = f"""你是B站弹幕评论情感分析专家。分析给定评论，从以下8种情绪中选择最匹配的标签。

{EMOTION_DESCRIPTIONS}

重要规则：
- B站评论常含反语、玩梗、缩写（如"笑死"是开心不是悲伤，"6"表示离谱/震惊，"典"表示讽刺厌恶）
- 有多个情绪时选最强烈那个
- 仅输出合法 JSON，不要任何额外文字
- confidence 表示你对分类把握的自信度（0.0-1.0）"""


def _build_few_shot_messages():
    """构造 few-shot 示例消息"""
    messages = []
    for ex in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": ex["text"]})
        messages.append({"role": "assistant", "content": json.dumps({
            "label": ex["label"],
            "confidence": 0.9,
            "reason": ex["reason"],
        }, ensure_ascii=False)})
    return messages


async def _call_llm(messages: list[dict], api_key: str, temperature: float = 0.1) -> dict | None:
    """调用百炼 API，自动尝试 plus → turbo 降级"""
    models_to_try = [BAILIAN_MODEL, BAILIAN_FALLBACK_MODEL] if BAILIAN_MODEL != BAILIAN_FALLBACK_MODEL else [BAILIAN_MODEL]

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 80,
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
                # 尝试解析 JSON，可能被 markdown 代码块包裹
                if content.startswith("```"):
                    content = content.split("\n", 1)[1]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    # 去掉可能的 json 语言标识
                    if content.startswith("json"):
                        content = content[4:].strip()
                parsed = json.loads(content)
                return parsed
        except Exception:
            continue
    return None


async def analyze_sentiment_llm(text: str, api_key: str) -> dict:
    """调用百炼 API 分析单条评论。返回 {"label": str, "confidence": float, "reason": str}。"""
    if not text or not text.strip():
        return {"label": "neutral", "confidence": 0.5}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    messages.extend(_build_few_shot_messages())
    messages.append({"role": "user", "content": text})

    try:
        parsed = await _call_llm(messages, api_key)
        if parsed is None:
            return {"label": "neutral", "confidence": 0.5}

        label = parsed.get("label", "neutral")
        confidence = float(parsed.get("confidence", 0.5))
        if label not in EIGHT_LABELS:
            label = "neutral"
        return {"label": label, "confidence": round(confidence, 4)}
    except Exception:
        return {"label": "neutral", "confidence": 0.5}


async def batch_analyze_llm(comments: list[dict], api_key: str, concurrency: int = 3) -> list[dict]:
    """批量分析评论（并发控制，避免触发 API 限流）。

    Args:
        comments: 评论列表，每条包含 content 字段
        api_key: 百炼 API Key
        concurrency: 最大并发数（默认3，防止限流）
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _analyze_with_limit(c: dict) -> dict:
        async with semaphore:
            llm_result = await analyze_sentiment_llm(c.get("content", ""), api_key)
            c["sentiment_llm_label"] = llm_result["label"]
            return c

    tasks = [_analyze_with_limit(c) for c in comments]
    return await asyncio.gather(*tasks)


def summarize_sentiment_llm(comments: list[dict]) -> dict:
    """统计 8 分类分布。"""
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
