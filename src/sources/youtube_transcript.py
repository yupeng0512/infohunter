"""YouTube 字幕/评论数据源 (ScrapeCreators)

辅助方案：字幕获取 + 评论获取 + 备用搜索。
复用已有 ScrapeCreators 账号，按量付费。
"""

from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from .base import SourceClient


class YouTubeTranscriptClient(SourceClient):
    """ScrapeCreators YouTube 字幕/评论客户端"""

    source_name = "youtube_transcript"
    BASE_URL = "https://api.scrapecreators.com/v1/youtube"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.scrapecreators_api_key
        if not self.api_key:
            logger.warning("ScrapeCreators API key not configured")

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _request(self, endpoint: str, params: dict) -> dict:
        """发送 API 请求"""
        url = f"{self.BASE_URL}/{endpoint}"
        self._log_request("GET", url=url, params=params)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url, params=params, headers=self._headers())
            if response.status_code != 200:
                logger.error(
                    f"ScrapeCreators YouTube error: {response.status_code} {response.text[:500]}"
                )
                response.raise_for_status()
            return response.json()

    async def search(
        self,
        query: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """ScrapeCreators YouTube 搜索 (备用)

        当 YouTube Data API v3 配额不足时使用。
        消耗: 1 credit/请求
        """
        if not self.api_key:
            return []

        try:
            params = {"query": query}
            data = await self._request("search", params)

            results = data.get("results", data.get("data", []))
            if not isinstance(results, list):
                return []

            items = []
            for item in results[:limit]:
                parsed = self._parse_search_result(item)
                if parsed:
                    items.append(parsed)

            return items

        except Exception as e:
            self._log_error("search", e)
            return []

    async def get_author_content(
        self,
        author_id: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """获取频道视频列表

        消耗: 1 credit/请求
        """
        if not self.api_key:
            return []

        try:
            params = {"channel_id": author_id}
            data = await self._request("channel/videos", params)

            videos = data.get("videos", data.get("data", []))
            if not isinstance(videos, list):
                return []

            items = []
            for video in videos[:limit]:
                parsed = self._parse_video(video)
                if parsed:
                    items.append(parsed)

            return items

        except Exception as e:
            self._log_error("get_author_content", e)
            return []

    async def get_detail(
        self,
        content_id: str,
        **kwargs,
    ) -> Optional[dict[str, Any]]:
        """获取视频详情

        消耗: 1 credit
        """
        if not self.api_key:
            return None

        try:
            params = {"video_id": content_id}
            data = await self._request("video/details", params)
            if data:
                return self._parse_video(data)
            return None
        except Exception as e:
            self._log_error("get_detail", e)
            return None

    async def get_transcript(
        self,
        content_id: str,
        **kwargs,
    ) -> Optional[str]:
        """获取视频字幕/文字稿

        消耗: 1 credit
        核心功能：比 youtube-transcript-api 更稳定可靠。
        """
        if not self.api_key:
            return None

        try:
            params = {"video_id": content_id}
            language = kwargs.get("language")
            if language:
                params["language"] = language

            data = await self._request("video/transcript", params)

            # 尝试多种响应格式
            transcript = data.get("transcript")
            if transcript:
                if isinstance(transcript, str):
                    return transcript
                if isinstance(transcript, list):
                    return "\n".join(
                        item.get("text", "") for item in transcript if item.get("text")
                    )

            # 备用: 直接返回 data 中的文本
            text = data.get("text", data.get("content"))
            if text:
                return text

            return None

        except Exception as e:
            self._log_error("get_transcript", e)
            return None

    async def get_comments(
        self,
        content_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取视频评论

        消耗: 1 credit
        最多返回约 7000 条评论。
        """
        if not self.api_key:
            return []

        try:
            params = {"video_id": content_id}
            data = await self._request("video/comments", params)

            comments = data.get("comments", data.get("data", []))
            if not isinstance(comments, list):
                return []

            results = []
            for comment in comments[:limit]:
                results.append({
                    "author": comment.get("author", comment.get("authorDisplayName", "")),
                    "text": comment.get("text", comment.get("textDisplay", "")),
                    "likes": comment.get("likes", comment.get("likeCount", 0)),
                    "published_at": comment.get("publishedAt", comment.get("published_at")),
                })

            return results

        except Exception as e:
            self._log_error("get_comments", e)
            return []

    async def get_channel_details(self, channel_id: str) -> Optional[dict]:
        """获取频道详情

        消耗: 1 credit
        """
        if not self.api_key:
            return None

        try:
            params = {"channel_id": channel_id}
            data = await self._request("channel/details", params)
            if not data:
                return None

            return {
                "channel_id": channel_id,
                "title": data.get("title", data.get("name", "")),
                "description": data.get("description", ""),
                "subscriber_count": data.get("subscriberCount", data.get("subscribers", 0)),
                "video_count": data.get("videoCount", data.get("videos", 0)),
                "view_count": data.get("viewCount", data.get("views", 0)),
                "thumbnail": data.get("thumbnail", data.get("avatar")),
                "raw_data": data,
            }

        except Exception as e:
            self._log_error("get_channel_details", e)
            return None

    def _parse_search_result(self, item: dict) -> Optional[dict[str, Any]]:
        """解析搜索结果"""
        video_id = item.get("videoId", item.get("video_id", item.get("id")))
        if not video_id:
            return None

        return {
            "content_id": str(video_id),
            "source": "youtube",
            "author": item.get("channelTitle", item.get("channel", "")),
            "author_id": item.get("channelId", item.get("channel_id", "")),
            "title": item.get("title", ""),
            "content": item.get("description", item.get("snippet", "")),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "metrics": {
                "views": self._parse_int(item.get("viewCount", item.get("views", 0))),
                "likes": self._parse_int(item.get("likeCount", item.get("likes", 0))),
                "comments": self._parse_int(item.get("commentCount", item.get("comments", 0))),
            },
            "posted_at": self._parse_datetime(
                item.get("publishedAt", item.get("published_at", item.get("publishDate")))
            ),
            "raw_data": item,
        }

    def _parse_video(self, video: dict) -> Optional[dict[str, Any]]:
        """解析视频数据"""
        video_id = video.get("videoId", video.get("video_id", video.get("id")))
        if not video_id:
            return None

        return {
            "content_id": str(video_id),
            "source": "youtube",
            "author": video.get("channelTitle", video.get("channel", "")),
            "author_id": video.get("channelId", video.get("channel_id", "")),
            "title": video.get("title", ""),
            "content": video.get("description", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "metrics": {
                "views": self._parse_int(video.get("viewCount", video.get("views", 0))),
                "likes": self._parse_int(video.get("likeCount", video.get("likes", 0))),
                "comments": self._parse_int(video.get("commentCount", video.get("comments", 0))),
            },
            "posted_at": self._parse_datetime(
                video.get("publishedAt", video.get("published_at", video.get("publishDate")))
            ),
            "duration": video.get("duration", video.get("lengthText")),
            "thumbnail": video.get("thumbnail", video.get("thumbnails", [{}])[0].get("url") if isinstance(video.get("thumbnails"), list) else None),
            "raw_data": video,
        }

    @staticmethod
    def _parse_int(value) -> int:
        """安全解析整数"""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _parse_datetime(dt_str) -> Optional[datetime]:
        """解析日期"""
        if not dt_str or not isinstance(dt_str, str):
            return None
        for fmt in [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None
