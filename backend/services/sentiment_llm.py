"""LLM sentiment analysis using main emotion plus Bilibili expression style."""

import asyncio
import json

from services.llm_client import chat_completion_json

EMOTION_LABELS = [
    "neutral", "joy", "support", "anticipation", "surprise",
    "anger", "sadness", "concern", "disgust",
]
STYLE_LABELS = ["plain", "meme", "sarcasm"]
LLM_BATCH_SIZE = 5
LLM_BATCH_CONCURRENCY = 3
LLM_BATCH_RETRIES = 2
LLM_CONTEXT_COMMENT_MAX_CHARS = 240

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


FEW_SHOT_EXAMPLES = [
    {"text": "心脏每分钟七十次，换算下来大概就是这个量级。", "label": "neutral", "style": "plain", "reason": "陈述或提问默认中性"},
    {"text": "讲得很清楚，感谢科普。", "label": "support", "style": "plain", "reason": "明确认可和支持"},
    {"text": "笑死，这下知道为什么要少熬夜了。", "label": "joy", "style": "meme", "reason": "轻松玩梗且带有愉悦"},
    {"text": "DNA 动了。", "label": "neutral", "style": "meme", "reason": "玩梗本身不等于主情感"},
    {"text": "对对对，所有问题都靠早睡解决，太科学了。", "label": "anger", "style": "sarcasm", "reason": "反讽表达不满"},
    {"text": "长期熬夜的人风险会更高吗？", "label": "concern", "style": "plain", "reason": "担忧风险或后果"},
]

SYSTEM_PROMPT = """你是 B 站评论情感分析专家。对每条评论输出两项：
- label（主情感）：neutral、joy、support、anticipation、surprise、anger、sadness、concern、disgust。
- style（表达方式）：plain、meme、sarcasm。

判定规则：
1. neutral 是默认值。事实陈述、普通提问、信息补充、含义不明确的短评均归 neutral。
2. support 仅用于明确认可、感谢、鼓励或支持；不要把无情感评论归为 support。
3. surprise 仅用于表达意外、震惊或出乎意料；“6”等梗若主要表达离谱/意外可为 surprise + meme。
4. concern 用于担忧、风险、不安、焦虑；不要使用 fear。
5. meme 与 sarcasm 是表达方式，不是主情感。玩梗但没有明确情感时使用 neutral + meme；反讽时按真实意图选择主情感，无法确定则 neutral + sarcasm。
6. 当有上下文时，只用它理解指代、玩笑或反讽；只能标注当前评论自身的情感。
7. 只输出合法 JSON，不要额外文字。
"""


