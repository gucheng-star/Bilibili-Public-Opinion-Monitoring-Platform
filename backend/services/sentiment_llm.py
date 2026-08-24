"""LLM sentiment analysis using one main label, including sarcasm."""

import asyncio
import json
import logging
from collections.abc import Callable

from services.llm_client import chat_completion_json

EMOTION_LABELS = [
    "neutral", "joy", "support", "anticipation", "surprise",
    "anger", "sadness", "concern", "disgust", "sarcasm",
]
LLM_BATCH_SIZE = 5
LLM_BATCH_CONCURRENCY = 3
LLM_BATCH_RETRIES = 2
LLM_CONTEXT_COMMENT_MAX_CHARS = 240
LLM_DIAGNOSTIC_VALUE_MAX_CHARS = 80

logger = logging.getLogger(__name__)

FEW_SHOT_EXAMPLES = [
    {"text": "心脏每分钟七十次，换算下来大概就是这个量级。", "label": "neutral", "reason": "陈述或提问默认中性"},
    {"text": "讲得很清楚，感谢科普。", "label": "support", "reason": "明确认可和支持"},
    {"text": "笑死，这下知道为什么要少熬夜了。", "label": "joy", "reason": "轻松玩梗且带有愉悦"},
    {"text": "DNA 动了。", "label": "neutral", "reason": "含义不明确时归中性"},
    {"text": "对对对，所有问题都靠早睡解决，太科学了。", "label": "sarcasm", "reason": "主要表达方式是反讽"},
    {"text": "长期熬夜的人风险会更高吗？", "label": "concern", "reason": "担忧风险或后果"},
]

SYSTEM_PROMPT = """你是 B 站评论情感分析专家。对每条评论只输出一个主分类：
- label：neutral、joy、support、anticipation、surprise、anger、sadness、concern、disgust、sarcasm。

判定规则：
1. neutral 是默认值。事实陈述、普通提问、信息补充、含义不明确的短评均归 neutral。
2. support 仅用于明确认可、感谢、鼓励或支持；不要把无情感评论归为 support。
3. surprise 仅用于表达意外、震惊或出乎意料；“6”等梗若主要表达离谱或意外可为 surprise。
4. concern 用于担忧、风险、不安、焦虑；不要使用 fear。
5. sarcasm 用于以反话、阴阳怪气或表面赞同表达否定；当反讽是最显著特征时直接选择 sarcasm。
6. 当有上下文时，只用它理解指代、玩笑或反讽；只能标注当前评论自身的情感。
7. 只输出合法 JSON，不要额外文字。
"""


class LLMProtocolFailure(RuntimeError):
    """One or more comments still violate the bounded response protocol.

    Protocol failures are isolatable: unrelated comments may continue and be
    persisted.  Transport, authentication and rate-limit failures deliberately
    use their original exception types so callers can still stop immediately.
    """

    def __init__(self, messages: list[str]):
        self.messages = tuple(messages)
        super().__init__("；".join(messages))


