"""配置管理模块

InfoHunter 多源社交媒体 AI 监控系统配置。
支持 Twitter (TwitterAPI.io + ScrapeCreators) 和 YouTube (Data API v3 + ScrapeCreators)。
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===== Twitter API 配置 =====
    # TwitterAPI.io (关键词搜索主力)
    twitterapi_io_key: str = Field(default="", description="TwitterAPI.io API Key")

    # ScrapeCreators (博主详情/字幕辅助)
    scrapecreators_api_key: str = Field(default="", description="ScrapeCreators API Key")

    # RSSHub (博主时间线备用)
    rsshub_base_url: str = Field(
        default="http://localhost:1200", description="RSSHub 服务地址"
    )

    # ===== YouTube API 配置 =====
    # YouTube Data API v3 (搜索/详情主力)
    youtube_api_key: str = Field(default="", description="YouTube Data API v3 Key")

    # ===== Knot Agent 配置 (AG-UI 协议) =====
    knot_enabled: bool = Field(default=False, description="是否启用 Knot Agent 分析")
    knot_api_base_url: str = Field(
        default="http://localhost:8080",
        description="Knot/AG-UI 平台 API 基础地址",
    )
    knot_agent_id: str = Field(default="", description="Knot 内容分析 Agent ID")
    knot_trend_agent_id: str = Field(
        default="", description="Knot 趋势分析 Agent ID (可选，默认复用 knot_agent_id)"
    )
    knot_api_token: str = Field(default="", description="Knot 用户个人 Token (推荐)")
    knot_agent_token: str = Field(default="", description="Knot 智能体 Token")
    knot_username: str = Field(
        default="", description="Knot 用户名 (使用智能体 Token 时需要)"
    )
    knot_model: str = Field(default="deepseek-v3.1", description="Knot 调用的模型")

    # ===== 飞书通知配置 =====
    feishu_webhook_url: str = Field(default="", description="飞书 Webhook URL")
    feishu_secret: str = Field(default="", description="飞书签名密钥")
    feishu_enabled: bool = Field(default=True, description="是否启用飞书通知")

    # ===== MySQL 配置 =====
    mysql_host: str = Field(default="mysql", description="MySQL 主机")
    mysql_port: int = Field(default=3306, description="MySQL 端口")
    mysql_user: str = Field(default="infohunter", description="MySQL 用户名")
    mysql_password: str = Field(default="", description="MySQL 密码")
    mysql_database: str = Field(default="infohunter", description="MySQL 数据库名")

    # ===== 调度配置 =====
    default_fetch_interval: int = Field(
        default=3600, description="默认采集间隔 (秒)"
    )
    min_fetch_gap: int = Field(
        default=300, description="最小采集间隔 (秒)，防止频繁重启时重复采集"
    )

    # ===== 过滤配置 =====
    min_quality_score: float = Field(
        default=0.3, description="最低质量评分阈值 (0-1)"
    )
    realtime_notify_threshold: float = Field(
        default=0.6, description="实时推送的质量阈值 (0-1)"
    )
    max_realtime_per_hour: int = Field(
        default=10, description="每小时最大实时推送数量"
    )

    # ===== API 配置 =====
    api_fetch_limit: int = Field(default=300, description="前端获取内容的默认数量限制")

    # ===== 通用配置 =====
    timezone: str = Field(default="Asia/Shanghai", description="服务器时区")
    log_level: str = Field(default="INFO", description="日志级别")

    @property
    def database_url(self) -> str:
        """获取数据库连接 URL"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
