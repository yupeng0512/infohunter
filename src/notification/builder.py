"""消息构建器

为 InfoHunter 多源内容构建飞书通知消息。
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from src.config import settings


def get_local_time() -> datetime:
    """获取本地时间"""
    return datetime.now(ZoneInfo(settings.timezone))


class MessageBuilder:
    """通知消息构建器"""

    @staticmethod
    def build_content_notification(
        source: str,
        title: Optional[str],
        content: str,
        author: str,
        url: str,
        metrics: Optional[dict] = None,
        ai_analysis: Optional[dict] = None,
        subscription_name: Optional[str] = None,
    ) -> str:
        """构建单条内容通知 (Markdown)"""
        source_emoji = {"twitter": "🐦", "youtube": "📺"}.get(source, "📰")
        lines = []

        if subscription_name:
            lines.append(f"📌 订阅: **{subscription_name}**")
            lines.append("")

        # 标题/内容
        if title:
            lines.append(f"**{title}**")
            lines.append("")

        # 正文 (截断)
        text = content[:500] if content else ""
        if text:
            lines.append(text)
            if len(content or "") > 500:
                lines.append("...")
            lines.append("")

        # 作者和互动
        lines.append(f"{source_emoji} @{author}")
        if metrics:
            parts = []
            if metrics.get("likes"):
                parts.append(f"❤️ {metrics['likes']}")
            if metrics.get("retweets"):
                parts.append(f"🔄 {metrics['retweets']}")
            if metrics.get("views"):
                parts.append(f"👁️ {_format_number(metrics['views'])}")
            if metrics.get("replies"):
                parts.append(f"💬 {metrics['replies']}")
            if parts:
                lines.append(" | ".join(parts))

        # AI 分析摘要
        if ai_analysis:
            lines.append("")
            lines.append("---")
            lines.append("🤖 **AI 分析**")
            if isinstance(ai_analysis, dict):
                if ai_analysis.get("summary"):
                    lines.append(f"📝 {ai_analysis['summary']}")
                if ai_analysis.get("key_points"):
                    for point in ai_analysis["key_points"][:3]:
                        lines.append(f"• {point}")
                if ai_analysis.get("importance"):
                    lines.append(f"⭐ 重要性: {ai_analysis['importance']}/10")

        # 链接
        if url:
            lines.append("")
            lines.append(f"[查看原文]({url})")

        return "\n".join(lines)

    @staticmethod
    def build_daily_report(
        contents: list[dict],
        date: Optional[datetime] = None,
        ai_summary: Optional[dict] = None,
    ) -> str:
        """构建日报消息"""
        if date is None:
            date = get_local_time()

        date_str = date.strftime("%Y-%m-%d")
        lines = [f"📊 **InfoHunter 日报** ({date_str})", ""]

        # 统计
        twitter_count = sum(1 for c in contents if c.get("source") == "twitter")
        youtube_count = sum(1 for c in contents if c.get("source") == "youtube")
        lines.append(f"📈 今日采集: **{len(contents)}** 条")
        if twitter_count:
            lines.append(f"  🐦 Twitter: {twitter_count} 条")
        if youtube_count:
            lines.append(f"  📺 YouTube: {youtube_count} 条")
        lines.append("")

        # AI 趋势总结
        if ai_summary:
            lines.append("---")
            lines.append("🤖 **AI 趋势分析**")
            if isinstance(ai_summary, dict):
                if ai_summary.get("overall_summary"):
                    lines.append(ai_summary["overall_summary"])
                if ai_summary.get("hot_topics"):
                    lines.append("")
                    lines.append("🔥 **热门话题**")
                    for topic in ai_summary["hot_topics"][:5]:
                        if isinstance(topic, dict):
                            lines.append(f"• {topic.get('topic', topic)}")
                        else:
                            lines.append(f"• {topic}")
                if ai_summary.get("key_insights"):
                    lines.append("")
                    lines.append("💡 **关键洞察**")
                    for insight in ai_summary["key_insights"][:5]:
                        lines.append(f"• {insight}")
            lines.append("")

        # Top 内容列表
        lines.append("---")
        lines.append("📋 **精选内容 Top 10**")
        lines.append("")

        for i, item in enumerate(contents[:10], 1):
            source_emoji = {"twitter": "🐦", "youtube": "📺"}.get(
                item.get("source", ""), "📰"
            )
            title = item.get("title") or (item.get("content", "")[:80] + "...")
            author = item.get("author", "unknown")
            url = item.get("url", "")

            line = f"{i}. {source_emoji} **{title}**"
            if author:
                line += f" - @{author}"
            if url:
                line += f" [链接]({url})"
            lines.append(line)

        now = get_local_time()
        lines.append("")
        lines.append(f"⏰ 生成时间: {now.strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(lines)

    @staticmethod
    def build_weekly_report(
        contents: list[dict],
        week_start: datetime,
        week_end: datetime,
        ai_summary: Optional[dict] = None,
    ) -> str:
        """构建周报消息"""
        lines = [
            f"📊 **InfoHunter 周报** ({week_start.strftime('%m/%d')} - {week_end.strftime('%m/%d')})",
            "",
        ]

        twitter_count = sum(1 for c in contents if c.get("source") == "twitter")
        youtube_count = sum(1 for c in contents if c.get("source") == "youtube")

        lines.append(f"📈 本周采集: **{len(contents)}** 条")
        if twitter_count:
            lines.append(f"  🐦 Twitter: {twitter_count} 条")
        if youtube_count:
            lines.append(f"  📺 YouTube: {youtube_count} 条")
        lines.append("")

        # 活跃作者统计
        authors: dict[str, int] = {}
        for c in contents:
            author = c.get("author", "")
            if author:
                authors[author] = authors.get(author, 0) + 1
        if authors:
            top_authors = sorted(authors.items(), key=lambda x: x[1], reverse=True)[:5]
            lines.append("👤 **活跃作者 Top 5**")
            for author, count in top_authors:
                lines.append(f"  • @{author} ({count} 条)")
            lines.append("")

        # AI 趋势分析
        if ai_summary and isinstance(ai_summary, dict):
            lines.append("---")
            lines.append("🤖 **AI 周度趋势分析**")
            if ai_summary.get("overall_summary"):
                lines.append(ai_summary["overall_summary"])

            if ai_summary.get("hot_topics"):
                lines.append("")
                lines.append("🔥 **热门话题**")
                for topic in ai_summary["hot_topics"][:5]:
                    if isinstance(topic, dict):
                        heat = topic.get("heat", "")
                        desc = topic.get("description", "")
                        name = topic.get("topic", str(topic))
                        heat_bar = "🟥" * min(int(heat), 10) if heat else ""
                        lines.append(f"  • **{name}** {heat_bar}")
                        if desc:
                            lines.append(f"    {desc}")
                    else:
                        lines.append(f"  • {topic}")

            if ai_summary.get("key_insights"):
                lines.append("")
                lines.append("💡 **关键洞察**")
                for insight in ai_summary["key_insights"][:5]:
                    lines.append(f"  • {insight}")

            if ai_summary.get("emerging_trends"):
                lines.append("")
                lines.append(f"🚀 **新兴趋势**: {ai_summary['emerging_trends']}")

            if ai_summary.get("sentiment_overview"):
                sentiment_map = {
                    "positive": "😊 积极",
                    "negative": "😟 消极",
                    "neutral": "😐 中性",
                    "mixed": "🔀 混合",
                }
                sentiment = sentiment_map.get(
                    ai_summary["sentiment_overview"],
                    ai_summary["sentiment_overview"],
                )
                lines.append(f"🎭 **整体情绪**: {sentiment}")

            if ai_summary.get("recommendation"):
                lines.append(f"💡 **建议关注**: {ai_summary['recommendation']}")
            lines.append("")

        # Top 内容
        lines.append("---")
        lines.append("🏆 **本周 Top 15 内容**")
        lines.append("")

        for i, item in enumerate(contents[:15], 1):
            source_emoji = {"twitter": "🐦", "youtube": "📺"}.get(
                item.get("source", ""), "📰"
            )
            title = item.get("title") or (item.get("content", "")[:80] + "...")
            author = item.get("author", "")
            url = item.get("url", "")
            line = f"{i}. {source_emoji} **{title}**"
            if author:
                line += f" - @{author}"
            if url:
                line += f" [链接]({url})"
            lines.append(line)

        now = get_local_time()
        lines.append("")
        lines.append(f"⏰ 生成时间: {now.strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(lines)


def _format_number(n: int) -> str:
    """格式化数字 (1000 -> 1K, 1000000 -> 1M)"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
