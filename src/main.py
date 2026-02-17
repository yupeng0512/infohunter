"""InfoHunter 主调度器

多源社交媒体 AI 智能订阅监控系统。
基于 APScheduler 调度采集、分析、通知任务。

架构:
- 订阅流 (Following): 用户创建的关键词/博主/话题订阅，定期采集
- 探索流 (Explore): 系统自动发现热门趋势 + 用户自定义探索关键词
- 推送调度: 与抓取解耦，按固定时间点汇总推送
- AI 分析: 内容分析、趋势雷达、智能推荐、Newsletter 摘要
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
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("interval"):
            try:
                return int(cfg["interval"])
            except (ValueError, TypeError):
                pass
        return settings.explore_fetch_interval

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
        cfg = self._get_db_config("explore_config")
        if cfg and cfg.get("twitter_daily_credit_limit"):
            try:
                return int(cfg["twitter_daily_credit_limit"])
            except (ValueError, TypeError):
                pass
        return settings.twitter_daily_credit_limit

    def _track_twitter_credits(self, credits: int) -> None:
        """追踪 Twitter API credit 消耗"""
        today = datetime.now(self.SERVER_TZ).strftime("%Y-%m-%d")
        if self._twitter_credits_date != today:
            self._twitter_credits_used = 0
            self._twitter_credits_date = today
        self._twitter_credits_used += credits
        logger.debug(f"Twitter credit: +{credits}, 今日累计: {self._twitter_credits_used}")

    def _check_twitter_credit_budget(self, estimated_cost: int = 0) -> bool:
        """检查是否超出每日 credit 预算"""
        limit = self.dynamic_twitter_daily_credit_limit
        if limit <= 0:
            return True  # 不限制
        today = datetime.now(self.SERVER_TZ).strftime("%Y-%m-%d")
        if self._twitter_credits_date != today:
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

            # AI 分析 (如果启用且有新内容)
            if sub.ai_analysis_enabled and self.analyzer and new_count > 0:
                await self._run_analysis()

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
                self._track_twitter_credits(75)
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
                self._track_twitter_credits(75)

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

    async def _enrich_youtube_transcripts(self, items: list[dict]) -> None:
        """为高质量 YouTube 视频获取字幕"""
        if not self.youtube_transcript:
            return

        for item in items[:5]:
            views = item.get("metrics", {}).get("views", 0)
            likes = item.get("metrics", {}).get("likes", 0)

            if views > 1000 or likes > 50:
                video_id = item.get("content_id")
                if video_id:
                    try:
                        transcript = await self.youtube_transcript.get_transcript(video_id)
                        if transcript:
                            item["transcript"] = transcript
                            logger.debug(f"获取字幕成功: {video_id} ({len(transcript)} chars)")
                    except Exception as e:
                        logger.debug(f"获取字幕失败: {video_id}: {e}")

    # ========== 探索流 (Explore/Discover) ==========

    async def run_explore_cycle(self) -> None:
        """执行探索流采集

        两部分:
        1. Twitter 趋势发现 — 拉取热门趋势，用 Top 关键词搜索高质量内容
        2. YouTube 热门发现 — 拉取各地区热门视频
        3. 用户自定义探索关键词
        """
        if not self.dynamic_explore_enabled:
            logger.debug("探索流未启用")
            return

        logger.info("开始探索流采集...")
        total_new = 0

        # 1. Twitter 趋势
        total_new += await self._explore_twitter_trends()

        # 2. YouTube 热门
        total_new += await self._explore_youtube_trending()

        # 3. 用户自定义探索关键词
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
                self._track_twitter_credits(450)
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
                    self._track_twitter_credits(75)
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

                if items:
                    new_count, _ = self.db.save_contents_batch(items)
                    new_total += new_count

                # 为热门视频获取字幕
                if items and self.youtube_transcript:
                    await self._enrich_youtube_transcripts(items)

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
                    self._track_twitter_credits(75)
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

    # ========== 推送调度 (与抓取解耦) ==========

    async def run_notify_batch(self) -> None:
        """定时推送任务

        从数据库取未通知的高质量内容，批量推送到飞书。
        与抓取完全解耦，按 notify_schedule 配置的时间点运行。
        """
        # 动态检查数据库中是否有更新的飞书 webhook 配置
        self._refresh_feishu_client()

        if not self.feishu:
            return

        try:
            threshold = self.dynamic_min_quality_score
            unnotified = self.db.get_unnotified_contents(
                limit=settings.max_notify_per_batch,
                min_quality=threshold,
            )
            if not unnotified:
                logger.debug("无待推送内容")
                return

            logger.info(f"开始批量推送 {len(unnotified)} 条内容...")

            success_count = 0
            for content in unnotified:
                try:
                    sub_name = None
                    if content.subscription_id:
                        sub = self.sub_manager.get(content.subscription_id)
                        if sub:
                            sub_name = sub.name

                    msg = MessageBuilder.build_content_notification(
                        source=content.source,
                        title=content.title,
                        content=content.content or "",
                        author=content.author or "unknown",
                        url=content.url or "",
                        metrics=content.metrics,
                        ai_analysis=content.ai_analysis,
                        subscription_name=sub_name,
                    )

                    source_emoji = {"twitter": "🐦", "youtube": "📺"}.get(
                        content.source, "📰"
                    )
                    title = f"{source_emoji} InfoHunter 新内容"

                    success = await self.feishu.send_markdown_card(title, msg)
                    if success:
                        self.db.mark_contents_notified([content.id])
                        success_count += 1

                except Exception as e:
                    logger.error(f"推送失败 (content_id={content.content_id}): {e}")

            logger.info(f"批量推送完成: {success_count}/{len(unnotified)} 成功")

        except Exception as e:
            logger.error(f"批量推送任务失败: {e}")

    # ========== AI 分析 ==========

    async def _run_analysis(self) -> None:
        """运行 AI 分析"""
        if not self.analyzer:
            return

        try:
            unanalyzed = self.db.get_unanalyzed_contents(limit=10)
            if not unanalyzed:
                return

            logger.info(f"开始 AI 分析 {len(unanalyzed)} 条内容...")

            for content in unanalyzed:
                try:
                    result = await self.analyzer.analyze_content(
                        content=content.content or "",
                        source=content.source,
                        title=content.title,
                        author=content.author,
                        metrics=content.metrics,
                        transcript=content.transcript,
                    )

                    if result["status"] == "success" and result["analysis"]:
                        self.db.update_ai_analysis(content.id, result["analysis"])

                        analysis = result["analysis"]
                        if isinstance(analysis, dict) and analysis.get("importance"):
                            relevance = analysis["importance"] / 10.0
                            self.db.update_scores(
                                content.id, relevance_score=relevance
                            )

                except Exception as e:
                    logger.error(f"分析内容 {content.content_id} 失败: {e}")

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
                if items_for_analysis:
                    result = await self.analyzer.analyze_batch(
                        items_for_analysis, focus="daily_newsletter"
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

        # 1. 订阅流采集调度 (每 5 分钟检查)
        self.scheduler.add_job(
            self.run_fetch_cycle,
            trigger=IntervalTrigger(minutes=5),
            id="fetch_cycle",
            name="订阅流采集",
            replace_existing=True,
        )

        # 2. 探索流采集调度
        if self.dynamic_explore_enabled:
            explore_minutes = max(self.dynamic_explore_interval // 60, 30)
            self.scheduler.add_job(
                self.run_explore_cycle,
                trigger=IntervalTrigger(minutes=explore_minutes),
                id="explore_cycle",
                name="探索流采集",
                replace_existing=True,
            )
            logger.info(f"探索流已启用: 每 {explore_minutes} 分钟采集一次")

        # 3. 推送调度 (按固定时间点)
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
        if notify_times:
            logger.info(f"推送调度已配置: {', '.join(notify_times)}")

        # 4. 日报 (每天 9:00)
        self.scheduler.add_job(
            self.send_daily_report,
            trigger=CronTrigger(hour=9, minute=0, timezone=self.SERVER_TZ),
            id="daily_report",
            name="日报推送",
            replace_existing=True,
        )

        # 5. 周报 (每周一 9:30)
        self.scheduler.add_job(
            self.send_weekly_report,
            trigger=CronTrigger(
                day_of_week=0, hour=9, minute=30, timezone=self.SERVER_TZ
            ),
            id="weekly_report",
            name="周报推送",
            replace_existing=True,
        )

        self.scheduler.start()

        # 首次采集 (仅订阅流，探索流等待调度器触发，避免启动时消耗大量 credit)
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