def _diagnostic_value(value: object) -> str:
    """Serialize one bounded protocol value without logging prompts or secrets."""
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = f"<{type(value).__name__}>"
    if len(text) <= LLM_DIAGNOSTIC_VALUE_MAX_CHARS:
        return text
    return text[:LLM_DIAGNOSTIC_VALUE_MAX_CHARS] + "..."


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
            {"id": comment["id"], "label": example["label"], "confidence": 0.9}
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
    repair_instruction: str | None = None,
) -> dict[str, dict[str, str]]:
    """Classify one batch and return one validated main label per comment ID."""
    # Bilibili rpids are long external identifiers.  Asking a generative model
    # to copy them exactly is unnecessary and was a repeated source of otherwise
    # valid single-item batches failing protocol validation.  Keep the real
    # identifiers local and expose only short, deterministic per-batch handles.
    protocol_to_comment_id = {
        f"item-{index}": str(comment["rpid"])
        for index, comment in enumerate(comments, start=1)
    }
    expected_ids = set(protocol_to_comment_id)
    payload_comments = []
    for index, comment in enumerate(comments, start=1):
        comment_id = str(comment["rpid"])
        payload = {"id": f"item-{index}", "text": comment["content"].strip()}
        if contexts and contexts.get(comment_id):
            payload["context"] = contexts[comment_id]
        payload_comments.append(payload)
    batch_instruction = (
        "请独立分析以下每条评论。只返回一个合法 JSON 对象，格式必须为 "
        '{"items":[{"id":"评论ID","label":"neutral","confidence":0.0}]}。'
        "items 必须恰好包含输入中的每个 id 一次；label 只能是 neutral、joy、support、anticipation、"
        "surprise、anger、sadness、concern、disgust、sarcasm；"
        "不要输出 style、reason 或任何额外文字。\n"
        f"评论：{json.dumps(payload_comments, ensure_ascii=False)}"
    )
    batch_instruction += (
        "\nWhen an item includes context, use it only to resolve references, irony, or jokes. "
        "Classify the item's text only; never copy the context comment's emotion."
    )
    if repair_instruction:
        batch_instruction += f"\n{repair_instruction}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_build_few_shot_messages())
    messages.append({"role": "user", "content": batch_instruction})
    parsed = await _call_llm(messages, config, max_tokens=180)

    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise ValueError("模型返回格式不符合要求：缺少 items 数组")

    labels_by_protocol_id: dict[str, dict[str, str]] = {}
    for item in parsed["items"]:
        if not isinstance(item, dict):
            raise ValueError("模型返回格式不符合要求：items 中存在非对象条目")
        comment_id = str(item.get("id", ""))
        label = item.get("label")
        if comment_id not in expected_ids:
            raise ValueError("模型返回格式不符合要求：包含意外的批次条目 ID")
        if comment_id in labels_by_protocol_id:
            raise ValueError("模型返回格式不符合要求：包含重复的批次条目 ID")
        if label not in EMOTION_LABELS:
            logger.warning(
                "LLM sentiment protocol rejected label provider=%s model=%s "
                "batch_size=%d item_id=%s label=%s label_type=%s",
                _diagnostic_value(config.get("provider", "")),
                _diagnostic_value(config.get("model", "")),
                len(comments),
                _diagnostic_value(comment_id),
                _diagnostic_value(label),
                type(label).__name__,
            )
            raise ValueError("模型返回格式不符合要求：包含非法情感标签")
        # Keep the legacy database column stable without asking the model for
        # a second classification dimension. UI and filtering use label only.
        labels_by_protocol_id[comment_id] = {"label": label, "style": "plain"}

    missing_count = len(expected_ids - set(labels_by_protocol_id))
    if missing_count:
        raise ValueError(f"模型返回格式不符合要求：缺少 {missing_count} 条评论结果")
    return {
        protocol_to_comment_id[protocol_id]: result
        for protocol_id, result in labels_by_protocol_id.items()
    }


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
    repair_instruction: str | None = None
    for attempt in range(LLM_BATCH_RETRIES + 1):
        try:
            return await _analyze_comment_batch(
                comments,
                config,
                contexts,
                repair_instruction=repair_instruction,
            )
        except Exception as exc:
            last_error = exc
            if isinstance(exc, ValueError):
                repair_instruction = (
                    f"上一次返回未通过协议校验：{exc}。"
                    "请严格按照既定 items、id、label 约束重新输出完整 JSON。"
                )
            if attempt < LLM_BATCH_RETRIES:
                await asyncio.sleep(attempt + 1)
    raise RuntimeError(
        f"大模型批次连续 {LLM_BATCH_RETRIES + 1} 次失败：{last_error}"
    ) from last_error


async def _analyze_batch_with_fallback(
    comments: list[dict], config: dict[str, str], contexts: dict[str, dict[str, str]],
    on_success: Callable[[list[dict], dict[str, dict[str, str]]], None],
) -> dict[str, dict[str, str]]:
    """Retry a batch, then bisect it so one malformed reply does not waste good work.

    A provider can occasionally return a malformed multi-item response.  After
    the normal bounded retries fail, recursively split the batch.  Successful
    leaves are reported immediately; a persistently bad single comment remains
    an explicit, retryable failure instead of cancelling previously completed
    labels.
    """
    try:
        labels = await _analyze_batch_with_retry(comments, config, contexts)
    except Exception as exc:
        # Only malformed/invalid model responses benefit from smaller JSON
        # payloads.  Retrying a network, authentication, rate-limit, or
        # provider failure as multiple subrequests would increase cost and
        # pressure without improving the outcome.
        is_protocol_failure = isinstance(exc.__cause__, ValueError)
        if not is_protocol_failure:
            raise
        if len(comments) > 1 and is_protocol_failure:
            midpoint = len(comments) // 2
            labels: dict[str, dict[str, str]] = {}
            protocol_errors: list[str] = []
            # Run both halves even when one contains an isolated protocol
            # failure.  A non-protocol failure still propagates immediately,
            # avoiding extra provider requests during network/auth/rate limits.
            for half in (comments[:midpoint], comments[midpoint:]):
                try:
                    labels.update(
                        await _analyze_batch_with_fallback(half, config, contexts, on_success)
                    )
                except LLMProtocolFailure as protocol_error:
                    protocol_errors.extend(protocol_error.messages)
            if protocol_errors:
                raise LLMProtocolFailure(protocol_errors) from exc
            return labels
        comment_id = str(comments[0].get("rpid", "unknown"))
        protocol_detail = exc.__cause__ if isinstance(exc.__cause__, ValueError) else exc
        raise LLMProtocolFailure([
            f"评论 rpid={comment_id} 连续 {LLM_BATCH_RETRIES + 1} 次未能完成大模型协议校验："
            f"{protocol_detail}"
        ]) from exc
    on_success(comments, labels)
    return labels


