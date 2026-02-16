"""智能过滤器

去重、相关性评分、质量过滤。
"""

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from src.config import settings
from src.storage.database import DatabaseManager


class SmartFilter:
    """智能内容过滤器"""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._seen_hashes: set[str] = set()

    def filter_batch(
        self,
        items: list[dict[str, Any]],
        subscription_id: Optional[int] = None,
        min_quality: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """批量过滤内容

        流程:
        1. 去重 (content_id + 内容指纹)
        2. 计算质量评分
        3. 计算相关性评分
        4. 过滤低质量内容

        Returns:
            过滤后的内容列表
        """
        if not items:
            return []

        min_q = min_quality or settings.min_quality_score
        original_count = len(items)

        # Step 1: 去重
        items = self._deduplicate(items)
        dedup_removed = original_count - len(items)

        # Step 2: 计算质量评分
        for item in items:
            item["quality_score"] = self.calc_quality_score(item)

        # Step 3: 计算相关性评分 (如果有订阅上下文)
        if subscription_id:
            sub = self.db.get_subscription(subscription_id)
            if sub:
                for item in items:
                    item["relevance_score"] = self.calc_relevance_score(item, sub)

        # Step 4: 过滤
        filtered = [i for i in items if i.get("quality_score", 0) >= min_q]
        quality_removed = len(items) - len(filtered)

        # 按质量排序
        filtered.sort(key=lambda x: x.get("quality_score", 0), reverse=True)

        logger.info(
            f"过滤完成: 原始 {original_count}, "
            f"去重移除 {dedup_removed}, "
            f"质量过滤 {quality_removed}, "
            f"保留 {len(filtered)}"
        )

        return filtered

    def _deduplicate(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """去重

        策略:
        1. content_id 精确去重 (数据库 + 批内)
        2. 内容指纹去重 (相似内容)
        """
        unique = []
        seen_ids = set()

        for item in items:
            content_id = item.get("content_id", "")
            source = item.get("source", "")

            # 1. content_id 精确去重 (批内)
            id_key = f"{source}:{content_id}"
            if id_key in seen_ids:
                continue
            seen_ids.add(id_key)

            # 2. content_id 数据库去重
            if content_id and source and self.db.content_exists(content_id, source):
                continue

            # 3. 内容指纹去重
            fingerprint = self._content_fingerprint(item)
            if fingerprint in self._seen_hashes:
                continue
            self._seen_hashes.add(fingerprint)

            unique.append(item)

        return unique

    def _content_fingerprint(self, item: dict) -> str:
        """生成内容指纹

        基于标题 + 内容前 200 字符的哈希。
        可以检测跨平台的重复内容。
        """
        title = (item.get("title") or "").strip().lower()
        content = (item.get("content") or "").strip().lower()[:200]
        text = f"{title}|{content}"
        text = re.sub(r"\s+", " ", text)
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def calc_quality_score(self, item: dict) -> float:
        """计算内容质量评分 (0-1)

        评分维度:
        - 互动量 (0-0.40)
        - 内容丰富度 (0-0.25)
        - 时效性 (0-0.15)
        - 媒体附件 (0-0.10)
        - 作者可信度 (0-0.10)
        """
        score = 0.0
        source = item.get("source", "")
        metrics = item.get("metrics", {})

        # 1. 互动量评分 (0-0.40)
        score += self._score_engagement(metrics, source)

        # 2. 内容丰富度 (0-0.25)
        score += self._score_content_richness(item)

        # 3. 时效性 (0-0.15)
        score += self._score_freshness(item)

        # 4. 媒体附件 (0-0.10)
        if item.get("media_attachments"):
            score += 0.05
        if item.get("transcript"):
            score += 0.05
        elif item.get("title"):
            score += 0.03

        # 5. 作者可信度 (0-0.10)
        score += self._score_author(item)

        return min(round(score, 4), 1.0)

    def _score_engagement(self, metrics: dict, source: str) -> float:
        """互动量评分"""
        if source == "twitter":
            likes = metrics.get("likes", 0)
            retweets = metrics.get("retweets", 0)
            replies = metrics.get("replies", 0)
            views = metrics.get("views", 0)

            engagement = likes + retweets * 2 + replies * 3
            if engagement > 5000:
                return 0.40
            elif engagement > 1000:
                return 0.30
            elif engagement > 100:
                return 0.20
            elif engagement > 10:
                return 0.10
            elif engagement > 0:
                return 0.03
            return 0.0

        elif source == "youtube":
            views = metrics.get("views", 0)
            likes = metrics.get("likes", 0)
            comments = metrics.get("comments", 0)

            if views > 1000000:
                return 0.40
            elif views > 100000:
                return 0.30
            elif views > 10000:
                return 0.20
            elif views > 1000:
                return 0.12
            elif views > 100:
                return 0.05

            # 如果没有播放量数据，用点赞作为备用
            if views == 0 and likes > 0:
                if likes > 1000:
                    return 0.25
                elif likes > 100:
                    return 0.15
                elif likes > 10:
                    return 0.08

            return 0.0

        return 0.0

    def _score_content_richness(self, item: dict) -> float:
        """内容丰富度评分"""
        score = 0.0
        content = item.get("content", "") or ""
        title = item.get("title", "") or ""

        total_len = len(content) + len(title)

        if total_len > 500:
            score += 0.20
        elif total_len > 200:
            score += 0.15
        elif total_len > 100:
            score += 0.10
        elif total_len > 30:
            score += 0.05

        # 有字幕的视频内容更丰富
        transcript = item.get("transcript", "")
        if transcript and len(transcript) > 100:
            score += 0.05

        return min(score, 0.25)

    def _score_freshness(self, item: dict) -> float:
        """时效性评分"""
        posted_at = item.get("posted_at")
        if not posted_at:
            return 0.05

        if isinstance(posted_at, str):
            try:
                posted_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return 0.05

        now = datetime.now()
        if posted_at.tzinfo:
            now = datetime.now(posted_at.tzinfo)

        age = now - posted_at

        if age < timedelta(hours=1):
            return 0.15
        elif age < timedelta(hours=6):
            return 0.12
        elif age < timedelta(hours=24):
            return 0.10
        elif age < timedelta(days=3):
            return 0.07
        elif age < timedelta(days=7):
            return 0.04
        else:
            return 0.02

    def _score_author(self, item: dict) -> float:
        """作者可信度评分 (基础版)"""
        author = item.get("author", "")
        author_id = item.get("author_id", "")

        if not author and not author_id:
            return 0.0

        # 有明确作者信息
        score = 0.03

        # 认证/知名作者 (未来可扩展为数据库查询)
        raw = item.get("raw_data", {})
        if isinstance(raw, dict):
            user = raw.get("user", raw.get("author", {}))
            if isinstance(user, dict):
                if user.get("verified") or user.get("is_blue_verified"):
                    score += 0.05
                followers = user.get("followers_count", user.get("followersCount", 0))
                if followers > 100000:
                    score += 0.02

        return min(score, 0.10)

    def calc_relevance_score(self, item: dict, subscription) -> float:
        """计算内容与订阅的相关性评分 (0-1)

        基于订阅目标关键词在内容中的出现频率和位置。
        """
        target = (getattr(subscription, "target", "") or "").lower()
        if not target:
            return 0.5

        title = (item.get("title") or "").lower()
        content = (item.get("content") or "").lower()
        author = (item.get("author") or "").lower()
        author_id = (item.get("author_id") or "").lower()

        score = 0.0

        # 分割关键词 (支持 OR 语法)
        keywords = [k.strip() for k in target.replace(" OR ", "|").split("|") if k.strip()]
        if not keywords:
            keywords = [target]

        for kw in keywords:
            kw = kw.strip("@#").lower()
            if not kw:
                continue

            # 标题中出现 (权重高)
            if kw in title:
                score += 0.4
            # 内容中出现
            if kw in content:
                score += 0.3
            # 作者匹配 (博主订阅)
            if kw in author or kw in author_id:
                score += 0.3

        # 归一化
        return min(round(score, 4), 1.0)

    def reset_seen_hashes(self) -> None:
        """重置指纹缓存 (每个采集周期后调用)"""
        self._seen_hashes.clear()
