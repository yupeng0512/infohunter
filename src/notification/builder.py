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
    def build_ai_digest(
        source: str,
        title: Optional[str],
        author: str,
        url: str,
        metrics: Optional[dict] = None,
        ai_analysis: Optional[dict] = None,
        subscription_name: Optional[str] = None,
    ) -> str:
        """构建 AI 精选推送（以 AI 分析结果为核心，不推送原文）"""
        source_emoji = {"twitter": "🐦", "youtube": "📺", "blog": "📝"}.get(source, "📰")
        lines = []

        if subscription_name:
            lines.append(f"📌 来源: **{subscription_name}**")
        else:
            lines.append(f"{source_emoji} 来源: **探索发现**")
        lines.append("")

        if title:
            lines.append(f"**{title}**")
            lines.append("")

        if ai_analysis and isinstance(ai_analysis, dict):
            if ai_analysis.get("summary"):
                lines.append(f"📝 **摘要**: {ai_analysis['summary']}")
                lines.append("")

            if ai_analysis.get("key_points"):
                lines.append("💡 **核心观点**:")
                for point in ai_analysis["key_points"][:5]:
                    lines.append(f"  • {point}")
                lines.append("")

            if ai_analysis.get("deep_analysis"):
                lines.append(f"🔬 **深度分析**: {ai_analysis['deep_analysis']}")
                lines.append("")

            if ai_analysis.get("actionable_insights"):
                lines.append("🎯 **可执行洞察**:")
                for insight in ai_analysis["actionable_insights"][:3]:
                    lines.append(f"  • {insight}")
                lines.append("")

            if ai_analysis.get("recommendation"):
                lines.append(f"💡 **建议**: {ai_analysis['recommendation']}")
                lines.append("")

            quality = ai_analysis.get("quality_indicators", {})
            importance = ai_analysis.get("importance", 0)
            if importance:
                stars = "⭐" * min(int(importance / 2), 5)
                lines.append(f"重要性: {stars} ({importance}/10)")

            if quality:
                parts = []
                if quality.get("originality"):
                    parts.append(f"原创 {quality['originality']}")
                if quality.get("depth"):
                    parts.append(f"深度 {quality['depth']}")
                if quality.get("credibility"):
                    parts.append(f"可信 {quality['credibility']}")
                if quality.get("signal_noise_ratio"):
                    parts.append(f"信噪比 {quality['signal_noise_ratio']}")
                if parts:
                    lines.append(f"质量: {' | '.join(parts)}")

            if ai_analysis.get("topics"):
                topics = ai_analysis["topics"][:5]
                lines.append(f"标签: {' '.join(f'#{t}' for t in topics)}")
        else:
            lines.append("⚠️ AI 分析数据异常")

        lines.append("")
        lines.append(f"{source_emoji} @{author}")
        if metrics:
            parts = []
            if metrics.get("likes"):
                parts.append(f"❤️ {metrics['likes']}")
            if metrics.get("views"):
                parts.append(f"👁️ {_format_number(metrics['views'])}")
            if parts:
                lines.append(" | ".join(parts))

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
            rendered = _render_ai_summary(ai_summary)
            if rendered:
                lines.append(rendered)
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
                    if isinstance(insight, dict):
                        lines.append(f"  • {insight.get('insight', str(insight))}")
                    else:
                        lines.append(f"  • {insight}")

            emerging = ai_summary.get("emerging_signals") or ai_summary.get("emerging_trends")
            if emerging:
                lines.append("")
                lines.append("🚀 **新兴趋势/弱信号**")
                if isinstance(emerging, list):
                    for sig in emerging[:3]:
                        if isinstance(sig, dict):
                            lines.append(f"  • {sig.get('signal', str(sig))}")
                        else:
                            lines.append(f"  • {sig}")
                elif isinstance(emerging, str):
                    lines.append(f"  {emerging}")

            sentiment_data = ai_summary.get("sentiment_overview")
            if sentiment_data:
                sentiment_map = {
                    "positive": "😊 积极",
                    "negative": "😟 消极",
                    "neutral": "😐 中性",
                    "mixed": "🔀 混合",
                }
                if isinstance(sentiment_data, dict):
                    overall = sentiment_data.get("overall", "")
                    sentiment = sentiment_map.get(overall, overall)
                    lines.append(f"🎭 **整体情绪**: {sentiment}")
                    if sentiment_data.get("breakdown"):
                        lines.append(f"  {sentiment_data['breakdown']}")
                else:
                    sentiment = sentiment_map.get(sentiment_data, sentiment_data)
                    lines.append(f"🎭 **整体情绪**: {sentiment}")

            rec = ai_summary.get("recommendation")
            if rec:
                if isinstance(rec, dict):
                    if rec.get("immediate_action"):
                        lines.append(f"🎯 **行动建议**: {rec['immediate_action']}")
                    if rec.get("watch_list"):
                        lines.append(f"👀 **关注清单**: {', '.join(rec['watch_list'][:5])}")
                else:
                    lines.append(f"💡 **建议关注**: {rec}")
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


    @staticmethod
    def build_briefing(
        contents: list,
        window_start: datetime,
        window_end: datetime,
        ai_trend_summary: Optional[dict] = None,
    ) -> str:
        """构建时间窗口批量简报（阶段三核心模板）

        Args:
            contents: Content ORM 对象列表（已分析的）
            window_start: 时间窗口开始
            window_end: 时间窗口结束
            ai_trend_summary: trend_analysis Agent 的二次汇总结果
        """
        now = get_local_time()
        start_str = window_start.strftime("%m/%d %H:%M")
        end_str = window_end.strftime("%m/%d %H:%M")

        lines = [
            f"**InfoHunter 简报** ({start_str} ~ {end_str})",
            f"共 **{len(contents)}** 条精选内容",
            "",
        ]

        if ai_trend_summary and isinstance(ai_trend_summary, dict):
            lines.append("---")
            lines.append("**AI 趋势总览**")

            if ai_trend_summary.get("overall_summary"):
                lines.append(ai_trend_summary["overall_summary"])
                lines.append("")

            if ai_trend_summary.get("hot_topics"):
                lines.append("**热点话题**")
                for topic in ai_trend_summary["hot_topics"][:5]:
                    if isinstance(topic, dict):
                        name = topic.get("topic", str(topic))
                        desc = topic.get("description", "")
                        heat = topic.get("heat", 0)
                        heat_bar = "■" * min(int(heat), 10) if heat else ""
                        lines.append(f"  • **{name}** {heat_bar}")
                        if desc:
                            lines.append(f"    {desc}")
                    else:
                        lines.append(f"  • {topic}")
                lines.append("")

            if ai_trend_summary.get("key_insights"):
                lines.append("**关键洞察**")
                for insight in ai_trend_summary["key_insights"][:5]:
                    if isinstance(insight, dict):
                        lines.append(f"  • {insight.get('insight', str(insight))}")
                    else:
                        lines.append(f"  • {insight}")
                lines.append("")

            emerging = ai_trend_summary.get("emerging_signals") or ai_trend_summary.get("emerging_trends")
            if emerging:
                lines.append("**弱信号**")
                if isinstance(emerging, list):
                    for sig in emerging[:3]:
                        if isinstance(sig, dict):
                            lines.append(f"  • {sig.get('signal', str(sig))}")
                        else:
                            lines.append(f"  • {sig}")
                elif isinstance(emerging, str):
                    lines.append(f"  {emerging}")
                lines.append("")

            rec = ai_trend_summary.get("recommendation")
            if rec:
                if isinstance(rec, dict):
                    if rec.get("immediate_action"):
                        lines.append(f"**行动建议**: {rec['immediate_action']}")
                    if rec.get("watch_list"):
                        lines.append(f"**关注清单**: {', '.join(rec['watch_list'][:5])}")
                else:
                    lines.append(f"**建议关注**: {rec}")
                lines.append("")

        lines.append("---")
        lines.append("**精选内容**")
        lines.append("")

        for i, c in enumerate(contents[:20], 1):
            source_emoji = {"twitter": "🐦", "youtube": "📺", "blog": "📝"}.get(
                getattr(c, "source", "") if hasattr(c, "source") else c.get("source", ""),
                "📰",
            )
            title = (
                getattr(c, "title", None) if hasattr(c, "title") else c.get("title")
            )
            author = (
                getattr(c, "author", "") if hasattr(c, "author") else c.get("author", "")
            )
            url = (
                getattr(c, "url", "") if hasattr(c, "url") else c.get("url", "")
            )
            ai = (
                getattr(c, "ai_analysis", None) if hasattr(c, "ai_analysis") else c.get("ai_analysis")
            )

            if not title:
                content_text = getattr(c, "content", "") if hasattr(c, "content") else c.get("content", "")
                title = (content_text[:60] + "...") if content_text else "无标题"

            importance = 0
            summary = ""
            if ai and isinstance(ai, dict):
                importance = ai.get("importance", 0)
                summary = ai.get("summary", "")

            stars = "⭐" * min(int(importance / 2), 5) if importance else ""
            line = f"{i}. {source_emoji} **{title}**"
            if author:
                line += f" @{author}"
            if stars:
                line += f" {stars}"
            lines.append(line)

            if summary:
                lines.append(f"   {summary}")

            if url:
                lines.append(f"   [原文]({url})")
            lines.append("")

        lines.append(f"⏰ {now.strftime('%Y-%m-%d %H:%M')}")
        return "\n".join(lines)


