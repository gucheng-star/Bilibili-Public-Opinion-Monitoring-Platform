"""Strict output contracts published by the read-only MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisListItem(StrictModel):
    analysis_id: int = Field(description="本机分析记录的数值主键")
    bv: str = Field(description="B站视频 BV 号")
    video_title: str = Field(description="视频标题")
    created_at: str | None = Field(description="分析创建时间，ISO 8601 格式")
    status: Literal["done"] = Field(description="阶段 A 仅返回已完成记录")
    analysis_mode: Literal["nlp", "llm"] = Field(description="记录当前保存的分析模式")
    total_comments: int = Field(ge=0, description="数据库中实际保存的评论数")
    llm_schema_version: Literal[0, 1, 2] = Field(description="记录保存的大模型标签版本；只有 2 可用于 V2 输出")
    has_v2_llm_labels: bool = Field(description="全部评论是否均为合法的 V2 情绪与表达风格标签")


class AnalysisListOutput(StrictModel):
    mcp_contract_version: Literal[2] = Field(description="当前只读 MCP 输出契约版本")
    items: list[AnalysisListItem]
    total_count: int = Field(ge=0, description="全部已完成分析记录数")
    has_more: bool = Field(description="当前页之后是否还有记录")
    limit: int = Field(ge=1, le=50)
    offset: int = Field(ge=0, le=100_000)


class RegionItem(StrictModel):
    region: str
    count: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)


class DuplicateStatistics(StrictModel):
    group_count: int = Field(ge=0)
    involved_comments: int = Field(ge=0)
    duplicate_excess: int = Field(ge=0)
    involved_ratio: float = Field(ge=0, le=1)


class TimeRange(StrictModel):
    earliest: str | None
    latest: str | None


class NLPSentimentDistribution(StrictModel):
    """The fixed local three-class sentiment vocabulary."""

    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    neutral: int = Field(ge=0)


class LLMSentimentDistribution(StrictModel):
    """The fixed V2 nine-class LLM primary-emotion vocabulary."""

    neutral: int = Field(ge=0)
    joy: int = Field(ge=0)
    trust: int = Field(ge=0)
    anticipation: int = Field(ge=0)
    surprise: int = Field(ge=0)
    anger: int = Field(ge=0)
    sadness: int = Field(ge=0)
    fear: int = Field(ge=0)
    disgust: int = Field(ge=0)


class LLMStyleDistribution(StrictModel):
    """The fixed V2 five-class LLM expression-style vocabulary."""

    plain: int = Field(ge=0)
    sarcasm: int = Field(ge=0)
    meme: int = Field(ge=0)
    rhetorical: int = Field(ge=0)
    hyperbole: int = Field(ge=0)


class AnalysisOverviewOutput(StrictModel):
    mcp_contract_version: Literal[2] = Field(description="当前只读 MCP 输出契约版本")
    analysis_id: int
    bv: str
    video_title: str
    created_at: str | None
    status: Literal["done"]
    analysis_mode: Literal["nlp", "llm"] = Field(description="记录当前保存的分析模式")
    llm_schema_version: Literal[0, 1, 2] = Field(description="记录保存的大模型标签版本；只有 2 可用于 LLM 口径")
    mode: Literal["nlp", "llm"] = Field(description="本次概览使用的情绪口径")
    declared_total_comments: int = Field(ge=0, description="分析记录声明的评论数")
    stored_comment_count: int = Field(ge=0, description="数据库中实际保存的评论数")
    sentiment_distribution: NLPSentimentDistribution | LLMSentimentDistribution
    style_distribution: LLMStyleDistribution | None = Field(description="仅 LLM V2 口径返回的表达风格分布")
    sentiment_denominator: int = Field(ge=0)
    time_range: TimeRange
    top_regions: list[RegionItem]
    duplicate_statistics: DuplicateStatistics
    data_complete: bool
    limitations: list[str]

    @model_validator(mode="after")
    def distribution_matches_mode(self) -> "AnalysisOverviewOutput":
        """Keep the published distribution vocabulary aligned with ``mode``."""
        if self.mode == "nlp" and not isinstance(self.sentiment_distribution, NLPSentimentDistribution):
            raise ValueError("NLP 模式必须使用三分类情绪分布。")
        if self.mode == "llm" and (
            self.llm_schema_version != 2
            or not isinstance(self.sentiment_distribution, LLMSentimentDistribution)
            or not isinstance(self.style_distribution, LLMStyleDistribution)
        ):
            raise ValueError("LLM 模式必须使用完整的 V2 情绪与表达风格分布。")
        if self.mode == "nlp" and self.style_distribution is not None:
            raise ValueError("NLP 模式不返回表达风格分布。")
        return self


class CommentEvidence(StrictModel):
    content: str = Field(max_length=240, description="最多 240 字符的评论正文")
    post_time: str | None
    likes: int = Field(ge=0)
    sentiment: str
    style: Literal["plain", "sarcasm", "meme", "rhetorical", "hyperbole"] | None
    llm_schema_version: Literal[0, 1, 2]
    is_exact_duplicate: bool
    has_context: bool = Field(description="是否存在根评论或直接父评论关系")


class CommentSearchOutput(StrictModel):
    mcp_contract_version: Literal[2] = Field(description="当前只读 MCP 输出契约版本")
    analysis_id: int
    mode: Literal["nlp", "llm"]
    llm_schema_version: Literal[0, 1, 2]
    matched_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    has_more: bool
    comments: list[CommentEvidence]
    limitations: list[str]
