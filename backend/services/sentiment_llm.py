"""LLM sentiment analysis using main emotion plus Bilibili expression style."""

import asyncio
import json
from collections.abc import Callable

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
    """Build few-shot examples with the same batched ``items`` protocol."""
    messages = []
    for batch_index in range(0, len(FEW_SHOT_EXAMPLES), LLM_BATCH_SIZE):
        batch = FEW_SHOT_EXAMPLES[batch_index:batch_index + LLM_BATCH_SIZE]
        comments = [
            {"id": f"example-{batch_index + index + 1}", "text": example["text"]}
            for index, example in enumerate(batch)
        ]
        items = [
            {"id": comment["id"], "label": example["label"],
             "style": example.get("style", "plain"), "confidence": 0.9}
            for comment, example in zip(comments, batch)
        ]
        messages.append({"role": "user", "content": json.dumps({"comments": comments}, ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps({"items": items}, ensure_ascii=False)})
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
    progress_callback: Callable[[int], None] | None = None,
) -> list[dict]:
    """Classify at most five comments per request and report completed comments."""
    comments_to_analyze = [
        comment for comment in comments if comment.get("content", "").strip()
    ]
    for comment in comments:
        if not comment.get("content", "").strip():
            comment["sentiment_llm_label"] = "neutral"
            comment["sentiment_llm_style"] = "plain"

    contexts = _build_comment_contexts(comments_to_analyze)
    batches = [comments[i:i + LLM_BATCH_SIZE] for i in range(0, len(comments), LLM_BATCH_SIZE)]
    semaphore = asyncio.Semaphore(concurrency)
    processed_comments = 0

    async def _run_batch(batch: list[dict]) -> tuple[dict[str, dict[str, str]], int]:
        nonempty_batch = [comment for comment in batch if comment.get("content", "").strip()]
        if not nonempty_batch:
            return {}, len(batch)
        async with semaphore:
            return await _analyze_batch_with_retry(nonempty_batch, config, contexts), len(batch)

    batch_tasks = [asyncio.create_task(_run_batch(batch)) for batch in batches]
    labels_by_id = {}
    try:
        for completed_task in asyncio.as_completed(batch_tasks):
            result, completed_count = await completed_task
            labels_by_id.update(result)
            processed_comments += completed_count
            if progress_callback:
                progress_callback(processed_comments)
    except Exception:
        for batch_task in batch_tasks:
            batch_task.cancel()
        await asyncio.gather(*batch_tasks, return_exceptions=True)
        raise
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
