"""Twitter 搜索数据源 (TwitterAPI.io)

主力方案：关键词搜索 + 话题监控。
API 文档: https://twitterapi.io/docs
定价: $0.15/千条推文
"""

from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from .base import SourceClient


class TwitterSearchClient(SourceClient):
    """TwitterAPI.io 搜索客户端"""

    source_name = "twitter_search"
    BASE_URL = "https://api.twitterapi.io/twitter"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.twitterapi_io_key
        if not self.api_key:
            logger.warning("TwitterAPI.io API key not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _request(
        self, method: str, endpoint: str, params: Optional[dict] = None
    ) -> dict:
        """发送 API 请求"""
        url = f"{self.BASE_URL}/{endpoint}"
        self._log_request(method, url=url, params=params)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, url, params=params, headers=self._headers()
            )
            if response.status_code != 200:
                logger.error(
                    f"TwitterAPI.io error: {response.status_code} {response.text[:500]}"
                )
                response.raise_for_status()
            return response.json()

    async def search(
        self,
        query: str,
        limit: int = 20,
        sort: str = "Latest",
        **kwargs,
    ) -> list[dict[str, Any]]:
        """搜索推文

        Args:
            query: 搜索查询 (支持高级语法: "AI" OR "LLM" from:sama since:2026-01-01)
            limit: 返回数量
            sort: 排序方式 "Latest" / "Top"
        """
        if not self.api_key:
            logger.warning("TwitterAPI.io not configured, skipping search")
            return []

        all_tweets = []
        cursor = None
        pages = (limit + 19) // 20  # 每页 20 条

        for page in range(pages):
            params = {
                "query": query,
                "queryType": sort,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                data = await self._request("GET", "tweet/advanced_search", params=params)
                tweets = data.get("tweets", [])
                cursor = data.get("next_cursor")

                for tweet in tweets:
                    parsed = self._parse_tweet(tweet)
                    all_tweets.append(parsed)

                if not cursor or len(tweets) == 0:
                    break

            except Exception as e:
                self._log_error("search", e)
                break

        logger.info(f"Twitter search '{query}': found {len(all_tweets)} tweets")
        return all_tweets[:limit]

    async def get_author_content(
        self,
        author_id: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """获取用户时间线

        Args:
            author_id: Twitter 用户名 (不含 @)
        """
        if not self.api_key:
            return []

        params = {"userName": author_id}

        try:
            data = await self._request("GET", "user/last_tweets", params=params)
            # 响应可能是 {tweets: [...]} 或 {data: {tweets: [...]}}
            tweets = data.get("tweets", [])
            if not tweets and isinstance(data.get("data"), dict):
                inner = data["data"]
                tweets = inner.get("tweets", [])
            results = [self._parse_tweet(t) for t in tweets[:limit]]
            logger.info(f"Twitter user @{author_id}: found {len(results)} tweets")
            return results
        except Exception as e:
            self._log_error("get_author_content", e)
            return []

    async def get_trends(
        self,
        woeid: int = 1,
        count: int = 30,
    ) -> list[dict[str, Any]]:
        """获取 Twitter 热门趋势

        Args:
            woeid: 地区 ID (1=全球, 23424977=美国, 23424868=中国)
            count: 趋势数量，默认 30
        """
        if not self.api_key:
            return []

        try:
            params = {"woeid": woeid, "count": count}
            data = await self._request("GET", "trends", params=params)
            trends = data.get("trends", [])

            results = []
            for trend in trends:
                target = trend.get("target", {})
                results.append({
                    "name": trend.get("name", ""),
                    "query": target.get("query", ""),
                    "rank": target.get("rank", 0),
                    "tweet_count": target.get("meta_description", ""),
                })

            logger.info(f"Twitter trends (woeid={woeid}): {len(results)} trends")
            return results

        except Exception as e:
            self._log_error("get_trends", e)
            return []

    def _parse_tweet(self, tweet: dict) -> dict[str, Any]:
        """解析推文数据为标准格式"""
        author = tweet.get("author", {})
        posted_at = None
        created_at_str = tweet.get("createdAt", "")
        if created_at_str:
            try:
                # TwitterAPI.io 返回格式: "Mon Feb 10 12:00:00 +0000 2026"
                posted_at = datetime.strptime(
                    created_at_str, "%a %b %d %H:%M:%S %z %Y"
                )
            except ValueError:
                try:
                    posted_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

        # 提取互动指标
        metrics = {
            "retweets": tweet.get("retweetCount", 0),
            "replies": tweet.get("replyCount", 0),
            "likes": tweet.get("likeCount", 0),
            "quotes": tweet.get("quoteCount", 0),
            "views": tweet.get("viewCount", 0),
            "bookmarks": tweet.get("bookmarkCount", 0),
        }

        # 提取媒体
        media = None
        if tweet.get("media"):
            media = tweet["media"]

        return {
            "content_id": tweet.get("id", ""),
            "source": "twitter",
            "author": author.get("name", ""),
            "author_id": author.get("userName", ""),
            "title": None,
            "content": tweet.get("text", ""),
            "url": tweet.get("url", f"https://x.com/i/status/{tweet.get('id', '')}"),
            "metrics": metrics,
            "media_attachments": media,
            "posted_at": posted_at,
            "raw_data": tweet,
        }