async def batch_analyze_llm(
    comments: list[dict], config: dict[str, str], concurrency: int = LLM_BATCH_CONCURRENCY,
    progress_callback: Callable[[int], None] | None = None,
    context_comments: list[dict] | None = None,
) -> list[dict]:
    """Classify targets in batches while retaining optional same-video context."""
    comments_to_analyze = [
        comment for comment in comments if comment.get("content", "").strip()
    ]
    for comment in comments:
        if not comment.get("content", "").strip():
            comment["sentiment_llm_label"] = "neutral"
            comment["sentiment_llm_style"] = "plain"

    # Reanalysis can classify only unfinished targets.  Their root or direct
    # parent may already have a valid label, so use the full same-video pool
    # for context without turning those completed comments into model targets.
    contexts = _build_comment_contexts(context_comments if context_comments is not None else comments_to_analyze)
    batches = [comments[i:i + LLM_BATCH_SIZE] for i in range(0, len(comments), LLM_BATCH_SIZE)]
    semaphore = asyncio.Semaphore(concurrency)
    processed_comments = 0

    def complete_batch(batch: list[dict], labels: dict[str, dict[str, str]]) -> None:
        """Apply each validated sub-batch before reporting durable progress."""
        nonlocal processed_comments
        for comment in batch:
            result = labels.get(str(comment.get("rpid")))
            if result:
                comment["sentiment_llm_label"] = result["label"]
                comment["sentiment_llm_style"] = result["style"]
        processed_comments += len(batch)
        if progress_callback:
            progress_callback(processed_comments)

    async def _run_batch(batch: list[dict]) -> None:
        nonempty_batch = [comment for comment in batch if comment.get("content", "").strip()]
        empty_batch = [comment for comment in batch if not comment.get("content", "").strip()]
        if empty_batch:
            complete_batch(empty_batch, {})
        if not nonempty_batch:
            return
        async with semaphore:
            await _analyze_batch_with_fallback(nonempty_batch, config, contexts, complete_batch)

    batch_tasks = [asyncio.create_task(_run_batch(batch)) for batch in batches]
    protocol_errors: list[str] = []
    try:
        for completed_task in asyncio.as_completed(batch_tasks):
            try:
                await completed_task
            except LLMProtocolFailure as protocol_error:
                # Protocol failures are scoped to their isolated comments.
                # Other already-paid batches must be allowed to finish and
                # report their validated labels before the aggregate failure.
                protocol_errors.extend(protocol_error.messages)
    except Exception:
        for batch_task in batch_tasks:
            batch_task.cancel()
        await asyncio.gather(*batch_tasks, return_exceptions=True)
        raise
    if protocol_errors:
        raise LLMProtocolFailure(protocol_errors)
    for comment in comments_to_analyze:
        if comment.get("sentiment_llm_label") not in EMOTION_LABELS:
            raise RuntimeError(f"评论 rpid={comment.get('rpid', 'unknown')} 未返回合法大模型标签")
    return comments


def summarize_sentiment_llm(comments: list[dict]) -> dict:
    """统计包含反讽在内的十类主标签分布。"""
    counts = {label: 0 for label in EMOTION_LABELS}
    for c in comments:
        label = c.get("sentiment_llm_label", "neutral")
        if label in counts:
            counts[label] += 1
    return counts
