"""YouTube 数据源 (Data API v3)

主力方案：搜索/视频详情/频道信息。
支持 API Key 和 OAuth 2.0 两种认证方式。
OAuth 2.0 用于 API Key 被限制的场景。
"""

import time
from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from .base import SourceClient


class YouTubeClient(SourceClient):
    """YouTube Data API v3 客户端

    认证优先级：
    1. OAuth 2.0 (如果配置了 refresh_token)
    2. API Key (简单但可能被限制)
    """

    source_name = "youtube"
    BASE_URL = "https://www.googleapis.com/youtube/v3"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.youtube_api_key

        # OAuth 2.0 配置
        self._oauth_client_id = settings.youtube_oauth_client_id
        self._oauth_client_secret = settings.youtube_oauth_client_secret
        self._oauth_refresh_token = settings.youtube_oauth_refresh_token
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        self._use_oauth = bool(
            self._oauth_client_id
            and self._oauth_client_secret
            and self._oauth_refresh_token
        )

        if self._use_oauth:
            logger.info("YouTube client: OAuth 2.0 mode")
        elif self.api_key:
            logger.info("YouTube client: API Key mode")
        else:
            logger.warning("YouTube Data API not configured")

    async def _refresh_access_token(self) -> bool:
        """刷新 OAuth 2.0 Access Token"""
        if not self._use_oauth:
            return False

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self._oauth_client_id,
                        "client_secret": self._oauth_client_secret,
                        "refresh_token": self._oauth_refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                if resp.status_code != 200:
                    logger.error(f"YouTube OAuth token refresh failed: {resp.status_code} {resp.text[:300]}")
                    return False

                data = resp.json()
                self._access_token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60
                logger.debug("YouTube OAuth access token refreshed")
                return True

        except Exception as e:
            logger.error(f"YouTube OAuth token refresh error: {e}")
            return False

    async def _ensure_token(self) -> bool:
        """确保有有效的 access token"""
        if not self._use_oauth:
            return False
        if self._access_token and time.time() < self._token_expires_at:
            return True
        return await self._refresh_access_token()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _request(self, endpoint: str, params: dict) -> dict:
        """发送 API 请求 (自动选择 OAuth 或 API Key)"""
        url = f"{self.BASE_URL}/{endpoint}"
        headers = {}

        if self._use_oauth and await self._ensure_token():
            headers["Authorization"] = f"Bearer {self._access_token}"
        elif self.api_key:
            params["key"] = self.api_key
        else:
            logger.error("YouTube: no auth configured")
            return {"items": []}

        self._log_request("GET", url=url, params={k: v for k, v in params.items() if k != "key"})

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params, headers=headers)

            if response.status_code == 401 and self._use_oauth:
                logger.warning("YouTube OAuth token expired, refreshing...")
                if await self._refresh_access_token():
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    response = await client.get(url, params=params, headers=headers)

            if response.status_code == 403:
                error_text = response.text[:300]
                if "API_KEY_SERVICE_BLOCKED" in error_text and not self._use_oauth:
                    logger.error("YouTube API Key blocked. Configure OAuth 2.0 to resolve.")
                else:
                    logger.error(f"YouTube API forbidden: {error_text}")
                return {"items": []}
            if response.status_code != 200:
                logger.error(f"YouTube API error: {response.status_code} {response.text[:500]}")
                response.raise_for_status()
            return response.json()

    async def search(
        self,
        query: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """搜索 YouTube 视频

        配额消耗: 100 单位/次
        """
        if not self.api_key and not self._use_oauth:
            return []

        try:
            order = kwargs.get("order", "relevance")
            published_after = kwargs.get("published_after")
            video_type = kwargs.get("type", "video")

            params = {
                "part": "snippet",
                "q": query,
                "type": video_type,
                "maxResults": min(limit, 50),
                "order": order,
                "relevanceLanguage": kwargs.get("language", "en"),
            }

            if published_after:
                params["publishedAfter"] = published_after

            data = await self._request("search", params)
            items = data.get("items", [])

            if not items:
                return []

            # 获取视频详情 (播放量等)
            video_ids = [
                item["id"]["videoId"]
                for item in items
                if item.get("id", {}).get("videoId")
            ]

            details = {}
            if video_ids:
                details = await self._get_videos_details(video_ids)

            results = []
            for item in items:
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue

                parsed = self._parse_search_item(item)
                if video_id in details:
                    parsed["metrics"] = details[video_id]["metrics"]
                    parsed["raw_data"].update(details[video_id].get("statistics", {}))

                results.append(parsed)

            return results

        except Exception as e:
            self._log_error("search", e)
            return []

    async def get_author_content(
        self,
        author_id: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """获取频道最新视频

        优先使用 activities API (1 单位) 代替 search (100 单位)。
        """
        if not self.api_key and not self._use_oauth:
            return []

        try:
            channel_id = author_id
            if not author_id.startswith("UC"):
                channel_id = await self._resolve_channel_id(author_id)
                if not channel_id:
                    logger.warning(f"无法解析频道 ID: {author_id}")
                    return []

            # 优先用 activities API (1 单位 vs search 的 100 单位)
            results = await self.get_channel_activities(
                channel_id, limit=limit
            )
            if results:
                return results

            # 回退到 search API
            logger.debug(f"Activities API 无结果，回退到 search: {channel_id}")
            params = {
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "maxResults": min(limit, 50),
                "order": "date",
            }

            data = await self._request("search", params)
            items = data.get("items", [])

            if not items:
                return []

            video_ids = [
                item["id"]["videoId"]
                for item in items
                if item.get("id", {}).get("videoId")
            ]

            details = {}
            if video_ids:
                details = await self._get_videos_details(video_ids)

            results = []
            for item in items:
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue

                parsed = self._parse_search_item(item)
                if video_id in details:
                    parsed["metrics"] = details[video_id]["metrics"]

                results.append(parsed)

            return results

        except Exception as e:
            self._log_error("get_author_content", e)
            return []

    async def get_detail(
        self,
        content_id: str,
        **kwargs,
    ) -> Optional[dict[str, Any]]:
        """获取视频详情

        配额消耗: 1 单位
        """
        if not self.api_key and not self._use_oauth:
            return None

        try:
            details = await self._get_videos_details([content_id])
            if content_id in details:
                return details[content_id]
            return None
        except Exception as e:
            self._log_error("get_detail", e)
            return None

    async def get_channel_info(self, channel_id: str) -> Optional[dict]:
        """获取频道信息

        配额消耗: 1 单位
        """
        if not self.api_key and not self._use_oauth:
            return None

        try:
            params = {
                "part": "snippet,statistics,contentDetails",
                "id": channel_id,
            }
            data = await self._request("channels", params)
            items = data.get("items", [])
            if not items:
                return None

            channel = items[0]
            snippet = channel.get("snippet", {})
            stats = channel.get("statistics", {})

            return {
                "channel_id": channel_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "view_count": int(stats.get("viewCount", 0)),
                "published_at": snippet.get("publishedAt"),
            }

        except Exception as e:
            self._log_error("get_channel_info", e)
            return None

    async def get_trending(
        self,
        region_code: str = "US",
        category_id: str = "28",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取热门视频 (mostPopular)

        配额消耗: 1 单位 (比 search 便宜 100 倍)

        Args:
            region_code: 地区代码 (US, CN, JP)
            category_id: 视频类别 (28=Science & Technology, 0=全部)
            limit: 返回数量
        """
        try:
            params = {
                "part": "snippet,statistics,contentDetails",
                "chart": "mostPopular",
                "regionCode": region_code,
                "maxResults": min(limit, 50),
            }
            if category_id and category_id != "0":
                params["videoCategoryId"] = category_id

            data = await self._request("videos", params)
            items = data.get("items", [])

            results = []
            for item in items:
                video_id = item.get("id")
                if not video_id:
                    continue

                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})

                results.append({
                    "content_id": video_id,
                    "source": "youtube",
                    "author": snippet.get("channelTitle", ""),
                    "author_id": snippet.get("channelId", ""),
                    "title": snippet.get("title", ""),
                    "content": snippet.get("description", ""),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "metrics": {
                        "views": int(stats.get("viewCount", 0)),
                        "likes": int(stats.get("likeCount", 0)),
                        "comments": int(stats.get("commentCount", 0)),
                    },
                    "posted_at": self._parse_datetime(snippet.get("publishedAt")),
                    "raw_data": item,
                })

            logger.info(f"YouTube trending ({region_code}): {len(results)} videos")
            return results

        except Exception as e:
            self._log_error("get_trending", e)
            return []

    async def get_channel_activities(
        self,
        channel_id: str,
        limit: int = 20,
        published_after: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取频道活动 (新上传等)

        配额消耗: 1 单位 (比 search 便宜 100 倍)
        适合频道订阅场景。

        Args:
            channel_id: 频道 ID (UC 开头)
            limit: 返回数量
            published_after: ISO 8601 时间过滤
        """
        try:
            params = {
                "part": "snippet,contentDetails",
                "channelId": channel_id,
                "maxResults": min(limit, 50),
            }
            if published_after:
                params["publishedAfter"] = published_after

            data = await self._request("activities", params)
            items = data.get("items", [])

            video_ids = []
            for item in items:
                content_details = item.get("contentDetails", {})
                upload = content_details.get("upload", {})
                video_id = upload.get("videoId")
                if video_id:
                    video_ids.append(video_id)

            if not video_ids:
                return []

            details = await self._get_videos_details(video_ids[:limit])
            results = list(details.values())
            logger.info(f"YouTube channel activities ({channel_id}): {len(results)} videos")
            return results

        except Exception as e:
            self._log_error("get_channel_activities", e)
            return []

    async def _get_videos_details(self, video_ids: list[str]) -> dict[str, dict]:
        """批量获取视频详情

        配额消耗: 1 单位/视频 (最多 50 个)
        """
        if not video_ids:
            return {}

        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids[:50]),
        }

        data = await self._request("videos", params)
        items = data.get("items", [])

        result = {}
        for item in items:
            video_id = item.get("id")
            if not video_id:
                continue

            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content_details = item.get("contentDetails", {})

            result[video_id] = {
                "content_id": video_id,
                "source": "youtube",
                "author": snippet.get("channelTitle", ""),
                "author_id": snippet.get("channelId", ""),
                "title": snippet.get("title", ""),
                "content": snippet.get("description", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "metrics": {
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                },
                "posted_at": self._parse_datetime(snippet.get("publishedAt")),
                "duration": content_details.get("duration"),
                "statistics": stats,
                "raw_data": item,
            }

        return result

    async def _resolve_channel_id(self, query: str) -> Optional[str]:
        """通过搜索解析频道 ID

        配额消耗: 100 单位
        """
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": 1,
            }
            data = await self._request("search", params)
            items = data.get("items", [])
            if items:
                return items[0].get("id", {}).get("channelId")
            return None
        except Exception as e:
            self._log_error("_resolve_channel_id", e)
            return None

    def _parse_search_item(self, item: dict) -> dict[str, Any]:
        """解析搜索结果为标准格式"""
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")

        return {
            "content_id": video_id,
            "source": "youtube",
            "author": snippet.get("channelTitle", ""),
            "author_id": snippet.get("channelId", ""),
            "title": snippet.get("title", ""),
            "content": snippet.get("description", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "metrics": {
                "views": 0,
                "likes": 0,
                "comments": 0,
            },
            "posted_at": self._parse_datetime(snippet.get("publishedAt")),
            "raw_data": item,
        }

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """解析 ISO 8601 日期"""
        if not dt_str:
            return None
        for fmt in [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S%z",
        ]:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None
