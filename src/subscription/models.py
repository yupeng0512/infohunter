"""订阅管理 Pydantic 模型

用于 API 请求/响应的数据验证。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SubscriptionCreate(BaseModel):
    """创建订阅请求"""

    name: str = Field(..., description="订阅名称", examples=["AI 趋势追踪"])
    source: str = Field(
        ..., description="数据源: twitter / youtube", pattern="^(twitter|youtube)$"
    )
    type: str = Field(
        ...,
        description="订阅类型: keyword / author / topic",
        pattern="^(keyword|author|topic)$",
    )
    target: str = Field(
        ...,
        description="订阅目标: 关键词 / @用户 / 频道ID",
        examples=["AI OR LLM", "@sama", "UCxxxxxx"],
    )
    filters: Optional[dict] = Field(
        default=None,
        description="额外过滤条件",
        examples=[{"min_likes": 100, "language": "en", "sort": "Latest"}],
    )
    fetch_interval: int = Field(
        default=14400, description="采集间隔 (秒), 默认 4 小时", ge=300, le=86400
    )
    ai_analysis_enabled: bool = Field(default=True, description="是否启用 AI 分析")
    notification_enabled: bool = Field(default=True, description="是否启用通知")


class SubscriptionUpdate(BaseModel):
    """更新订阅请求"""

    name: Optional[str] = None
    target: Optional[str] = None
    filters: Optional[dict] = None
    fetch_interval: Optional[int] = Field(default=None, ge=300, le=86400)
    ai_analysis_enabled: Optional[bool] = None
    notification_enabled: Optional[bool] = None
    status: Optional[str] = Field(default=None, pattern="^(active|paused)$")


class SubscriptionResponse(BaseModel):
    """订阅响应"""

    id: int
    name: str
    source: str
    type: str
    target: str
    filters: Optional[dict] = None
    fetch_interval: int
    ai_analysis_enabled: bool
    notification_enabled: bool
    status: str
    last_fetched_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContentResponse(BaseModel):
    """内容响应"""

    id: int
    content_id: str
    source: str
    subscription_id: Optional[int] = None
    author: Optional[str] = None
    author_id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    transcript: Optional[str] = None
    url: Optional[str] = None
    metrics: Optional[dict] = None
    ai_analysis: Optional[dict] = None
    ai_analyzed_at: Optional[datetime] = None
    relevance_score: Optional[float] = None
    quality_score: Optional[float] = None
    notified: bool = False
    posted_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
