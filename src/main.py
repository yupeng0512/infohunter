"""InfoHunter 主调度器

多源社交媒体 AI 智能订阅监控系统。
基于 APScheduler 调度采集、分析、通知任务。

三阶段解耦架构:
- 阶段一 (抓取与落库): 订阅流 + 探索流采集，去重/质量评分后落库，不触发 AI 分析
- 阶段二 (独立 AI 分析): 定时任务按优先级排序处理未分析内容，写回 ai_analysis + importance
- 阶段三 (汇总与推送): 定时按时间窗口查询已分析内容，二次汇总后一次性推送批量简报
"""

import asyncio
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from src.config import settings
from src.storage.database import DatabaseManager, get_db_manager
from src.subscription.manager import SubscriptionManager
from src.sources.twitter_search import TwitterSearchClient
from src.sources.twitter_detail import TwitterDetailClient
from src.sources.youtube import YouTubeClient
from src.sources.youtube_transcript import YouTubeTranscriptClient
from src.sources.transcript_service import TranscriptService
from src.sources.rss import RSSClient
from src.analyzer.content_analyzer import ContentAnalyzer, get_content_analyzer
from src.filter.smart_filter import SmartFilter
from src.notification.client import FeishuClient
from src.notification.builder import MessageBuilder, get_local_time

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=settings.log_level,
)
logger.add(
    "logs/infohunter_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG",
)


