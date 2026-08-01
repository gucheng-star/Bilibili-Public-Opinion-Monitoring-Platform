"""LLM sentiment analysis service using a configured OpenAI-compatible provider.

Plutchik's 8 emotion categories: joy, anger, sadness, surprise, fear, disgust, anticipation, trust
"""

import asyncio
import json

from services.llm_client import chat_completion_json

EIGHT_LABELS = ["joy", "anger", "sadness", "surprise", "fear", "disgust", "anticipation", "trust"]
LLM_BATCH_SIZE = 5
LLM_BATCH_CONCURRENCY = 3
LLM_BATCH_RETRIES = 2

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


async def _call_llm(
    messages: list[dict],
    config: dict[str, str],
    temperature: float = 0.1,
    max_tokens: int = 80,
) -> dict:
    """Call the configured provider and parse a JSON response."""
    parsed, _ = await chat_completion_json(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parsed


async def _analyze_comment_batch(comments: list[dict], config: dict[str, str]) -> dict[str, str]:
    """Classify one batch and return a validated map of comment ID to label."""
    expected_ids = {str(comment["rpid"]) for comment in comments}
    payload_comments = [
        {"id": str(comment["rpid"]), "text": comment["content"].strip()}
        for comment in comments
    ]
    batch_instruction = (
        "请独立分析以下每条评论。只返回一个合法 JSON 对象，格式必须为 "
        '{"items":[{"id":"评论ID","label":"joy","confidence":0.0}]}。'
        "items 必须恰好包含输入中的每个 id 一次；label 只能是 joy、anger、sadness、"
        "surprise、fear、disgust、anticipation、trust；不要输出 reason 或任何额外文字。\n"
        f"评论：{json.dumps(payload_comments, ensure_ascii=False)}"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_build_few_shot_messages())
    messages.append({"role": "user", "content": batch_instruction})
    parsed = await _call_llm(messages, config, max_tokens=180)

    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise ValueError("LLM response does not contain an items array")

    labels_by_id: dict[str, str] = {}
    for item in parsed["items"]:
        if not isinstance(item, dict):
            raise ValueError("LLM response contains an invalid item")
        comment_id = str(item.get("id", ""))
        label = item.get("label")
        if comment_id not in expected_ids or label not in EIGHT_LABELS or comment_id in labels_by_id:
            raise ValueError("LLM response contains an invalid, duplicate, or unexpected item")
        labels_by_id[comment_id] = label

    if set(labels_by_id) != expected_ids:
        raise ValueError("LLM response is missing one or more comment results")
    return labels_by_id


async def _analyze_batch_with_retry(comments: list[dict], config: dict[str, str]) -> dict[str, str]:
    """Retry only the failed batch so valid completed batches are preserved."""
    last_error: Exception | None = None
    for attempt in range(LLM_BATCH_RETRIES + 1):
        try:
            return await _analyze_comment_batch(comments, config)
        except Exception as exc:
            last_error = exc
            if attempt < LLM_BATCH_RETRIES:
                await asyncio.sleep(attempt + 1)
    raise RuntimeError(f"LLM batch failed after {LLM_BATCH_RETRIES + 1} attempts: {last_error}")


async def batch_analyze_llm(
    comments: list[dict], config: dict[str, str], concurrency: int = LLM_BATCH_CONCURRENCY,
) -> list[dict]:
    """Classify five comments per request, with limited concurrent batches."""
    comments_to_analyze = []
    for comment in comments:
        if comment.get("content", "").strip():
            comments_to_analyze.append(comment)
        else:
            comment["sentiment_llm_label"] = "neutral"

    batches = [comments_to_analyze[i:i + LLM_BATCH_SIZE] for i in range(0, len(comments_to_analyze), LLM_BATCH_SIZE)]
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_batch(batch: list[dict]) -> dict[str, str]:
        async with semaphore:
            return await _analyze_batch_with_retry(batch, config)

    batch_results = await asyncio.gather(*[_run_batch(batch) for batch in batches])
    labels_by_id = {comment_id: label for result in batch_results for comment_id, label in result.items()}
    for comment in comments_to_analyze:
        comment["sentiment_llm_label"] = labels_by_id[str(comment["rpid"])]
    return comments


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
