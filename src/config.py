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
    youtube_oauth_client_id: str = Field(default="", description="YouTube OAuth 2.0 Client ID")
    youtube_oauth_client_secret: str = Field(default="", description="YouTube OAuth 2.0 Client Secret")
    youtube_oauth_refresh_token: str = Field(default="", description="YouTube OAuth 2.0 Refresh Token")

    # ===== Knot Agent 配置 (AG-UI 协议) =====
    knot_enabled: bool = Field(default=False, description="是否启用 Knot Agent 分析")
    knot_api_base_url: str = Field(
        default="http://knot.woa.com",
        description="Knot/AG-UI 平台 API 基础地址",
    )
    knot_model: str = Field(default="claude-4.5-sonnet", description="Knot 调用的模型")

    # 内容分析 Agent
    knot_content_agent_id: str = Field(default="", description="内容分析 Agent ID")
    knot_content_agent_key: str = Field(default="", description="内容分析 Agent API Key")

    # 趋势分析 Agent
    knot_trend_agent_id: str = Field(default="", description="趋势分析 Agent ID")
    knot_trend_agent_key: str = Field(default="", description="趋势分析 Agent API Key")

    # 博主评估 Agent
    knot_recommend_agent_id: str = Field(default="", description="博主评估 Agent ID")
    knot_recommend_agent_key: str = Field(default="", description="博主评估 Agent API Key")

    # 兼容旧配置（向后兼容）
    knot_agent_id: str = Field(default="", description="[旧] 通用 Agent ID")
    knot_api_token: str = Field(default="", description="[旧] 用户个人 Token")
    knot_agent_token: str = Field(default="", description="[旧] 智能体 Token")
    knot_username: str = Field(default="", description="[旧] 用户名")

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
    subscription_enabled: bool = Field(
        default=True, description="是否启用订阅流 (关注的博主/关键词定时采集)"
    )
    default_fetch_interval: int = Field(
        default=14400, description="默认采集间隔 (秒), 4h=14400"
    )
    fetch_check_interval: int = Field(
        default=1800, description="检查到期订阅的频率 (秒), 30min=1800"
    )
    min_fetch_gap: int = Field(
        default=300, description="最小采集间隔 (秒)，防止频繁重启时重复采集"
    )

    # ===== 推送配置 (与抓取解耦) =====
    notify_enabled: bool = Field(
        default=True, description="是否启用定时推送通知"
    )
    notify_schedule: str = Field(
        default="09:00,21:00",
        description="推送时间表 (逗号分隔的 HH:MM)，按时间窗口汇总推送",
    )
    notify_mode: str = Field(
        default="incremental",
        description="推送模式: incremental=增量推送, top_list=当前榜单, full_report=周期全量",
    )
    notify_top_n: int = Field(
        default=15, description="推送简报中展示的 TOP N 内容数"
    )
    notify_enable_trend_summary: bool = Field(
        default=True,
        description="推送时是否调用 trend_analysis Agent 做二次汇总",
    )
    max_notify_per_batch: int = Field(
        default=20, description="每次推送最大内容数"
    )

    # ===== 探索流配置 =====
    explore_enabled: bool = Field(
        default=True, description="是否启用探索流 (自动发现热门内容)"
    )
    explore_fetch_interval: int = Field(
        default=21600, description="探索流关键词搜索间隔 (秒), 6h=21600"
    )
    explore_trend_interval: int = Field(
        default=86400, description="探索流趋势发现间隔 (秒), 24h=86400, 消耗大量 credit"
    )
    explore_twitter_woeids: str = Field(
        default="1,23424977,23424868",
        description="Twitter 趋势地区 WOEID (逗号分隔): 1=全球, 23424977=美国, 23424868=中国",
    )
    explore_youtube_regions: str = Field(
        default="US,CN",
        description="YouTube 热门视频地区 (逗号分隔)",
    )
    explore_youtube_category: str = Field(
        default="28",
        description="YouTube 热门视频类别 (28=Science & Technology, 0=全部)",
    )
    explore_keywords: str = Field(
        default="",
        description="用户自定义探索关键词 (逗号分隔)，如 'AI agent,LLM,AGI'",
    )

    # ===== API 调用量控制 =====
    explore_max_trends_per_woeid: int = Field(
        default=2, description="每个 WOEID 取 Top N 趋势进行搜索 (默认 2，减少 credit 消耗)"
    )
    explore_max_search_per_keyword: int = Field(
        default=5, description="每个关键词搜索返回的最大条数"
    )
    twitter_daily_credit_limit: int = Field(
        default=10000, description="Twitter API 每日 credit 上限 (0=不限制)"
    )

    # ===== AI 分析调度配置 =====
    analysis_check_interval: int = Field(
        default=1800, description="AI 分析定时任务检查间隔 (秒), 30min=1800"
    )
    analysis_batch_size: int = Field(
        default=20, description="每轮 AI 分析最大处理条数"
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
