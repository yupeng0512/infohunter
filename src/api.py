"""InfoHunter REST API

FastAPI 应用，提供订阅管理、内容查询、系统状态等接口。
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from loguru import logger

from src.config import settings
from src.storage.database import get_db_manager
from src.subscription.manager import SubscriptionManager
from pydantic import BaseModel, Field
from src.subscription.models import (
    ContentResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
)


class AnalyzeUrlRequest(BaseModel):
    url: str = Field(..., description="Twitter or YouTube URL to analyze")


class AnalyzeAuthorRequest(BaseModel):
    author_id: str = Field(..., description="Twitter username or YouTube channel ID")
    source: str = Field(default="twitter", description="Platform: twitter or youtube")

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(
    title="InfoHunter API",
    description="社交媒体 AI 智能订阅监控系统",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 懒初始化
_db = None
_sub_manager = None


def get_db():
    global _db
    if _db is None:
        _db = get_db_manager()
    return _db


def get_sub_mgr():
    global _sub_manager
    if _sub_manager is None:
        _sub_manager = SubscriptionManager(get_db())
    return _sub_manager


# ===== 前端页面 =====


@app.get("/")
async def index():
    """Web 管理面板"""
    return FileResponse(WEB_DIR / "index.html")


# ===== 健康检查 =====


@app.get("/api/health")
async def health():
    db = get_db()
    return {
        "status": "ok",
        "subscriptions": db.get_subscription_count(),
        "contents": db.get_content_count(),
        "twitter_contents": db.get_content_count(source="twitter"),
        "youtube_contents": db.get_content_count(source="youtube"),
    }


# ===== 订阅管理 =====


@app.post("/api/subscriptions", response_model=SubscriptionResponse)
async def create_subscription(data: SubscriptionCreate):
    """创建订阅"""
    mgr = get_sub_mgr()
    sub = mgr.create(data.model_dump())
    return SubscriptionResponse.model_validate(sub)


@app.get("/api/subscriptions", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    source: Optional[str] = Query(None, description="过滤数据源: twitter/youtube"),
    status: str = Query("active", description="过滤状态: active/paused/deleted"),
):
    """列出订阅"""
    mgr = get_sub_mgr()
    subs = mgr.list_all(source=source, status=status)
    return [SubscriptionResponse.model_validate(s) for s in subs]


@app.get("/api/subscriptions/{sub_id}", response_model=SubscriptionResponse)
async def get_subscription(sub_id: int):
    """获取订阅详情"""
    mgr = get_sub_mgr()
    sub = mgr.get(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return SubscriptionResponse.model_validate(sub)


@app.put("/api/subscriptions/{sub_id}", response_model=SubscriptionResponse)
async def update_subscription(sub_id: int, data: SubscriptionUpdate):
    """更新订阅"""
    mgr = get_sub_mgr()
    sub = mgr.update(sub_id, data.model_dump(exclude_unset=True))
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return SubscriptionResponse.model_validate(sub)


@app.delete("/api/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int):
    """删除订阅"""
    mgr = get_sub_mgr()
    if not mgr.delete(sub_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "deleted"}


# ===== 内容查询 =====


@app.get("/api/contents", response_model=list[ContentResponse])
async def list_contents(
    subscription_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """查询内容"""
    db = get_db()
    if subscription_id:
        contents = db.get_contents_by_subscription(subscription_id, limit=limit)
    else:
        contents = db.get_contents_for_report(
            since=datetime(2020, 1, 1), source=source, limit=limit
        )
    return [ContentResponse.model_validate(c) for c in contents]


@app.get("/api/contents/unanalyzed", response_model=list[ContentResponse])
async def list_unanalyzed(limit: int = Query(50, ge=1, le=200)):
    """获取未分析的内容"""
    db = get_db()
    contents = db.get_unanalyzed_contents(limit=limit)
    return [ContentResponse.model_validate(c) for c in contents]


# ===== 手动触发 =====


@app.post("/api/trigger/fetch")
async def trigger_fetch():
    """手动触发一轮采集"""
    from src.main import InfoHunter

    hunter = InfoHunter()
    try:
        await hunter.init()
        await hunter.run_fetch_cycle()
        return {"status": "ok", "message": "Fetch cycle triggered"}
    except Exception as e:
        logger.error(f"Trigger fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            await hunter.stop()
        except Exception:
            pass


@app.post("/api/trigger/daily-report")
async def trigger_daily_report():
    """手动触发日报"""
    from src.main import InfoHunter

    hunter = InfoHunter()
    try:
        await hunter.init()
        await hunter.send_daily_report()
        return {"status": "ok", "message": "Daily report triggered"}
    except Exception as e:
        logger.error(f"Trigger daily report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            await hunter.stop()
        except Exception:
            pass


# ===== YouTube OAuth 2.0 =====


@app.get("/api/youtube/oauth/authorize")
async def youtube_oauth_authorize(
    redirect_host: str = Query(default="localhost:6003", description="回调地址 host:port"),
):
    """获取 YouTube OAuth 2.0 授权 URL

    步骤:
    1. 访问返回的 auth_url 完成 Google 授权
    2. 授权后自动回调到 /api/youtube/oauth/callback
    3. 将返回的 refresh_token 配置到 .env
    """
    from urllib.parse import quote

    client_id = settings.youtube_oauth_client_id
    if not client_id:
        raise HTTPException(status_code=400, detail="YOUTUBE_OAUTH_CLIENT_ID not configured")

    redirect_uri = f"http://{redirect_host}/api/youtube/oauth/callback"

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}"
        f"&redirect_uri={quote(redirect_uri)}"
        "&response_type=code"
        "&scope=https://www.googleapis.com/auth/youtube.readonly"
        "&access_type=offline"
        "&prompt=consent"
    )

    return {
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "note": "请确保 Google Cloud Console 的 OAuth 客户端已添加此重定向 URI",
    }


@app.get("/api/youtube/oauth/callback")
async def youtube_oauth_callback(
    code: str = Query(None, description="Authorization code from Google"),
    error: str = Query(None, description="Error from Google"),
):
    """YouTube OAuth 2.0 回调

    Google 授权后自动重定向到此端点，换取 refresh_token。
    """
    if error:
        return {"status": "error", "error": error}

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    import httpx

    client_id = settings.youtube_oauth_client_id
    client_secret = settings.youtube_oauth_client_secret
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="YouTube OAuth not configured")

    # 需要和授权时用的 redirect_uri 完全一致
    # 从 Referer 或默认推断
    redirect_uri = "http://localhost:6003/api/youtube/oauth/callback"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )

    if resp.status_code != 200:
        return {
            "status": "error",
            "detail": f"Token exchange failed: {resp.text[:500]}",
        }

    data = resp.json()
    refresh_token = data.get("refresh_token", "")

    return {
        "status": "ok",
        "refresh_token": refresh_token,
        "expires_in": data.get("expires_in"),
        "instructions": f"将以下内容添加到 .env 文件:\nYOUTUBE_OAUTH_REFRESH_TOKEN={refresh_token}",
    }


# ===== 交互式分析 =====


@app.post("/api/analyze/url")
async def analyze_url(data: AnalyzeUrlRequest):
    """即时分析链接

    发送 Twitter/YouTube 链接，即时获取内容详情 + AI 分析。
    """
    url = data.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    from src.analyzer.content_analyzer import get_content_analyzer

    result = {"url": url, "source": None, "content": None, "analysis": None, "error": None}

    try:
        # 解析链接类型
        content_data = None

        if "twitter.com" in url or "x.com" in url:
            result["source"] = "twitter"
            content_data = await _fetch_twitter_url(url)

        elif "youtube.com" in url or "youtu.be" in url:
            result["source"] = "youtube"
            content_data = await _fetch_youtube_url(url)

        else:
            raise HTTPException(status_code=400, detail="Unsupported URL. Only Twitter and YouTube links are supported.")

        if not content_data:
            result["error"] = "Failed to fetch content"
            return result

        result["content"] = content_data

        # AI 分析
        analyzer = get_content_analyzer()
        analysis_result = await analyzer.analyze_content(
            content=content_data.get("content", ""),
            source=result["source"],
            title=content_data.get("title"),
            author=content_data.get("author"),
            metrics=content_data.get("metrics"),
            transcript=content_data.get("transcript"),
        )

        if analysis_result["status"] == "success":
            result["analysis"] = analysis_result["analysis"]
        elif analysis_result["status"] == "disabled":
            result["analysis"] = {"note": "AI analysis is not configured"}
        else:
            result["error"] = analysis_result.get("error", "Analysis failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"URL analysis failed: {e}")
        result["error"] = str(e)

    return result


@app.post("/api/analyze/author")
async def analyze_author(data: AnalyzeAuthorRequest):
    """分析博主/频道

    发送用户名或频道 ID，获取博主信息 + 最新内容 + AI 评估。
    """
    author_id = data.author_id.strip()
    source = data.source.strip()

    if not author_id:
        raise HTTPException(status_code=400, detail="author_id is required")

    from src.analyzer.content_analyzer import get_content_analyzer

    result = {"author_id": author_id, "source": source, "profile": None, "recent_contents": [], "analysis": None, "error": None}

    try:
        if source == "twitter":
            result["profile"], result["recent_contents"] = await _fetch_twitter_author(author_id)
        elif source == "youtube":
            result["profile"], result["recent_contents"] = await _fetch_youtube_author(author_id)
        else:
            raise HTTPException(status_code=400, detail="source must be 'twitter' or 'youtube'")

        # AI 评估 - 使用博主评估 Agent
        if result["recent_contents"]:
            from src.analyzer.agui_client import AGUIClient, create_recommend_agent

            recommend_agent = create_recommend_agent()
            if not recommend_agent:
                result["analysis"] = {"note": "AI analysis is not configured"}
            else:
                prompt_text = _build_author_analysis_prompt(
                    author_id=author_id,
                    source=source,
                    profile=result["profile"],
                    contents=result["recent_contents"],
                )

                response = await recommend_agent.chat(message=prompt_text, temperature=0.3)

                if response.get("error"):
                    result["error"] = response["error"]
                else:
                    analysis = AGUIClient.extract_json(response.get("content", ""))
                    result["analysis"] = analysis or {"raw_response": response.get("content", "")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Author analysis failed: {e}")
        result["error"] = str(e)

    return result


# ===== 交互式分析辅助函数 =====


async def _fetch_twitter_url(url: str) -> dict | None:
    """从 Twitter URL 获取内容"""
    import re

    match = re.search(r"/status/(\d+)", url)
    if not match:
        return None

    tweet_id = match.group(1)

    # 方案 1: TwitterAPI.io (通过 tweet ID 获取，格式标准)
    if settings.twitterapi_io_key:
        from src.sources.twitter_search import TwitterSearchClient

        client = TwitterSearchClient()
        try:
            data = await client._request("GET", "tweets", params={"tweet_ids": tweet_id})
            tweets = data.get("tweets", [])
            if tweets:
                return client._parse_tweet(tweets[0])
        except Exception as e:
            logger.warning(f"TwitterAPI.io fetch tweet failed: {e}")

    # 方案 2: ScrapeCreators (推文详情，备用)
    if settings.scrapecreators_api_key:
        from src.sources.twitter_detail import TwitterDetailClient

        client = TwitterDetailClient()
        detail = await client.get_detail(tweet_id)
        if detail:
            return detail

    return None


async def _fetch_youtube_url(url: str) -> dict | None:
    """从 YouTube URL 获取内容"""
    import re

    video_id = None
    match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
    if match:
        video_id = match.group(1)
    else:
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
        if match:
            video_id = match.group(1)

    if not video_id:
        return None

    content_data = None

    # YouTube Data API v3
    if settings.youtube_api_key:
        from src.sources.youtube import YouTubeClient

        client = YouTubeClient()
        detail = await client.get_detail(video_id)
        if detail:
            content_data = detail

    # ScrapeCreators 字幕
    if settings.scrapecreators_api_key:
        from src.sources.youtube_transcript import YouTubeTranscriptClient

        tc = YouTubeTranscriptClient()

        if not content_data:
            content_data = await tc.get_detail(video_id)

        if content_data:
            transcript = await tc.get_transcript(video_id)
            if transcript:
                content_data["transcript"] = transcript

            comments = await tc.get_comments(video_id, limit=20)
            if comments:
                content_data["top_comments"] = comments

    return content_data


async def _fetch_twitter_author(author_id: str) -> tuple[dict | None, list]:
    """获取 Twitter 博主信息"""
    author_id = author_id.lstrip("@")
    profile = None
    contents = []

    # 获取 Profile (ScrapeCreators)
    if settings.scrapecreators_api_key:
        from src.sources.twitter_detail import TwitterDetailClient

        client = TwitterDetailClient()
        profile = await client.get_profile(author_id)

    # 获取内容 - 优先 TwitterAPI.io（格式标准，内容完整）
    if settings.twitterapi_io_key:
        from src.sources.twitter_search import TwitterSearchClient

        search_client = TwitterSearchClient()
        contents = await search_client.get_author_content(author_id, limit=10)

    # 备用: ScrapeCreators
    if not contents and settings.scrapecreators_api_key:
        from src.sources.twitter_detail import TwitterDetailClient

        detail_client = TwitterDetailClient()
        contents = await detail_client.get_author_content(author_id, limit=10)

    return profile, contents


async def _fetch_youtube_author(channel_id: str) -> tuple[dict | None, list]:
    """获取 YouTube 频道信息"""
    profile = None
    contents = []

    if settings.youtube_api_key:
        from src.sources.youtube import YouTubeClient

        client = YouTubeClient()
        profile = await client.get_channel_info(channel_id)
        contents_raw = await client.get_author_content(channel_id, limit=10)
        contents = contents_raw

    if not contents and settings.scrapecreators_api_key:
        from src.sources.youtube_transcript import YouTubeTranscriptClient

        client = YouTubeTranscriptClient()
        if not profile:
            profile = await client.get_channel_details(channel_id)
        contents = await client.get_author_content(channel_id, limit=10)

    return profile, contents


def _build_author_analysis_prompt(
    author_id: str,
    source: str,
    profile: dict | None,
    contents: list[dict],
) -> str:
    """构建博主分析 Prompt"""
    import json
    from pathlib import Path

    prompt_path = Path(__file__).parent.parent / "config" / "prompts" / "recommend_evaluation.txt"
    if prompt_path.exists():
        template = prompt_path.read_text(encoding="utf-8")
        return template.format(
            author_id=author_id,
            source=source,
            profile=json.dumps(profile or {}, ensure_ascii=False, indent=2),
            contents=json.dumps(
                [
                    {
                        "title": c.get("title", ""),
                        "content": (c.get("content", "") or "")[:200],
                        "metrics": c.get("metrics", {}),
                    }
                    for c in contents[:10]
                ],
                ensure_ascii=False,
                indent=2,
            ),
        )

    # Default prompt
    contents_summary = "\n".join(
        f"- {c.get('title') or (c.get('content', '')[:100])}"
        for c in contents[:10]
    )

    return f"""请评估以下 {source} 博主是否值得订阅：

博主: {author_id}
平台: {source}
个人资料: {json.dumps(profile or {}, ensure_ascii=False)}

最近内容:
{contents_summary}

请输出 JSON 格式的评估报告：
- summary: 博主一句话概述 (中文)
- topics: 主要涉及话题列表
- content_quality: 内容质量评分 (1-10)
- update_frequency: 更新频率评估
- audience_fit: 适合什么样的读者
- subscribe_recommendation: 是否推荐订阅 (true/false)
- recommendation_reason: 推荐/不推荐理由 (中文)

请直接输出 JSON。"""