def _build_few_shot_messages():
    """构造 few-shot 示例消息"""
    messages = []
    for ex in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": ex["text"]})
        messages.append({"role": "assistant", "content": json.dumps({
            "label": ex["label"],
            "style": ex.get("style", "plain"),
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


def _truncate_context(text: str) -> str:
    text = text.strip()
    if len(text) <= LLM_CONTEXT_COMMENT_MAX_CHARS:
        return text
    return text[:LLM_CONTEXT_COMMENT_MAX_CHARS] + "..."


def _build_comment_contexts(comments: list[dict]) -> dict[str, dict[str, str]]:
    """Build root and direct-parent context without including descendant replies."""
    comments_by_id = {str(comment.get("rpid")): comment for comment in comments}
    contexts: dict[str, dict[str, str]] = {}
    for comment in comments:
        comment_id = str(comment.get("rpid"))
        root_id = str(comment.get("root_rpid") or "")
        parent_id = str(comment.get("parent_rpid") or "")
        context: dict[str, str] = {}

        root_comment = comments_by_id.get(root_id)
        if root_comment and root_id != comment_id:
            root_text = _truncate_context(str(root_comment.get("content") or ""))
            if root_text:
                context["root_comment"] = root_text

        parent_comment = comments_by_id.get(parent_id)
        if parent_comment and parent_id not in {comment_id, root_id}:
            parent_text = _truncate_context(str(parent_comment.get("content") or ""))
            if parent_text:
                context["parent_comment"] = parent_text

        if context:
            contexts[comment_id] = context
    return contexts


async def _analyze_comment_batch(
    comments: list[dict], config: dict[str, str], contexts: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    """Classify one batch and return validated emotion and expression style by ID."""
    expected_ids = {str(comment["rpid"]) for comment in comments}
    payload_comments = []
    for comment in comments:
        comment_id = str(comment["rpid"])
        payload = {"id": comment_id, "text": comment["content"].strip()}
        if contexts and contexts.get(comment_id):
            payload["context"] = contexts[comment_id]
        payload_comments.append(payload)
    batch_instruction = (
        "请独立分析以下每条评论。只返回一个合法 JSON 对象，格式必须为 "
        '{"items":[{"id":"评论ID","label":"neutral","style":"plain","confidence":0.0}]}。'
        "items 必须恰好包含输入中的每个 id 一次；label 只能是 neutral、joy、support、anticipation、"
        "surprise、anger、sadness、concern、disgust；style 只能是 plain、meme、sarcasm；"
        "不要输出 reason 或任何额外文字。\n"
        f"评论：{json.dumps(payload_comments, ensure_ascii=False)}"
    )
    batch_instruction += (
        "\nWhen an item includes context, use it only to resolve references, irony, or jokes. "
        "Classify the item's text only; never copy the context comment's emotion."
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_build_few_shot_messages())
    messages.append({"role": "user", "content": batch_instruction})
    parsed = await _call_llm(messages, config, max_tokens=180)

    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise ValueError("LLM response does not contain an items array")

    labels_by_id: dict[str, dict[str, str]] = {}
    for item in parsed["items"]:
        if not isinstance(item, dict):
            raise ValueError("LLM response contains an invalid item")
        comment_id = str(item.get("id", ""))
        label = item.get("label")
        style = item.get("style")
        if (
            comment_id not in expected_ids
            or label not in EMOTION_LABELS
            or style not in STYLE_LABELS
            or comment_id in labels_by_id
        ):
            raise ValueError("LLM response contains an invalid, duplicate, or unexpected item")
        labels_by_id[comment_id] = {"label": label, "style": style}

    if set(labels_by_id) != expected_ids:
        raise ValueError("LLM response is missing one or more comment results")
    return labels_by_id


async def test_sentiment_connection(config: dict[str, str]) -> int:
    """Exercise the real structured sentiment path with harmless samples."""
    labels = await _analyze_comment_batch(
        [
            {"rpid": "connection-positive", "content": "讲得很好，期待下一期"},
            {"rpid": "connection-negative", "content": "完全看不懂，太失望了"},
        ],
        config,
    )
    return len(labels)


async def _analyze_batch_with_retry(
    comments: list[dict], config: dict[str, str], contexts: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Retry only the failed batch so valid completed batches are preserved."""
    last_error: Exception | None = None
    for attempt in range(LLM_BATCH_RETRIES + 1):
        try:
            return await _analyze_comment_batch(comments, config, contexts)
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
            comment["sentiment_llm_style"] = "plain"

    contexts = _build_comment_contexts(comments_to_analyze)
    batches = [comments_to_analyze[i:i + LLM_BATCH_SIZE] for i in range(0, len(comments_to_analyze), LLM_BATCH_SIZE)]
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_batch(batch: list[dict]) -> dict[str, dict[str, str]]:
        async with semaphore:
            return await _analyze_batch_with_retry(batch, config, contexts)

    batch_results = await asyncio.gather(*[_run_batch(batch) for batch in batches])
    labels_by_id = {comment_id: value for result in batch_results for comment_id, value in result.items()}
    for comment in comments_to_analyze:
        result = labels_by_id[str(comment["rpid"])]
        comment["sentiment_llm_label"] = result["label"]
        comment["sentiment_llm_style"] = result["style"]
    return comments


def summarize_sentiment_llm(comments: list[dict]) -> dict:
    """统计九类主情感分布；表达方式单独保存在评论记录中。"""
    counts = {label: 0 for label in EMOTION_LABELS}
    for c in comments:
        label = c.get("sentiment_llm_label", "neutral")
        if label in counts:
            counts[label] += 1
    return counts
