"""数据库模型定义

InfoHunter 多源社交媒体监控系统的数据模型。
支持 Twitter / YouTube 多平台内容存储。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


class Subscription(Base):
    """订阅表

    管理用户的订阅目标：关键词、博主、话题等。
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="订阅名称 (如: AI趋势追踪)"
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="数据源: twitter / youtube"
    )
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="订阅类型: keyword / author / topic"
    )
    target: Mapped[str] = mapped_column(
        String(512), nullable=False,
        comment="订阅目标: 关键词 / #话题 / @用户 / 频道ID"
    )
    filters: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="额外过滤条件 (JSON): min_likes, language, sort 等"
    )

    fetch_interval: Mapped[int] = mapped_column(
        Integer, default=14400, comment="采集间隔 (秒), 默认 4 小时"
    )
    ai_analysis_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用 AI 分析"
    )
    notification_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用通知推送"
    )

    status: Mapped[str] = mapped_column(
        String(32), default="active", comment="状态: active / paused / deleted"
    )
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="上次采集时间"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    contents: Mapped[list["Content"]] = relationship(
        "Content", back_populates="subscription", lazy="dynamic"
    )
    fetch_logs: Mapped[list["FetchLog"]] = relationship(
        "FetchLog", back_populates="subscription", lazy="dynamic"
    )

    __table_args__ = (
        Index("idx_sub_source", "source"),
        Index("idx_sub_type", "type"),
        Index("idx_sub_status", "status"),
        Index("idx_sub_last_fetched", "last_fetched_at"),
    )

    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, name={self.name}, source={self.source}, target={self.target})>"


class Content(Base):
    """内容表

    存储从 Twitter / YouTube 采集的内容。
    统一模型，通过 source 字段区分平台。
    """

    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 平台原始 ID (推文ID / 视频ID)
    content_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="平台原始 ID"
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="数据源: twitter / youtube"
    )

    # 关联订阅
    subscription_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("subscriptions.id"), comment="关联的订阅 ID"
    )

    # 作者信息
    author: Mapped[Optional[str]] = mapped_column(
        String(255), comment="作者名称"
    )
    author_id: Mapped[Optional[str]] = mapped_column(
        String(128), comment="作者平台 ID"
    )

    # 内容
    title: Mapped[Optional[str]] = mapped_column(
        String(512), comment="标题 (YouTube 视频标题)"
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text, comment="正文内容 (推文文本 / 视频描述)"
    )
    transcript: Mapped[Optional[str]] = mapped_column(
        Text, comment="字幕/文字稿 (YouTube 视频字幕)"
    )
    url: Mapped[Optional[str]] = mapped_column(
        String(512), comment="原文链接"
    )

    # 互动指标 (JSON: views, likes, retweets, replies, comments, bookmarks 等)
    metrics: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="互动指标 (JSON)"
    )

    # 媒体附件 (JSON: 图片/视频 URL 列表)
    media_attachments: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="媒体附件 (JSON)"
    )

    # 原始 API 返回数据
    raw_data: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="API 返回的原始数据 (JSON)"
    )

    # AI 分析结果
    ai_analysis: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="AI 分析结果 (JSON)"
    )
    ai_analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="AI 分析时间"
    )

    # 评分
    relevance_score: Mapped[Optional[float]] = mapped_column(
        Float, comment="相关性评分 (0-1)"
    )
    quality_score: Mapped[Optional[float]] = mapped_column(
        Float, comment="质量评分 (0-1)"
    )

    # 通知状态
    notified: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否已发送通知"
    )
    notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="通知发送时间"
    )

    # 时间戳
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="原始发布时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), comment="记录创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), comment="记录更新时间"
    )

    # 关系
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="contents"
    )

    __table_args__ = (
        Index("idx_content_id_source", "content_id", "source", unique=True),
        Index("idx_content_source", "source"),
        Index("idx_content_subscription", "subscription_id"),
        Index("idx_content_author_id", "author_id"),
        Index("idx_content_posted_at", "posted_at"),
        Index("idx_content_notified", "notified"),
        Index("idx_content_ai_analyzed", "ai_analyzed_at"),
        Index("idx_content_quality", "quality_score"),
    )

    def __repr__(self) -> str:
        return f"<Content(id={self.id}, content_id={self.content_id}, source={self.source})>"


class FetchLog(Base):
    """采集日志表

    记录每次采集任务的状态和统计信息。
    """

    __tablename__ = "fetch_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    subscription_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("subscriptions.id"), comment="关联的订阅 ID"
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="数据源: twitter / youtube / rss"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="采集状态: success / failed / partial"
    )

    # 统计
    total_fetched: Mapped[int] = mapped_column(
        Integer, default=0, comment="获取的内容总数"
    )
    new_items: Mapped[int] = mapped_column(
        Integer, default=0, comment="新增内容数"
    )
    filtered_items: Mapped[int] = mapped_column(
        Integer, default=0, comment="被过滤的内容数"
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text, comment="错误信息"
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), comment="开始时间"
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="结束时间"
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Float, comment="耗时 (秒)"
    )

    # 关系
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="fetch_logs"
    )

    __table_args__ = (
        Index("idx_fetch_subscription", "subscription_id"),
        Index("idx_fetch_source", "source"),
        Index("idx_fetch_status", "status"),
        Index("idx_fetch_started_at", "started_at"),
    )

    def __repr__(self) -> str:
        return f"<FetchLog(id={self.id}, source={self.source}, status={self.status})>"


class SystemConfig(Base):
    """系统配置表

    存储运行时配置，支持热更新。
    """

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    config_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="配置键名"
    )
    config_value: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="配置值 (JSON)"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255), comment="配置描述"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_config_key", "config_key"),
    )

    def __repr__(self) -> str:
        return f"<SystemConfig(id={self.id}, key={self.config_key})>"
