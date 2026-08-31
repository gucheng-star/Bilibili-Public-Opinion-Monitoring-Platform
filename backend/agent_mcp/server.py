"""Local stdio MCP server exposing three bounded, read-only analysis tools."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_mcp.contracts import (  # noqa: E402
    AnalysisListOutput,
    AnalysisOverviewOutput,
    CommentSearchOutput,
)
from agent_mcp.read_only_service import AgentReadOnlyError, ReadOnlyService  # noqa: E402


Mode = Literal["nlp", "llm"]
OutputModel = TypeVar("OutputModel", bound=BaseModel)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)


class SafeToolInputMiddleware:
    """Reject malformed tool input without echoing attacker-controlled values."""

    _allowed = {
        "bili_list_analyses": {"limit", "offset", "status"},
        "bili_get_analysis_overview": {"analysis_id", "mode"},
        "bili_search_comments": {"analysis_id", "mode", "keyword", "sentiment", "limit", "offset"},
    }

    @staticmethod
    def _value(source: Any, name: str, default: Any = None) -> Any:
        return source.get(name, default) if isinstance(source, dict) else getattr(source, name, default)

    @staticmethod
    def _valid(arguments: dict[str, Any], name: str) -> bool:
        if name != "bili_list_analyses":
            value = arguments.get("analysis_id")
            if type(value) is not int or value <= 0:
                return False
        if "limit" in arguments:
            value = arguments["limit"]
            if type(value) is not int or not 1 <= value <= 50:
                return False
        if "offset" in arguments:
            value = arguments["offset"]
            if type(value) is not int or not 0 <= value <= 100_000:
                return False
        if "mode" in arguments:
            value = arguments["mode"]
            if type(value) is not str or value not in {"nlp", "llm"}:
                return False
        if "status" in arguments and arguments["status"] != "done":
            return False
        for field, maximum in (("keyword", 100), ("sentiment", 30)):
            if field in arguments and arguments[field] is not None:
                value = arguments[field]
                if not isinstance(value, str) or len(value) > maximum:
                    return False
        return True

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        params = ctx.params
        name = self._value(params, "name")
        if name not in self._allowed:
            return CallToolResult(
                content=[TextContent(type="text", text="工具名称不合法，请从 tools/list 返回的工具中选择。")],
                is_error=True,
            )
        arguments = self._value(params, "arguments", {}) or {}
        if (
            not isinstance(arguments, dict)
            or not set(arguments) <= self._allowed[name]
            or not self._valid(arguments, name)
        ):
            return CallToolResult(
                content=[TextContent(type="text", text="工具参数不合法，请按照输入 Schema 修正后重试。")],
                is_error=True,
            )
        return await call_next(ctx)


mcp = MCPServer(
    "B站舆论监测只读校验",
    version="0.1.0",
    instructions=(
        "阶段 A 只读技术校验：仅可读取用户明确指定的 SQLite 数据库副本。"
        "不会抓取视频、调用大模型、修改业务数据或监听网络端口。"
    ),
    log_level="WARNING",
    middleware=[SafeToolInputMiddleware()],
)

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _service() -> ReadOnlyService:
    configured = os.getenv("BILI_MCP_DB_PATH", "").strip()
    if not configured:
        raise ToolError("未配置 BILI_MCP_DB_PATH，请将它指向经确认的 SQLite 数据库副本。")
    try:
        return ReadOnlyService(configured)
    except AgentReadOnlyError as exc:
        raise ToolError(exc.message) from None


def _call(operation):
    try:
        return operation(_service())
    except AgentReadOnlyError as exc:
        raise ToolError(exc.message) from None


def _result(text: str, payload: OutputModel) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload.model_dump(mode="json"),
    )


@mcp.tool(
    title="列出已完成分析",
    description="分页列出本机数据库副本中可供 Agent 选择的已完成单视频分析记录。",
    annotations=READ_ONLY_ANNOTATIONS,
)
def bili_list_analyses(
    limit: Annotated[int, Field(ge=1, le=50, description="每页记录数，范围 1 至 50")] = 20,
    offset: Annotated[int, Field(ge=0, le=100_000, description="从第几条记录开始，范围 0 至 100000")] = 0,
    status: Literal["done"] = "done",
) -> Annotated[CallToolResult, AnalysisListOutput]:
    """列出已完成分析；阶段 A 的 status 固定为 done。"""
    del status
    payload = AnalysisListOutput.model_validate(
        _call(lambda service: service.list_analyses(limit=limit, offset=offset))
    )
    text = f"共有 {payload.total_count} 条已完成分析，本页返回 {len(payload.items)} 条。"
    if payload.has_more:
        text += " 后续仍有记录，可增加 offset 继续读取。"
    return _result(text, payload)


@mcp.tool(
    title="读取分析概览",
    description="读取一条已完成分析的情绪、时间、地域和精确重复内容统计。",
    annotations=READ_ONLY_ANNOTATIONS,
)
def bili_get_analysis_overview(
    analysis_id: Annotated[int, Field(gt=0, description="已完成分析记录的正整数 ID")],
    mode: Mode = "nlp",
) -> Annotated[CallToolResult, AnalysisOverviewOutput]:
    """读取单条分析的可核对概览，不接受完整前端筛选器。"""
    payload = AnalysisOverviewOutput.model_validate(
        _call(lambda service: service.get_analysis_overview(analysis_id=analysis_id, mode=mode))
    )
    main_label = max(
        payload.sentiment_distribution.model_dump(),
        key=payload.sentiment_distribution.model_dump().get,
        default="无",
    )
    text = (
        f"分析 {payload.analysis_id}（{payload.video_title}）按 {payload.mode.upper()} 口径统计；"
        f"情绪分母为 {payload.sentiment_denominator}，数量最多的标签是 {main_label}。"
    )
    if not payload.data_complete:
        text += " 数据存在完整性限制，请查看 limitations。"
    return _result(text, payload)


@mcp.tool(
    title="检索评论证据",
    description="在一条已完成分析中按原文包含关系或情绪检索有限、裁剪后的评论证据。",
    annotations=READ_ONLY_ANNOTATIONS,
)
def bili_search_comments(
    analysis_id: Annotated[int, Field(gt=0, description="已完成分析记录的正整数 ID")],
    mode: Mode = "nlp",
    keyword: Annotated[str | None, Field(max_length=100, description="可选原文关键词；空值表示不限")] = None,
    sentiment: Annotated[str | None, Field(max_length=30, description="可选情绪标签，必须符合当前 mode")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="每页评论数，范围 1 至 50")] = 20,
    offset: Annotated[int, Field(ge=0, le=100_000, description="从第几条匹配评论开始，范围 0 至 100000")] = 0,
) -> Annotated[CallToolResult, CommentSearchOutput]:
    """检索评论证据；不返回用户名、UID、评论 ID 或上下文正文。"""
    payload = CommentSearchOutput.model_validate(
        _call(
            lambda service: service.search_comments(
                analysis_id=analysis_id,
                mode=mode,
                keyword=keyword,
                sentiment=sentiment,
                limit=limit,
                offset=offset,
            )
        )
    )
    text = f"匹配 {payload.matched_count} 条评论，本页安全返回 {payload.returned_count} 条证据。"
    if payload.has_more:
        text += " 后续仍有匹配项，可增加 offset 继续读取。"
    return _result(text, payload)


def _close_published_input_schemas() -> None:
    """Match the published schema to the middleware's strict extra-field policy."""
    # MCP SDK 2.1 generates open argument models for decorated functions.  The
    # version is pinned for this PoC; middleware above is the actual enforcement.
    for tool in mcp._tool_manager.list_tools():  # type: ignore[attr-defined]
        tool.parameters["additionalProperties"] = False


_close_published_input_schemas()


def main() -> None:
    """Run until the stdio client closes the connection or sends EOF."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