def _render_ai_summary(ai_summary) -> str:
    """渲染 AI 趋势分析为 Markdown 文本

    兼容多种 ai_summary 格式:
      - dict with overall_summary / hot_topics / key_insights (trend prompt)
      - dict with raw_response (extract_json fallback)
      - str (plain text)
    """
    if isinstance(ai_summary, str):
        return ai_summary

    if not isinstance(ai_summary, dict):
        return str(ai_summary) if ai_summary else ""

    # 如果是 extract_json 回退的 raw_response
    if "raw_response" in ai_summary and len(ai_summary) == 1:
        raw = ai_summary["raw_response"]
        return raw[:2000] if isinstance(raw, str) else str(raw)[:2000]

    parts: list[str] = []

    if ai_summary.get("overall_summary"):
        parts.append(ai_summary["overall_summary"])

    if ai_summary.get("hot_topics"):
        parts.append("")
        parts.append("🔥 **热门话题**")
        for topic in ai_summary["hot_topics"][:5]:
            if isinstance(topic, dict):
                name = topic.get("topic", str(topic))
                heat = topic.get("heat", 0)
                heat_bar = "🟥" * min(int(heat), 10) if heat else ""
                desc = topic.get("description", "")
                parts.append(f"• **{name}** {heat_bar}")
                if desc:
                    parts.append(f"  {desc}")
            else:
                parts.append(f"• {topic}")

    if ai_summary.get("key_insights"):
        parts.append("")
        parts.append("💡 **关键洞察**")
        for insight in ai_summary["key_insights"][:5]:
            if isinstance(insight, dict):
                text = insight.get("insight", str(insight))
                parts.append(f"• {text}")
            else:
                parts.append(f"• {insight}")

    if ai_summary.get("emerging_signals"):
        parts.append("")
        parts.append("📡 **新兴信号**")
        for sig in ai_summary["emerging_signals"][:3]:
            if isinstance(sig, dict):
                parts.append(f"• {sig.get('signal', str(sig))}")
            else:
                parts.append(f"• {sig}")

    rec = ai_summary.get("recommendation")
    if rec and isinstance(rec, dict):
        if rec.get("immediate_action"):
            parts.append("")
            parts.append(f"🎯 **行动建议**: {rec['immediate_action']}")
        if rec.get("watch_list"):
            parts.append(f"👀 **关注清单**: {', '.join(rec['watch_list'][:5])}")

    if not parts:
        # 兜底: 如果所有已知字段都为空，直接渲染所有有值的字段
        for k, v in ai_summary.items():
            if v and k != "raw_response":
                parts.append(f"**{k}**: {str(v)[:300]}")

    return "\n".join(parts)


def _format_number(n: int) -> str:
    """格式化数字 (1000 -> 1K, 1000000 -> 1M)"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
