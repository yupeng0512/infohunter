"""RSS 数据源

支持两种模式:
1. RSSHub 代理 — 通过 RSSHub 路由获取 Twitter/YouTube 博主时间线 (备用方案)
2. 通用 RSS/Atom — 直接订阅任意 RSS Feed URL (博客、Newsletter 等)
"""

import hashlib
from datetime import datetime
from typing import Any, Optional
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx
import feedparser
from loguru import logger

from src.config import settings
from .base import SourceClient


class RSSClient(SourceClient):
    """RSS 客户端 — 支持 RSSHub 代理和通用 RSS Feed"""

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
        """获取作者 RSS 时间线 (通过 RSSHub)"""
        route_map = {
            "twitter": f"/twitter/user/{author_id}",
            "youtube": f"/youtube/channel/{author_id}",
        }

        route = route_map.get(platform)
        if not route:
            logger.warning(f"Unsupported RSS platform: {platform}")
            return []

        url = f"{self.base_url}{route}"
        return await self._fetch_and_parse(url, source=platform, author=author_id, limit=limit)

    async def fetch_feed(
        self,
        feed_url: str,
        limit: int = 20,
        source: str = "blog",
        author: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """直接获取任意 RSS/Atom Feed

        Args:
            feed_url: 完整的 RSS/Atom Feed URL
            limit: 最大返回条数
            source: 内容来源标识 (默认 "blog")
            author: 作者名称 (可选，自动从 feed 元数据提取)
        """
        return await self._fetch_and_parse(feed_url, source=source, author=author, limit=limit)

    async def _fetch_and_parse(
        self,
        url: str,
        source: str = "blog",
        author: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """通用 RSS 抓取 + 解析"""
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    logger.warning(f"RSS fetch failed: {response.status_code} for {url}")
                    return []

            feed = feedparser.parse(response.text)
            feed_author = author or feed.feed.get("title", "")
            results = []

            for entry in feed.entries[:limit]:
                posted_at = self._parse_date(entry)
                entry_link = entry.get("link", "")
                content_id = entry.get("id", entry_link)
                if not content_id:
                    content_id = hashlib.md5(
                        f"{entry.get('title', '')}{entry_link}".encode()
                    ).hexdigest()
                if len(content_id) > 500:
                    content_id = hashlib.md5(content_id.encode()).hexdigest()

                entry_author = entry.get("author", feed_author)

                results.append({
                    "content_id": content_id,
                    "source": source,
                    "author": entry_author,
                    "author_id": entry_author,
                    "title": entry.get("title", ""),
                    "content": self._extract_content(entry),
                    "url": entry_link,
                    "metrics": {},
                    "posted_at": posted_at,
                    "raw_data": dict(entry),
                })

            logger.info(f"RSS [{source}] {url[:60]}...: found {len(results)} items")
            return results

        except Exception as e:
            self._log_error("_fetch_and_parse", e)
            return []

    @staticmethod
    def _parse_date(entry) -> Optional[datetime]:
        """从 feed entry 解析发布时间"""
        if hasattr(entry, "published") and entry.published:
            try:
                return parsedate_to_datetime(entry.published)
            except (ValueError, TypeError):
                pass
        if hasattr(entry, "updated") and entry.updated:
            try:
                return parsedate_to_datetime(entry.updated)
            except (ValueError, TypeError):
                pass
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6])
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _extract_content(entry) -> str:
        """从 feed entry 提取正文内容 (优先完整内容，fallback 到摘要)"""
        if hasattr(entry, "content") and entry.content:
            for c in entry.content:
                if c.get("type", "").startswith("text"):
                    return c.get("value", "")
        return entry.get("summary", entry.get("description", ""))

    @staticmethod
    def parse_opml(opml_text: str) -> list[dict[str, str]]:
        """解析 OPML 文件，提取 RSS Feed 列表

        Returns:
            [{"title": "...", "xml_url": "...", "html_url": "..."}, ...]
        """
        feeds = []
        try:
            root = ElementTree.fromstring(opml_text)
            for outline in root.iter("outline"):
                xml_url = outline.get("xmlUrl", "").strip()
                if xml_url:
                    feeds.append({
                        "title": outline.get("title") or outline.get("text") or "",
                        "xml_url": xml_url,
                        "html_url": outline.get("htmlUrl", ""),
                    })
        except ElementTree.ParseError as e:
            logger.error(f"OPML parse failed: {e}")
        return feeds
