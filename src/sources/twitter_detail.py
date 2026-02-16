"""Twitter 详情数据源 (ScrapeCreators)

辅助方案：博主 Profile / 推文详情 / 视频字幕。
复用已有 ScrapeCreators 账号。
"""

from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from .base import SourceClient


class TwitterDetailClient(SourceClient):
    """ScrapeCreators Twitter 详情客户端"""

    source_name = "twitter_detail"
    BASE_URL = "https://api.scrapecreators.com/v1/twitter"

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
        url = f"{self.BASE_URL}/{endpoint}"
        self._log_request("GET", url=url, params=params)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params, headers=self._headers())
            if response.status_code != 200:
                logger.error(
                    f"ScrapeCreators error: {response.status_code} {response.text[:500]}"
                )
                response.raise_for_status()
            return response.json()

    async def search(self, query: str, limit: int = 20, **kwargs) -> list[dict[str, Any]]:
        """ScrapeCreators 不支持 Twitter 搜索，返回空"""
        logger.debug("ScrapeCreators does not support Twitter keyword search")
        return []

    async def get_author_content(
        self, author_id: str, limit: int = 20, **kwargs
    ) -> list[dict[str, Any]]:
        """获取用户热门推文 (注意: 只返回约 100 条最热门推文)"""
        if not self.api_key:
            return []

        try:
            data = await self._request("user-tweets", {"handle": author_id})
            tweets = data.get("tweets", data.get("data", []))
            if isinstance(tweets, list):
                return [self._parse_tweet(t) for t in tweets[:limit]]
            return []
        except Exception as e:
            self._log_error("get_author_content", e)
            return []

    async def get_profile(self, username: str) -> Optional[dict[str, Any]]:
        """获取用户 Profile"""
        if not self.api_key:
            return None

        try:
            data = await self._request("profile", {"handle": username})
            return data
        except Exception as e:
            self._log_error("get_profile", e)
            return None

    async def get_detail(self, content_id: str, **kwargs) -> Optional[dict[str, Any]]:
        """获取推文详情"""
        if not self.api_key:
            return None

        try:
            data = await self._request("tweet", {"tweet_id": content_id})
            if data:
                return self._parse_tweet(data)
            return None
        except Exception as e:
            self._log_error("get_detail", e)
            return None

    async def get_transcript(self, content_id: str, **kwargs) -> Optional[str]:
        """获取视频推文的 AI 转录字幕"""
        if not self.api_key:
            return None

        try:
            data = await self._request("tweet/transcript", {"tweet_id": content_id})
            return data.get("transcript", None)
        except Exception as e:
            self._log_error("get_transcript", e)
            return None

    def _parse_tweet(self, tweet: dict) -> dict[str, Any]:
        """解析推文为标准格式"""
        posted_at = None
        created_at_str = tweet.get("created_at", tweet.get("createdAt", ""))
        if created_at_str:
            for fmt in [
                "%a %b %d %H:%M:%S %z %Y",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
            ]:
                try:
                    posted_at = datetime.strptime(created_at_str, fmt)
                    break
                except ValueError:
                    continue

        user = tweet.get("user", tweet.get("author", {}))

        metrics = {
            "retweets": tweet.get("retweet_count", tweet.get("retweetCount", 0)),
            "likes": tweet.get("favorite_count", tweet.get("likeCount", 0)),
            "replies": tweet.get("reply_count", tweet.get("replyCount", 0)),
            "views": tweet.get("view_count", tweet.get("viewCount", 0)),
        }

        tweet_id = str(tweet.get("id", tweet.get("id_str", "")))

        return {
            "content_id": tweet_id,
            "source": "twitter",
            "author": user.get("name", ""),
            "author_id": user.get("screen_name", user.get("userName", "")),
            "title": None,
            "content": tweet.get("full_text", tweet.get("text", "")),
            "url": f"https://x.com/i/status/{tweet_id}",
            "metrics": metrics,
            "posted_at": posted_at,
            "raw_data": tweet,
        }
