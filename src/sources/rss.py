"""RSS 数据源 (RSSHub)

备用方案：博主时间线订阅。
已部署在 localhost:1200。
"""

from datetime import datetime
from typing import Any, Optional
from email.utils import parsedate_to_datetime

import httpx
import feedparser
from loguru import logger

from src.config import settings
from .base import SourceClient


class RSSClient(SourceClient):
    """RSSHub RSS 客户端"""

    source_name = "rss"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.rsshub_base_url).rstrip("/")

    async def search(self, query: str, limit: int = 20, **kwargs) -> list[dict[str, Any]]:
        """RSS 不支持搜索"""
        logger.debug("RSS does not support keyword search")
        return []

    async def get_author_content(
        self,
        author_id: str,
        limit: int = 20,
        platform: str = "twitter",
        **kwargs,
    ) -> list[dict[str, Any]]:
        """获取作者 RSS 时间线

        Args:
            author_id: 用户名
            platform: 平台 (twitter / youtube)
        """
        route_map = {
            "twitter": f"/twitter/user/{author_id}",
            "youtube": f"/youtube/channel/{author_id}",
        }

        route = route_map.get(platform)
        if not route:
            logger.warning(f"Unsupported RSS platform: {platform}")
            return []

        url = f"{self.base_url}{route}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    logger.warning(f"RSS fetch failed: {response.status_code} for {url}")
                    return []

            feed = feedparser.parse(response.text)
            results = []

            for entry in feed.entries[:limit]:
                posted_at = None
                if hasattr(entry, "published") and entry.published:
                    try:
                        posted_at = parsedate_to_datetime(entry.published)
                    except (ValueError, TypeError):
                        pass
                if not posted_at and hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        posted_at = datetime(*entry.published_parsed[:6])
                    except (ValueError, TypeError) as e:
                        logger.debug(f"RSS date parse failed: {e}")

                source = "twitter" if platform == "twitter" else "youtube"
                content_id = entry.get("id", entry.get("link", ""))

                results.append({
                    "content_id": content_id,
                    "source": source,
                    "author": author_id,
                    "author_id": author_id,
                    "title": entry.get("title", ""),
                    "content": entry.get("summary", entry.get("description", "")),
                    "url": entry.get("link", ""),
                    "metrics": {},
                    "posted_at": posted_at,
                    "raw_data": dict(entry),
                })

            logger.info(f"RSS {platform}/{author_id}: found {len(results)} items")
            return results

        except Exception as e:
            self._log_error("get_author_content", e)
            return []
