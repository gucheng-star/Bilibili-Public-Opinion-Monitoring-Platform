"""Derived comment-quality annotations and exact-duplicate filtering."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any


DUPLICATE_MODES = {"include", "deduplicate", "exclude_groups"}


def _stable_integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 2**63 - 1


def _post_time_key(value: Any) -> tuple[int, str]:
    if isinstance(value, datetime):
        return (0, value.isoformat())
    if isinstance(value, str) and value:
        return (0, value)
    return (1, "")


def _canonical_key(comment: dict[str, Any]) -> tuple[Any, ...]:
    return (
        *_post_time_key(comment.get("post_time")),
        _stable_integer(comment.get("rpid")),
        _stable_integer(comment.get("id")),
    )


def annotate_exact_duplicates(
    comments: list[dict[str, Any]], scope_field: str | None = None,
) -> list[dict[str, Any]]:
    """Return copied comments annotated from exact, non-empty content matches.

    ``scope_field`` isolates groups for an aggregate view.  This preserves the
    existing single-analysis hash contract while preventing identical wording
    under different source videos from being treated as one duplicate group.
    """
    annotated = [dict(comment) for comment in comments]
    groups: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
    for comment in annotated:
        content = comment.get("content")
        if isinstance(content, str) and content != "":
            scope = comment.get(scope_field) if scope_field else None
            groups[(scope, content)].append(comment)

    for comment in annotated:
        comment.update({
            "is_exact_duplicate": False,
            "duplicate_group_size": 1,
            "duplicate_group_key": None,
            "is_duplicate_canonical": False,
        })

    for (scope, content), members in groups.items():
        if len(members) < 2:
            continue
        canonical = min(members, key=_canonical_key)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        group_key = (
            f"source:{scope}:sha256:{content_hash}"
            if scope_field else f"sha256:{content_hash}"
        )
        for member in members:
            member.update({
                "is_exact_duplicate": True,
                "duplicate_group_size": len(members),
                "duplicate_group_key": group_key,
                "is_duplicate_canonical": member is canonical,
            })
    return annotated


def apply_duplicate_mode(
    comments: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    if mode not in DUPLICATE_MODES:
        raise ValueError("无效的重复内容筛选条件")
    annotated = (
        comments
        if all("is_exact_duplicate" in comment for comment in comments)
        else annotate_exact_duplicates(comments)
    )
    if mode == "include":
        return list(annotated)
    if mode == "deduplicate":
        return [
            comment for comment in annotated
            if not comment["is_exact_duplicate"] or comment["is_duplicate_canonical"]
        ]
    return [comment for comment in annotated if not comment["is_exact_duplicate"]]


def build_duplicate_statistics(comments: list[dict[str, Any]]) -> dict[str, int | float]:
    annotated = (
        comments
        if all("is_exact_duplicate" in comment for comment in comments)
        else annotate_exact_duplicates(comments)
    )
    duplicate_members = [comment for comment in annotated if comment["is_exact_duplicate"]]
    group_keys = {comment["duplicate_group_key"] for comment in duplicate_members}
    involved = len(duplicate_members)
    group_count = len(group_keys)
    total = len(annotated)
    return {
        "group_count": group_count,
        "involved_comments": involved,
        "duplicate_excess": involved - group_count,
        "involved_ratio": involved / total if total else 0.0,
    }
