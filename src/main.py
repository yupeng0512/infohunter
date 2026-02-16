"""InfoHunter 主调度器

多源社交媒体 AI 智能订阅监控系统。
基于 APScheduler 调度采集、分析、通知任务。
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

        if settings.youtube_api_key:
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

    async def fetch_subscription(self, sub) -> None:
        """执行单个订阅的采集任务"""
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

            # 为每条内容关联订阅 ID
            for item in items:
                item["subscription_id"] = sub.id

            # 智能过滤 (去重 + 质量评分 + 过滤)
            original_count = len(items)
            if self.smart_filter:
                filtered = self.smart_filter.filter_batch(
                    items, subscription_id=sub.id
                )
            else:
                # 降级: 简单质量评分
                for item in items:
                    item["quality_score"] = self._calc_quality_score(item)
                min_quality = settings.min_quality_score
                filtered = [i for i in items if (i.get("quality_score", 0) >= min_quality)]

            filtered_count = original_count - len(filtered)

            # 保存到数据库
            new_count, updated_count = self.db.save_contents_batch(filtered)

            logger.info(
                f"订阅 {sub.name}: 获取 {len(items)}, "
                f"过滤 {filtered_count}, 新增 {new_count}, 更新 {updated_count}"
            )

            # 记录日志
            self.db.log_fetch(
                subscription_id=sub.id,
                source=sub.source,
                status="success",
                total_fetched=len(items),
                new_items=new_count,
                filtered_items=filtered_count,
                started_at=started_at,
            )

            # 更新采集时间
            self.sub_manager.mark_fetched(sub.id)

            # AI 分析 (如果启用)
            if sub.ai_analysis_enabled and self.analyzer and new_count > 0:
                await self._run_analysis()

            # 发送通知
            if sub.notification_enabled and self.feishu and new_count > 0:
                if self.is_first_run:
                    logger.info("首次运行，跳过通知")
                else:
                    await self._send_notifications()

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
        """执行 Twitter 采集"""
        items = []

        if sub.type == "keyword" or sub.type == "topic":
            # 关键词/话题搜索 -> TwitterAPI.io
            if self.twitter_search:
                sort = "Latest"
                if sub.filters and sub.filters.get("sort"):
                    sort = sub.filters["sort"]
                items = await self.twitter_search.search(
                    query=sub.target,
                    limit=20,
                    sort=sort,
                )
            else:
                logger.warning("TwitterAPI.io 未配置，无法执行关键词搜索")

        elif sub.type == "author":
            # 博主订阅 -> 优先 RSSHub，备用 TwitterAPI.io
            username = sub.target.lstrip("@")

            # 尝试 RSSHub
            rss_items = await self.rss.get_author_content(
                author_id=username, platform="twitter"
            )
            if rss_items:
                items = rss_items
            elif self.twitter_search:
                # 回退到 TwitterAPI.io
                items = await self.twitter_search.get_author_content(
                    author_id=username, limit=20
                )

        return items

    async def _fetch_youtube(self, sub) -> list[dict]:
        """执行 YouTube 采集"""
        items = []

        if sub.type == "keyword" or sub.type == "topic":
            # 关键词/话题搜索 -> 优先 YouTube Data API v3
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
                # 备用: ScrapeCreators YouTube Search
                items = await self.youtube_transcript.search(
                    query=sub.target,
                    limit=20,
                )
            else:
                logger.warning("YouTube 数据源均未配置")

        elif sub.type == "author":
            # 频道订阅 -> 优先 YouTube Data API v3
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
                # 尝试 RSSHub
                rss_items = await self.rss.get_author_content(
                    author_id=channel_id, platform="youtube"
                )
                if rss_items:
                    items = rss_items

        # 为高质量视频获取字幕 (ScrapeCreators)
        if items and self.youtube_transcript:
            await self._enrich_youtube_transcripts(items)

        return items

    async def _enrich_youtube_transcripts(self, items: list[dict]) -> None:
        """为高质量 YouTube 视频获取字幕"""
        if not self.youtube_transcript:
            return

        # 只为互动量较高的视频获取字幕 (节省 credits)
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

    def _calc_quality_score(self, item: dict) -> float:
        """计算内容质量评分 (0-1)"""
        score = 0.0
        metrics = item.get("metrics", {})

        # 互动量评分 (0-0.5)
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

        # 内容长度评分 (0-0.2)
        content = item.get("content", "")
        if len(content) > 200:
            score += 0.2
        elif len(content) > 50:
            score += 0.1
        elif len(content) > 10:
            score += 0.05

        # 有标题加分 (YouTube) (0-0.1)
        if item.get("title"):
            score += 0.1

        # 有媒体加分 (0-0.1)
        if item.get("media_attachments"):
            score += 0.1

        # 播放量加分 (YouTube) (0-0.1)
        if views > 100000:
            score += 0.1
        elif views > 10000:
            score += 0.05

        return min(score, 1.0)

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

                        # 从分析结果更新评分
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

    async def _send_notifications(self) -> None:
        """发送未通知的高质量内容"""
        if not self.feishu:
            return

        try:
            threshold = settings.realtime_notify_threshold
            unnotified = self.db.get_unnotified_contents(
                limit=settings.max_realtime_per_hour,
                min_quality=threshold,
            )
            if not unnotified:
                return

            logger.info(f"发送 {len(unnotified)} 条内容通知...")

            for content in unnotified:
                try:
                    # 获取订阅名称
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

                except Exception as e:
                    logger.error(f"发送通知失败 (content_id={content.content_id}): {e}")

        except Exception as e:
            logger.error(f"通知任务失败: {e}")

    async def send_daily_report(self) -> None:
        """发送日报"""
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

            # AI 趋势分析
            ai_summary = None
            if self.analyzer:
                items_for_analysis = [
                    {
                        "content": c.content or "",
                        "title": c.title,
                        "source": c.source,
                    }
                    for c in contents[:30]
                    if c.content
                ]
                if items_for_analysis:
                    result = await self.analyzer.analyze_batch(
                        items_for_analysis, focus="daily_summary"
                    )
                    if result["status"] == "success":
                        ai_summary = result["analysis"]

            # 构建消息
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

            # AI 趋势分析
            ai_summary = None
            if self.analyzer:
                items_for_analysis = [
                    {
                        "content": c.content or "",
                        "title": c.title,
                        "source": c.source,
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

    async def run_fetch_cycle(self) -> None:
        """执行一轮采集"""
        due_subs = self.sub_manager.get_due_subscriptions()
        if not due_subs:
            logger.debug("无需采集的订阅")
            return

        logger.info(f"本轮需采集 {len(due_subs)} 个订阅")
        for sub in due_subs:
            await self.fetch_subscription(sub)

        # 重置过滤器指纹缓存
        if self.smart_filter:
            self.smart_filter.reset_seen_hashes()

    async def start(self) -> None:
        """启动 InfoHunter"""
        await self.init()
        self.running = True

        now = get_local_time()
        logger.info(f"InfoHunter 启动 ({now.strftime('%Y-%m-%d %H:%M')} {settings.timezone})")

        # 采集调度 (每 5 分钟检查一次是否有订阅需要采集)
        self.scheduler.add_job(
            self.run_fetch_cycle,
            trigger=IntervalTrigger(minutes=5),
            id="fetch_cycle",
            name="采集调度",
            replace_existing=True,
        )

        # 日报 (每天 9:00)
        self.scheduler.add_job(
            self.send_daily_report,
            trigger=CronTrigger(hour=9, minute=0, timezone=self.SERVER_TZ),
            id="daily_report",
            name="日报推送",
            replace_existing=True,
        )

        # 周报 (每周一 9:30)
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

        # 首次采集
        logger.info("执行首次采集...")
        await self.run_fetch_cycle()
        self.is_first_run = False

        # 保持运行
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("收到停止信号")

    async def stop(self) -> None:
        """停止 InfoHunter"""
        logger.info("正在停止 InfoHunter...")
        self.running = False
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
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