class InfoHunter:
    """InfoHunter 主调度器"""

    SERVER_TZ = ZoneInfo(settings.timezone)

    def __init__(self):
        self.db: Optional[DatabaseManager] = None
        self.sub_manager: Optional[SubscriptionManager] = None
        self.twitter_search: Optional[TwitterSearchClient] = None
        self.twitter_detail: Optional[TwitterDetailClient] = None
        self.youtube: Optional[YouTubeClient] = None
        self.youtube_transcript: Optional[YouTubeTranscriptClient] = None
        self.rss: Optional[RSSClient] = None
        self.smart_filter: Optional[SmartFilter] = None
        self.analyzer: Optional[ContentAnalyzer] = None
        self.feishu: Optional[FeishuClient] = None
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.running = False
        self.is_first_run = True
        # Twitter API credit 追踪 (每日重置)
        self._twitter_credits_used: int = 0
        self._twitter_credits_date: str = ""  # YYYY-MM-DD

    # ===== 动态配置（优先读数据库 SystemConfig，fallback 到 .env settings） =====

    def _get_db_config(self, key: str) -> Optional[dict]:
        """从数据库 SystemConfig 读取配置，返回 config_value (dict) 或 None"""
        if not self.db:
            return None
        try:
            cfg = self.db.get_system_config(key)
            return cfg.config_value if cfg else None
        except Exception:
            return None

    @property
    def dynamic_subscription_enabled(self) -> bool:
        cfg = self._get_db_config("subscription_config")
        if cfg and "enabled" in cfg:
            return bool(cfg["enabled"])
        return settings.subscription_enabled

    @property
    def dynamic_notify_enabled(self) -> bool:
        cfg = self._get_db_config("notify_config")
        if cfg and "enabled" in cfg:
            return bool(cfg["enabled"])
        return settings.notify_enabled

    @property
    def dynamic_explore_enabled(self) -> bool:
        cfg = self._get_db_config("explore_config")
        if cfg and "enabled" in cfg:
            return bool(cfg["enabled"])
        return settings.explore_enabled

    @property
    def dynamic_explore_twitter_woeids(self) -> str:
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("twitter_woeids"):
            return cfg["twitter_woeids"]
        return settings.explore_twitter_woeids

    @property
    def dynamic_explore_youtube_regions(self) -> str:
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("youtube_regions"):
            return cfg["youtube_regions"]
        return settings.explore_youtube_regions

    @property
    def dynamic_explore_keywords(self) -> str:
        cfg = self._get_db_config("explore_keywords")
        if cfg and cfg.get("keywords"):
            return cfg["keywords"]
        return settings.explore_keywords

    @property
    def dynamic_notify_schedule(self) -> str:
        cfg = self._get_db_config("notify_schedule")
        if cfg and cfg.get("schedule"):
            return cfg["schedule"]
        return settings.notify_schedule

    @property
    def dynamic_analysis_focus(self) -> str:
        cfg = self._get_db_config("analysis_focus")
        if cfg and cfg.get("focus"):
            return cfg["focus"]
        return "comprehensive"

    @property
    def dynamic_min_quality_score(self) -> float:
        cfg = self._get_db_config("min_quality_score")
        if cfg and "value" in cfg:
            try:
                return float(cfg["value"])
            except (ValueError, TypeError):
                pass
        return settings.min_quality_score

    @property
    def dynamic_explore_interval(self) -> int:
        """关键词搜索间隔 (兼容旧字段名)"""
        return self.dynamic_explore_keyword_interval

    @property
    def dynamic_explore_keyword_interval(self) -> int:
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("keyword_interval"):
            try:
                return int(cfg["keyword_interval"])
            except (ValueError, TypeError):
                pass
        if cfg and cfg.get("interval"):
            try:
                return int(cfg["interval"])
            except (ValueError, TypeError):
                pass
        return settings.explore_fetch_interval

    @property
    def dynamic_explore_trend_interval(self) -> int:
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("trend_interval"):
            try:
                return int(cfg["trend_interval"])
            except (ValueError, TypeError):
                pass
        return settings.explore_trend_interval

    @property
    def dynamic_max_trends_per_woeid(self) -> int:
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("max_trends_per_woeid"):
            try:
                return int(cfg["max_trends_per_woeid"])
            except (ValueError, TypeError):
                pass
        return settings.explore_max_trends_per_woeid

    @property
    def dynamic_max_search_per_keyword(self) -> int:
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("max_search_per_keyword"):
            try:
                return int(cfg["max_search_per_keyword"])
            except (ValueError, TypeError):
                pass
        return settings.explore_max_search_per_keyword

    @property
    def dynamic_twitter_daily_credit_limit(self) -> int:
        # 优先：独立 key
        limit_cfg = self._get_db_config("twitter_credit_limit")
        if limit_cfg and limit_cfg.get("daily_limit") is not None:
            try:
                return int(limit_cfg["daily_limit"])
            except (ValueError, TypeError):
                pass
        # 向后兼容：explore_config 中的旧字段
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("twitter_daily_credit_limit"):
            try:
                return int(cfg["twitter_daily_credit_limit"])
            except (ValueError, TypeError):
                pass
        return settings.twitter_daily_credit_limit

    def _track_twitter_credits(
        self,
        credits: int,
        operation: str = "unknown",
        detail: str = "",
        context: str = "explore",
    ) -> None:
        """追踪 Twitter API credit 消耗并持久化到数据库"""
        today = datetime.now(self.SERVER_TZ).strftime("%Y-%m-%d")
        if self._twitter_credits_date != today:
            self._twitter_credits_used = 0
            self._twitter_credits_date = today
        self._twitter_credits_used += credits
        logger.debug(f"Twitter credit: +{credits}, 今日累计: {self._twitter_credits_used}")

        if self.db:
            try:
                self.db.log_credit_usage(
                    source="twitter",
                    operation=operation,
                    credits=credits,
                    detail=detail or None,
                    context=context,
                )
            except Exception as e:
                logger.warning(f"持久化 credit 记录失败: {e}")

    def _check_twitter_credit_budget(self, estimated_cost: int = 0) -> bool:
        """检查是否超出每日 credit 预算（结合内存和数据库记录）"""
        limit = self.dynamic_twitter_daily_credit_limit
        if limit <= 0:
            return True
        today = datetime.now(self.SERVER_TZ).strftime("%Y-%m-%d")
        if self._twitter_credits_date != today:
            # 新的一天：从数据库恢复已用 credit（防止重启丢失）
            if self.db:
                try:
                    self._twitter_credits_used = self.db.get_credit_usage_today(source="twitter")
                except Exception:
                    self._twitter_credits_used = 0
            else:
                self._twitter_credits_used = 0
            self._twitter_credits_date = today
        if self._twitter_credits_used + estimated_cost > limit:
            logger.warning(
                f"Twitter credit 预算不足: 已用 {self._twitter_credits_used}, "
                f"预估 +{estimated_cost}, 上限 {limit}"
            )
            return False
        return True

    async def init(self) -> None:
        """初始化各组件"""
        logger.info("初始化 InfoHunter...")

        # 数据库
        self.db = get_db_manager()
        self.db.init_db()
        logger.info("数据库初始化完成")

        # 订阅管理
        self.sub_manager = SubscriptionManager(self.db)

        # 迁移：统一过短的订阅间隔为 6h
        self._normalize_subscription_intervals()

        # 数据源
        if settings.twitterapi_io_key:
            self.twitter_search = TwitterSearchClient()
            logger.info("TwitterAPI.io 客户端初始化完成")
        else:
            logger.warning("TwitterAPI.io 未配置")

        if settings.scrapecreators_api_key:
            self.twitter_detail = TwitterDetailClient()
            self.youtube_transcript = YouTubeTranscriptClient()
            logger.info("ScrapeCreators 客户端初始化完成 (Twitter详情 + YouTube字幕)")
        else:
            logger.warning("ScrapeCreators 未配置")

        # 字幕提取服务（始终可用，主: youtube-transcript-api, 备: ScrapeCreators）
        self.transcript_service = TranscriptService(
            fallback_client=self.youtube_transcript
        )

        if settings.youtube_api_key or settings.youtube_oauth_refresh_token:
            self.youtube = YouTubeClient()
            logger.info("YouTube Data API v3 客户端初始化完成")
        else:
            logger.warning("YouTube Data API 未配置")

        self.rss = RSSClient()
        logger.info("RSSHub 客户端初始化完成")

        # 智能过滤器
        self.smart_filter = SmartFilter(self.db)
        logger.info("智能过滤器初始化完成")

        # AI 分析
        if settings.knot_enabled:
            self.analyzer = get_content_analyzer()
            logger.info("AI 分析引擎初始化完成")
        else:
            logger.info("AI 分析未启用")

        # 飞书通知
        if settings.feishu_enabled and settings.feishu_webhook_url:
            try:
                self.feishu = FeishuClient()
                logger.info("飞书客户端初始化完成")
            except Exception as e:
                logger.warning(f"飞书初始化失败: {e}")
        else:
            logger.warning("飞书通知未配置")

        # 调度器
        self.scheduler = AsyncIOScheduler()

    def _normalize_subscription_intervals(self) -> None:
        """将过短的订阅间隔统一为 6h (21600s)"""
        min_interval = settings.default_fetch_interval  # 21600
        subs = self.sub_manager.list_all()
        updated = 0
        for sub in subs:
            if sub.fetch_interval < min_interval:
                self.db.update_subscription(sub.id, {"fetch_interval": min_interval})
                updated += 1
                logger.info(
                    f"订阅 '{sub.name}' 间隔从 {sub.fetch_interval}s 调整为 {min_interval}s"
                )
        if updated:
            logger.info(f"已标准化 {updated} 个订阅的采集间隔为 {min_interval}s ({min_interval // 3600}h)")

    def _refresh_feishu_client(self) -> None:
        """根据数据库 SystemConfig 动态刷新飞书客户端"""
        cfg = self._get_db_config("feishu_webhook")
        if not cfg or not cfg.get("url"):
            return
        db_url = cfg["url"]
        db_secret = cfg.get("secret", "")
        # 如果数据库配置与当前客户端不同，重新创建
        if self.feishu and self.feishu.webhook_url == db_url:
            return
        try:
            self.feishu = FeishuClient(webhook_url=db_url, secret=db_secret)
            logger.info(f"飞书客户端已从数据库配置刷新: {db_url[:50]}...")
        except Exception as e:
            logger.warning(f"刷新飞书客户端失败: {e}")

    # ========== 订阅流 (Following) ==========

    async def fetch_subscription(self, sub) -> None:
        """执行单个订阅的采集任务 (不再直接推送)"""
        started_at = datetime.now()
        logger.info(f"开始采集订阅 [{sub.source}] {sub.name}: {sub.target}")

        try:
            items = []

            if sub.source == "twitter":
                items = await self._fetch_twitter(sub)
            elif sub.source == "youtube":
                items = await self._fetch_youtube(sub)
            elif sub.source == "blog":
                items = await self._fetch_blog(sub)

            if not items:
                logger.info(f"订阅 {sub.name}: 未获取到新内容")
                self.db.log_fetch(
                    subscription_id=sub.id,
                    source=sub.source,
                    status="success",
                    total_fetched=0,
                    started_at=started_at,
                )
                self.sub_manager.mark_fetched(sub.id)
                return

            for item in items:
                item["subscription_id"] = sub.id

            # 智能过滤 (去重 + 质量评分 + 过滤)
            original_count = len(items)
            if self.smart_filter:
                filtered = self.smart_filter.filter_batch(
                    items, subscription_id=sub.id
                )
            else:
                for item in items:
                    item["quality_score"] = self._calc_quality_score(item)
                min_quality = self.dynamic_min_quality_score
                filtered = [i for i in items if (i.get("quality_score", 0) >= min_quality)]

            filtered_count = original_count - len(filtered)

            # 保存到数据库
            new_count, updated_count = self.db.save_contents_batch(filtered)

            logger.info(
                f"订阅 {sub.name}: 获取 {len(items)}, "
                f"过滤 {filtered_count}, 新增 {new_count}, 更新 {updated_count}"
            )

            self.db.log_fetch(
                subscription_id=sub.id,
                source=sub.source,
                status="success",
                total_fetched=len(items),
                new_items=new_count,
                filtered_items=filtered_count,
                started_at=started_at,
            )

            self.sub_manager.mark_fetched(sub.id)

        except Exception as e:
            logger.error(f"采集订阅 {sub.name} 失败: {e}")
            self.db.log_fetch(
                subscription_id=sub.id,
                source=sub.source,
                status="failed",
                error_message=str(e),
                started_at=started_at,
            )

    async def _fetch_twitter(self, sub) -> list[dict]:
        """执行 Twitter 采集 (带 credit 追踪)"""
        items = []

        if sub.type == "keyword" or sub.type == "topic":
            if self.twitter_search:
                if not self._check_twitter_credit_budget(75):
                    logger.warning(f"Twitter credit 预算不足，跳过订阅 {sub.target}")
                    return items
                sort = "Top"
                if sub.filters and sub.filters.get("sort"):
                    sort = sub.filters["sort"]
                items = await self.twitter_search.search(
                    query=sub.target,
                    limit=20,
                    sort=sort,
                )
                self._track_twitter_credits(
                    75, operation="keyword_search",
                    detail=sub.target[:200], context="subscription",
                )
            else:
                logger.warning("TwitterAPI.io 未配置，无法执行关键词搜索")

        elif sub.type == "author":
            username = sub.target.lstrip("@")

            rss_items = await self.rss.get_author_content(
                author_id=username, platform="twitter"
            )
            if rss_items:
                items = rss_items
            elif self.twitter_search:
                if not self._check_twitter_credit_budget(75):
                    logger.warning(f"Twitter credit 预算不足，跳过博主 {username}")
                    return items
                items = await self.twitter_search.get_author_content(
                    author_id=username, limit=20
                )
                self._track_twitter_credits(
                    75, operation="author_search",
                    detail=username, context="subscription",
                )

        return items

    async def _fetch_youtube(self, sub) -> list[dict]:
        """执行 YouTube 采集"""
        items = []

        if sub.type == "keyword" or sub.type == "topic":
            if self.youtube:
                order = "relevance"
                if sub.filters and sub.filters.get("order"):
                    order = sub.filters["order"]
                items = await self.youtube.search(
                    query=sub.target,
                    limit=20,
                    order=order,
                )
            elif self.youtube_transcript:
                items = await self.youtube_transcript.search(
                    query=sub.target,
                    limit=20,
                )
            else:
                logger.warning("YouTube 数据源均未配置")

        elif sub.type == "author":
            channel_id = sub.target

            if self.youtube:
                items = await self.youtube.get_author_content(
                    author_id=channel_id,
                    limit=20,
                )
            elif self.youtube_transcript:
                items = await self.youtube_transcript.get_author_content(
                    author_id=channel_id,
                    limit=20,
                )
            else:
                rss_items = await self.rss.get_author_content(
                    author_id=channel_id, platform="youtube"
                )
                if rss_items:
                    items = rss_items

        # 为高质量视频获取字幕
        if items and self.youtube_transcript:
            await self._enrich_youtube_transcripts(items)

        return items

    async def _fetch_blog(self, sub) -> list[dict]:
        """执行 Blog/RSS 采集"""
        if sub.type != "feed" or not sub.target:
            logger.warning(f"Blog 订阅 {sub.name}: 类型或目标无效 (type={sub.type})")
            return []

        items = await self.rss.fetch_feed(
            feed_url=sub.target,
            limit=20,
            source="blog",
            author=sub.name,
        )
        return items

    async def _enrich_youtube_transcripts(self, items: list[dict]) -> None:
        """为高质量 YouTube 视频获取字幕

        按互动量降序排序，优先为高互动视频获取字幕，
        每批上限由 settings.transcript_batch_size 控制。
        """
        if not self.transcript_service:
            return

        batch_size = settings.transcript_batch_size
        candidates = [
            item for item in items
            if not item.get("transcript")
            and item.get("content_id")
            and (
                item.get("metrics", {}).get("views", 0) > 1000
                or item.get("metrics", {}).get("likes", 0) > 50
            )
        ]
        candidates.sort(
            key=lambda x: (
                x.get("metrics", {}).get("views", 0)
                + x.get("metrics", {}).get("likes", 0) * 100
            ),
            reverse=True,
        )

        fetched = 0
        for item in candidates[:batch_size]:
            video_id = item["content_id"]
            try:
                transcript = await self.transcript_service.get_transcript(video_id)
                if transcript:
                    item["transcript"] = transcript
                    fetched += 1
                    logger.info(f"获取字幕成功: {video_id} ({len(transcript)} chars)")
                else:
                    logger.warning(f"获取字幕失败 (无可用字幕): {video_id}")
            except Exception as e:
                logger.warning(f"获取字幕异常: {video_id}: {e}")

        if candidates:
            logger.info(f"字幕获取: {fetched}/{len(candidates[:batch_size])} 成功")

    # ========== 探索流 (Explore/Discover) ==========

    async def _explore_trends_job(self) -> None:
        """调度器入口 — 趋势发现 (低频, 默认 24h)
        包含: Twitter 趋势 + YouTube 热门
        """
        if not self.dynamic_explore_enabled:
            logger.debug("探索流未启用，跳过趋势发现")
            return

        logger.info("开始趋势发现...")
        total_new = 0
        total_new += await self._explore_twitter_trends()
        total_new += await self._explore_youtube_trending()
        logger.info(f"趋势发现完成: 新增 {total_new} 条内容")

    async def _explore_keywords_job(self) -> None:
        """调度器入口 — 关键词探索 (中频, 默认 6h)
        包含: 用户自定义关键词在 Twitter + YouTube 搜索
        """
        if not self.dynamic_explore_enabled:
            logger.debug("探索流未启用，跳过关键词探索")
            return

        logger.info("开始关键词探索...")
        total_new = await self._explore_custom_keywords()
        logger.info(f"关键词探索完成: 新增 {total_new} 条内容")

    async def run_explore_cycle(self) -> None:
        """执行完整探索流 (手动触发时使用，包含趋势+关键词)"""
        if not self.dynamic_explore_enabled:
            logger.debug("探索流未启用")
            return

        logger.info("开始完整探索流采集...")
        total_new = 0
        total_new += await self._explore_twitter_trends()
        total_new += await self._explore_youtube_trending()
        total_new += await self._explore_custom_keywords()
        logger.info(f"探索流采集完成: 新增 {total_new} 条内容")

    async def _explore_twitter_trends(self) -> int:
        """Twitter 趋势探索 (带 credit 预算控制)"""
        if not self.twitter_search:
            return 0

        woeids = [
            int(w.strip())
            for w in self.dynamic_explore_twitter_woeids.split(",")
            if w.strip()
        ]
        max_trends = self.dynamic_max_trends_per_woeid
        search_limit = self.dynamic_max_search_per_keyword

        # 预估 credit: 每个 WOEID 趋势 ~450 + 每次搜索 ~75
        estimated = len(woeids) * 450 + len(woeids) * max_trends * 75
        if not self._check_twitter_credit_budget(estimated):
            logger.warning(f"Twitter 趋势探索: credit 预算不足，跳过 (预估 {estimated})")
            return 0

        new_total = 0
        for woeid in woeids:
            try:
                trends = await self.twitter_search.get_trends(woeid=woeid, count=10)
                self._track_twitter_credits(
                    450, operation="trends",
                    detail=f"woeid={woeid}", context="explore",
                )
                if not trends:
                    continue

                for trend in trends[:max_trends]:
                    if not self._check_twitter_credit_budget(75):
                        logger.warning("Twitter credit 预算耗尽，停止趋势搜索")
                        break

                    query = trend.get("query") or trend.get("name")
                    if not query:
                        continue

                    items = await self.twitter_search.search(
                        query=query, limit=search_limit, sort="Top"
                    )
                    self._track_twitter_credits(
                        75, operation="trend_search",
                        detail=query[:200], context="explore",
                    )
                    if not items:
                        continue

                    for item in items:
                        item["subscription_id"] = None

                    if self.smart_filter:
                        items = self.smart_filter.filter_batch(items)
                    else:
                        for item in items:
                            item["quality_score"] = self._calc_quality_score(item)
                        items = [i for i in items if i.get("quality_score", 0) >= self.dynamic_min_quality_score]

                    if items:
                        new_count, _ = self.db.save_contents_batch(items)
                        new_total += new_count

            except Exception as e:
                logger.error(f"Twitter 趋势探索失败 (woeid={woeid}): {e}")

        if new_total > 0:
            logger.info(f"Twitter 趋势探索: 新增 {new_total} 条 (credit 已用: {self._twitter_credits_used})")
        return new_total

    async def _explore_youtube_trending(self) -> int:
        """YouTube 热门视频探索"""
        if not self.youtube:
            return 0

        new_total = 0
        regions = [
            r.strip()
            for r in self.dynamic_explore_youtube_regions.split(",")
            if r.strip()
        ]
        category = settings.explore_youtube_category  # category 不常改，保持 .env

        for region in regions:
            try:
                items = await self.youtube.get_trending(
                    region_code=region,
                    category_id=category,
                    limit=10,
                )
                if not items:
                    continue

                for item in items:
                    item["subscription_id"] = None

                if self.smart_filter:
                    items = self.smart_filter.filter_batch(items)
                else:
                    for item in items:
                        item["quality_score"] = self._calc_quality_score(item)
                    items = [i for i in items if i.get("quality_score", 0) >= self.dynamic_min_quality_score]

                # 先获取字幕，再保存（确保字幕入库）
                if items:
                    await self._enrich_youtube_transcripts(items)

                if items:
                    new_count, _ = self.db.save_contents_batch(items)
                    new_total += new_count

            except Exception as e:
                logger.error(f"YouTube 热门探索失败 (region={region}): {e}")

        if new_total > 0:
            logger.info(f"YouTube 热门探索: 新增 {new_total} 条")
        return new_total

    async def _explore_custom_keywords(self) -> int:
        """用户自定义探索关键词 (带 credit 预算控制)"""
        keywords = [
            k.strip()
            for k in self.dynamic_explore_keywords.split(",")
            if k.strip()
        ]
        if not keywords:
            return 0

        search_limit = self.dynamic_max_search_per_keyword
        new_total = 0

        for keyword in keywords:
            # Twitter 搜索 (带 credit 检查)
            if self.twitter_search and self._check_twitter_credit_budget(75):
                try:
                    items = await self.twitter_search.search(
                        query=keyword, limit=search_limit, sort="Top"
                    )
                    self._track_twitter_credits(
                        75, operation="keyword_search",
                        detail=keyword[:200], context="explore",
                    )
                    for item in items:
                        item["subscription_id"] = None
                    if self.smart_filter:
                        items = self.smart_filter.filter_batch(items)
                    if items:
                        new_count, _ = self.db.save_contents_batch(items)
                        new_total += new_count
                except Exception as e:
                    logger.error(f"探索关键词 Twitter 搜索失败 ({keyword}): {e}")

            # YouTube 搜索 (viewCount 排序获取热门)
            if self.youtube:
                try:
                    items = await self.youtube.search(
                        query=keyword, limit=search_limit, order="viewCount"
                    )
                    for item in items:
                        item["subscription_id"] = None
                    if self.smart_filter:
                        items = self.smart_filter.filter_batch(items)
                    if items:
                        new_count, _ = self.db.save_contents_batch(items)
                        new_total += new_count
                except Exception as e:
                    logger.error(f"探索关键词 YouTube 搜索失败 ({keyword}): {e}")

        if new_total > 0:
            logger.info(f"自定义探索关键词: 新增 {new_total} 条")
        return new_total

    # ========== 阶段三：推送调度 (时间窗口 + 批量简报) ==========

    async def run_notify_batch(self) -> None:
        """定时推送任务（时间窗口 + 批量简报模式）

        核心逻辑：
        1. 确定时间窗口 [上次推送时间 ~ 当前]
        2. 查询窗口内已分析但未推送的内容
        3. 按 importance 排序取 TOP N
        4. 可选：调用 trend_analysis Agent 做二次汇总
        5. 构建一份简报，一次性推送到飞书
        6. 标记所有内容为已推送
        """
        if not self.dynamic_notify_enabled:
            logger.debug("推送通知未启用")
            return

        self._refresh_feishu_client()

        if not self.feishu:
            return

        try:
            now = datetime.now()
            window_start = self.db.get_last_notify_time()
            if not window_start:
                window_start = now - timedelta(hours=12)
            window_end = now

            top_n = settings.notify_top_n

            contents = self.db.get_analyzed_contents_in_window(
                window_start=window_start,
                window_end=window_end,
                notified=False,
                limit=top_n,
            )

            if not contents:
                logger.debug(
                    f"无待推送内容 "
                    f"(窗口 {window_start.strftime('%m/%d %H:%M')} ~ {window_end.strftime('%m/%d %H:%M')})"
                )
                return

            logger.info(
                f"推送简报: {len(contents)} 条内容 "
                f"(窗口 {window_start.strftime('%m/%d %H:%M')} ~ {window_end.strftime('%m/%d %H:%M')})"
            )

            ai_trend_summary = None
            if settings.notify_enable_trend_summary and self.analyzer and len(contents) >= 3:
                try:
                    items_for_trend = [
                        {
                            "content": c.content or "",
                            "title": c.title,
                            "source": c.source,
                            "author": c.author or "",
                            "metrics": c.metrics,
                            "ai_analysis": c.ai_analysis,
                        }
                        for c in contents
                        if c.ai_analysis
                    ]
                    if items_for_trend:
                        result = await self.analyzer.analyze_batch(
                            items_for_trend, focus="briefing_summary"
                        )
                        if result["status"] == "success":
                            ai_trend_summary = result["analysis"]
                            logger.info("二次汇总完成")
                except Exception as e:
                    logger.warning(f"二次汇总失败 (不影响推送): {e}")

            msg = MessageBuilder.build_briefing(
                contents=contents,
                window_start=window_start,
                window_end=window_end,
                ai_trend_summary=ai_trend_summary,
            )

            success = await self.feishu.send_markdown_card(
                "📋 InfoHunter 简报", msg
            )

            if success:
                content_ids = [c.id for c in contents]
                self.db.mark_contents_notified(content_ids)
                logger.info(f"简报推送成功: {len(contents)} 条内容已标记为已推送")
            else:
                logger.error("简报推送失败")

            await self._push_to_app_users(contents)

        except Exception as e:
            logger.error(f"推送任务失败: {e}")

    async def _push_to_app_users(self, contents: list) -> None:
        """内容推送到 App 用户（通过 Expo Push Service）"""
        try:
            from src.notification.push_service import PushService

            push_svc = PushService(self.db)
            active_tokens = push_svc.get_active_tokens()
            if not active_tokens:
                return

            count = len(contents)
            result = await push_svc.push_daily_digest(user_id=None, count=count)
            logger.info(f"App 推送: {result}")

        except Exception as e:
            logger.warning(f"App 推送失败 (不影响主流程): {e}")

    # ========== 阶段二：独立 AI 分析定时任务 ==========

    async def run_ai_analysis_job(self) -> None:
        """独立 AI 分析定时任务（与抓取/推送完全解耦）

        按优先级排序处理未分析内容：
        1. 订阅流（有 subscription_id）优先于探索流
        2. 越新的内容越优先
        3. 每轮上限 analysis_batch_size 条
        """
        if not self.analyzer:
            return

        batch_size = settings.analysis_batch_size
        analysis_focus = self.dynamic_analysis_focus

        try:
            unanalyzed = self.db.get_unanalyzed_contents_prioritized(limit=batch_size)
            if not unanalyzed:
                logger.debug("无待分析内容")
                return

            logger.info(f"AI 分析任务: 待处理 {len(unanalyzed)} 条 (侧重: {analysis_focus})")

            analyzed_count = 0
            for content in unanalyzed:
                try:
                    # 为缺少字幕的高价值 YouTube 视频自动补充
                    if (
                        content.source == "youtube"
                        and not content.transcript
                        and self.transcript_service
                    ):
                        views = (content.metrics or {}).get("views", 0)
                        likes = (content.metrics or {}).get("likes", 0)
                        if views > 1000 or likes > 50:
                            transcript = await self.transcript_service.get_transcript(
                                content.content_id
                            )
                            if transcript:
                                self.db.update_transcript(content.id, transcript)
                                content.transcript = transcript
                                logger.info(
                                    f"AI分析前补充字幕: {content.content_id} "
                                    f"({len(transcript)} chars)"
                                )

                    result = await self.analyzer.analyze_content(
                        content=content.content or "",
                        source=content.source,
                        title=content.title,
                        author=content.author,
                        metrics=content.metrics,
                        transcript=content.transcript,
                        analysis_focus=analysis_focus,
                    )

                    if result["status"] == "success" and result["analysis"]:
                        analysis = result["analysis"]
                        importance = None
                        if isinstance(analysis, dict):
                            importance = analysis.get("importance")

                        self.db.update_ai_analysis(
                            content.id, analysis, importance=importance
                        )
                        analyzed_count += 1

                except Exception as e:
                    logger.error(f"分析内容 {content.content_id} 失败: {e}")

            logger.info(f"AI 分析完成: {analyzed_count}/{len(unanalyzed)} 成功")

        except Exception as e:
            logger.error(f"AI 分析任务失败: {e}")

    # ========== 报告 ==========

    async def send_daily_report(self) -> None:
        """发送日报 (AI Newsletter 摘要)"""
        if not self.feishu:
            return

        try:
            now = datetime.now(self.SERVER_TZ)
            since = now - timedelta(hours=24)
            since_naive = since.replace(tzinfo=None)

            contents = self.db.get_contents_for_report(since=since_naive)
            if not contents:
                logger.info("过去 24 小时无内容，跳过日报")
                return

            # AI 趋势分析 (趋势雷达 + Newsletter 摘要)
            ai_summary = None
            if self.analyzer:
                items_for_analysis = [
                    {
                        "content": c.content or "",
                        "title": c.title,
                        "source": c.source,
                        "author": c.author or "",
                        "metrics": c.metrics,
                    }
                    for c in contents[:30]
                    if c.content
                ]
                logger.info(f"日报 AI 分析: {len(items_for_analysis)} 条内容待分析")
                if items_for_analysis:
                    result = await self.analyzer.analyze_batch(
                        items_for_analysis, focus="daily_newsletter"
                    )
                    if result["status"] == "success":
                        ai_summary = result["analysis"]
                        if isinstance(ai_summary, dict):
                            non_empty = {
                                k: type(v).__name__
                                for k, v in ai_summary.items()
                                if v
                            }
                            logger.info(
                                f"日报 AI 趋势分析成功, "
                                f"fields={non_empty}"
                            )
                        else:
                            logger.info(
                                f"日报 AI 趋势分析成功, type={type(ai_summary).__name__}"
                            )
                    else:
                        logger.warning(
                            f"日报 AI 趋势分析失败: status={result['status']}, "
                            f"error={result.get('error')}"
                        )

            contents_data = [
                {
                    "source": c.source,
                    "title": c.title,
                    "content": c.content or "",
                    "author": c.author or "",
                    "url": c.url or "",
                }
                for c in contents
            ]

            msg = MessageBuilder.build_daily_report(
                contents_data, date=now, ai_summary=ai_summary
            )

            success = await self.feishu.send_markdown_card("📊 InfoHunter 日报", msg)
            if success:
                logger.info(f"日报推送成功，共 {len(contents)} 条内容")
            else:
                logger.error("日报推送失败")

        except Exception as e:
            logger.error(f"发送日报失败: {e}")

    async def send_weekly_report(self) -> None:
        """发送周报"""
        if not self.feishu:
            return

        try:
            now = datetime.now(self.SERVER_TZ)
            since = now - timedelta(days=7)
            since_naive = since.replace(tzinfo=None)

            contents = self.db.get_contents_for_report(since=since_naive, limit=500)
            if not contents:
                logger.info("过去 7 天无内容，跳过周报")
                return

            ai_summary = None
            if self.analyzer:
                items_for_analysis = [
                    {
                        "content": c.content or "",
                        "title": c.title,
                        "source": c.source,
                        "author": c.author or "",
                        "metrics": c.metrics,
                    }
                    for c in contents[:50]
                    if c.content
                ]
                if items_for_analysis:
                    result = await self.analyzer.analyze_batch(
                        items_for_analysis, focus="weekly_summary"
                    )
                    if result["status"] == "success":
                        ai_summary = result["analysis"]

            contents_data = [
                {
                    "source": c.source,
                    "title": c.title,
                    "content": c.content or "",
                    "author": c.author or "",
                    "url": c.url or "",
                }
                for c in contents
            ]

            msg = MessageBuilder.build_weekly_report(
                contents_data,
                week_start=since_naive,
                week_end=now.replace(tzinfo=None),
                ai_summary=ai_summary,
            )

            success = await self.feishu.send_markdown_card("📊 InfoHunter 周报", msg)
            if success:
                logger.info(f"周报推送成功，共 {len(contents)} 条内容")

        except Exception as e:
            logger.error(f"发送周报失败: {e}")

    # ========== 质量评分 ==========

    def _calc_quality_score(self, item: dict) -> float:
        """计算内容质量评分 (0-1)"""
        score = 0.0
        metrics = item.get("metrics", {})

        likes = metrics.get("likes", 0)
        retweets = metrics.get("retweets", 0)
        views = metrics.get("views", 0)
        replies = metrics.get("replies", 0)

        engagement = likes + retweets * 2 + replies * 3
        if engagement > 1000:
            score += 0.5
        elif engagement > 100:
            score += 0.3
        elif engagement > 10:
            score += 0.15
        elif engagement > 0:
            score += 0.05

        content = item.get("content", "")
        if len(content) > 200:
            score += 0.2
        elif len(content) > 50:
            score += 0.1
        elif len(content) > 10:
            score += 0.05

        if item.get("title"):
            score += 0.1

        if item.get("media_attachments"):
            score += 0.1

        if views > 100000:
            score += 0.1
        elif views > 10000:
            score += 0.05

        return min(score, 1.0)

    # ========== 调度循环 ==========

    async def run_fetch_cycle(self) -> None:
        """执行一轮订阅流采集"""
        if not self.dynamic_subscription_enabled:
            logger.debug("订阅流未启用")
            return

        due_subs = self.sub_manager.get_due_subscriptions()
        if not due_subs:
            logger.debug("无需采集的订阅")
            return

        logger.info(f"本轮需采集 {len(due_subs)} 个订阅")
        for sub in due_subs:
            await self.fetch_subscription(sub)

        if self.smart_filter:
            self.smart_filter.reset_seen_hashes()

    async def start(self) -> None:
        """启动 InfoHunter"""
        await self.init()
        self.running = True

        now = get_local_time()
        logger.info(f"InfoHunter 启动 ({now.strftime('%Y-%m-%d %H:%M')} {settings.timezone})")

        # 1. 订阅流采集调度 (默认每 30 分钟检查到期订阅)
        fetch_check_minutes = max(settings.fetch_check_interval // 60, 5)
        self.scheduler.add_job(
            self.run_fetch_cycle,
            trigger=IntervalTrigger(minutes=fetch_check_minutes),
            id="fetch_cycle",
            name="订阅流采集",
            replace_existing=True,
        )
        logger.info(
            f"订阅流: {'已启用' if self.dynamic_subscription_enabled else '已关闭'} "
            f"(检查间隔 {fetch_check_minutes}min)"
        )

        # 2. 探索流 — 趋势发现 (低频，默认 24h，消耗大量 credit)
        explore_trend_hours = max(self.dynamic_explore_trend_interval // 3600, 1)
        self.scheduler.add_job(
            self._explore_trends_job,
            trigger=IntervalTrigger(hours=explore_trend_hours),
            id="explore_trends",
            name="趋势发现",
            replace_existing=True,
        )

        # 3. 探索流 — 关键词搜索 (中频，默认 6h)
        explore_kw_minutes = max(self.dynamic_explore_keyword_interval // 60, 30)
        self.scheduler.add_job(
            self._explore_keywords_job,
            trigger=IntervalTrigger(minutes=explore_kw_minutes),
            id="explore_keywords",
            name="关键词探索",
            replace_existing=True,
        )
        logger.info(
            f"探索流: {'已启用' if self.dynamic_explore_enabled else '已关闭'} "
            f"(趋势 {explore_trend_hours}h, 关键词 {explore_kw_minutes}min)"
        )

        # 4. 独立 AI 分析定时任务
        if self.analyzer:
            analysis_check_minutes = max(settings.analysis_check_interval // 60, 5)
            self.scheduler.add_job(
                self.run_ai_analysis_job,
                trigger=IntervalTrigger(minutes=analysis_check_minutes),
                id="ai_analysis",
                name="AI 分析",
                replace_existing=True,
            )
            logger.info(
                f"AI 分析: 已启用 (间隔 {analysis_check_minutes}min, "
                f"每轮上限 {settings.analysis_batch_size} 条)"
            )
        else:
            logger.info("AI 分析: 未启用 (knot_enabled=false)")

        # 5. 推送调度 (时间窗口 + 批量简报，启停由 handler 动态判断)
        notify_times = [
            t.strip()
            for t in self.dynamic_notify_schedule.split(",")
            if t.strip()
        ]
        for i, time_str in enumerate(notify_times):
            try:
                hour, minute = time_str.split(":")
                self.scheduler.add_job(
                    self.run_notify_batch,
                    trigger=CronTrigger(
                        hour=int(hour), minute=int(minute), timezone=self.SERVER_TZ
                    ),
                    id=f"notify_batch_{i}",
                    name=f"定时推送 ({time_str})",
                    replace_existing=True,
                )
            except ValueError:
                logger.warning(f"无效的推送时间格式: {time_str}")
        logger.info(
            f"推送: {'已启用' if self.dynamic_notify_enabled else '已关闭'} "
            f"({', '.join(notify_times)})"
        )

        # 6. 日报 (每天 09:30，在简报之后，提供 24h 全量视角)
        self.scheduler.add_job(
            self.send_daily_report,
            trigger=CronTrigger(hour=9, minute=30, timezone=self.SERVER_TZ),
            id="daily_report",
            name="日报推送",
            replace_existing=True,
        )

        # 7. 周报 (每周一 10:00，与日报/简报错开)
        self.scheduler.add_job(
            self.send_weekly_report,
            trigger=CronTrigger(
                day_of_week=0, hour=10, minute=0, timezone=self.SERVER_TZ
            ),
            id="weekly_report",
            name="周报推送",
            replace_existing=True,
        )

        self.scheduler.start()

        # 首次采集 (仅订阅流，探索流等待调度器触发)
        if self.dynamic_subscription_enabled:
            logger.info("执行首次订阅流采集...")
            await self.run_fetch_cycle()
        self.is_first_run = False
        logger.info("探索流将在下一个调度周期自动执行 (不在启动时立即执行以节省 credit)")

        # 保持运行
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("收到停止信号")

    async def stop(self) -> None:
        """优雅停止 InfoHunter"""
        if not self.running:
            return
        logger.info("正在停止 InfoHunter...")
        self.running = False
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("APScheduler 已停止")
        logger.info("InfoHunter 已停止")


async def main():
    """主函数"""
    hunter = InfoHunter()

    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("收到终止信号...")
        asyncio.create_task(hunter.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await hunter.start()
    except Exception as e:
        logger.error(f"InfoHunter 异常: {e}")
    finally:
        await hunter.stop()


if __name__ == "__main__":
    asyncio.run(main())
