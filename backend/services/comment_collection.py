"""Stable, privacy-safe contracts for a single comment collection attempt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence


COMMENT_COLLECTION_PENDING = "pending"
COMMENT_COLLECTION_FETCHING = "fetching"
COMMENT_COLLECTION_COMPLETED = "completed"
COMMENT_COLLECTION_PARTIAL = "partial"
COMMENT_COLLECTION_FAILED = "failed"


SAFE_COMMENT_COLLECTION_ERRORS = {
    "request_failed": "评论获取受限，已保存部分结果，可重新采集",
    "http_error": "评论获取受限，已保存部分结果，可重新采集",
    "platform_error": "评论获取受限，已保存部分结果，可重新采集",
    "invalid_response": "评论获取受限，已保存部分结果，可重新采集",
    "source_exhausted": "评论获取未完成，已保存部分结果，可重新采集",
    "page_limit": "评论获取未完成，已保存部分结果，可重新采集",
}


def safe_comment_collection_error(reason: str | None, fetched_count: int) -> str | None:
    """Return a fixed user-facing summary, never a platform or request payload."""
    if reason in {None, "target_reached"}:
        return None
    if fetched_count <= 0:
        return "评论获取失败，可重新采集"
    return SAFE_COMMENT_COLLECTION_ERRORS.get(reason, "评论获取未完成，已保存部分结果，可重新采集")


@dataclass(eq=False)
class CommentCollectionResult(Sequence[dict]):
    """The terminal result of one collection attempt.

    Sequence compatibility keeps existing callers working while later phases
    persist and present collection fields independently from NLP/LLM state.
    """

    comments: list[dict]
    target_count: int
    collection_status: str
    termination_reason: str
    error_summary: str | None = None

    @property
    def fetched_count(self) -> int:
        return len(self.comments)

    def __len__(self) -> int:
        return len(self.comments)

    def __getitem__(self, index):
        return self.comments[index]

    def __iter__(self) -> Iterator[dict]:
        return iter(self.comments)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CommentCollectionResult):
            return (
                self.comments == other.comments
                and self.target_count == other.target_count
                and self.collection_status == other.collection_status
                and self.termination_reason == other.termination_reason
                and self.error_summary == other.error_summary
            )
        return self.comments == other
