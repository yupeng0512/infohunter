"""InfoHunter REST API

FastAPI 应用，提供订阅管理、内容查询、系统状态等接口。
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


# ===== 全局 InfoHunter 实例（用于 trigger 端点复用） =====
_hunter_instance = None
_hunter_lock = asyncio.Lock()


async def get_hunter():
    """获取或创建全局 InfoHunter 实例（懒加载 + 线程安全）"""
    global _hunter_instance
    if _hunter_instance is None:
        async with _hunter_lock:
            if _hunter_instance is None:
                from src.main import InfoHunter
                _hunter_instance = InfoHunter()
                await _hunter_instance.init()
                logger.info("全局 InfoHunter 实例已初始化")
    return _hunter_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: 启动时无需预创建，关闭时清理全局实例"""
    yield
    global _hunter_instance
    if _hunter_instance is not None:
        try:
            await _hunter_instance.stop()
            logger.info("全局 InfoHunter 实例已关闭")
        except Exception as e:
            logger.warning(f"关闭 InfoHunter 实例时出错: {e}")
        _hunter_instance = None


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
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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


def _get_config_value(db, key: str):
    """从 SystemConfig 数据库中读取配置值，返回 dict 或 None"""
    try:
        cfg = db.get_system_config(key)
        return cfg.config_value if cfg else None
    except Exception:
        return None


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
        "blog_contents": db.get_content_count(source="blog"),
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
    source: Optional[str] = Query(None, description="过滤数据源: twitter/youtube/blog"),
    type: Optional[str] = Query(None, description="过滤类型: keyword/author/topic/feed"),
    status: str = Query("active", description="过滤状态: active/paused/deleted"),
):
    """列出订阅"""
    mgr = get_sub_mgr()
    subs = mgr.list_all(source=source, sub_type=type, status=status)
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


# ===== OPML 导入 =====


class OPMLImportResponse(BaseModel):
    total_feeds: int = Field(..., description="OPML 中解析到的 Feed 数量")
    created: int = Field(..., description="新创建的订阅数")
    skipped: int = Field(..., description="跳过的 (已存在) 数量")
    errors: list[str] = Field(default_factory=list, description="导入错误列表")


@app.post("/api/subscriptions/import/opml", response_model=OPMLImportResponse)
async def import_opml(
    file: UploadFile = File(..., description="OPML 文件"),
    fetch_interval: int = Query(43200, ge=300, le=604800, description="采集间隔 (秒), 默认 12h"),
    ai_analysis_enabled: bool = Query(True, description="是否启用 AI 分析"),
):
    """导入 OPML 文件，批量创建 Blog/RSS 订阅"""
    from src.sources.rss import RSSClient

    content = await file.read()
    try:
        opml_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码错误，请使用 UTF-8 编码的 OPML 文件")

    feeds = RSSClient.parse_opml(opml_text)
    if not feeds:
        raise HTTPException(status_code=400, detail="未从 OPML 中解析到任何 RSS Feed")

    db = get_db()
    mgr = get_sub_mgr()
    existing_subs = mgr.list_all(source="blog", status="active")
    existing_targets = {s.target for s in existing_subs}
    paused_subs = mgr.list_all(source="blog", status="paused")
    existing_targets.update(s.target for s in paused_subs)

    created = 0
    skipped = 0
    errors = []

    for feed in feeds:
        xml_url = feed["xml_url"]
        title = feed["title"] or feed["html_url"] or xml_url

        if xml_url in existing_targets:
            skipped += 1
            continue

        try:
            mgr.create({
                "name": title,
                "source": "blog",
                "type": "feed",
                "target": xml_url,
                "fetch_interval": fetch_interval,
                "ai_analysis_enabled": ai_analysis_enabled,
                "notification_enabled": True,
                "filters": {"html_url": feed["html_url"]} if feed["html_url"] else None,
            })
            created += 1
        except Exception as e:
            errors.append(f"{title}: {str(e)[:80]}")

    logger.info(f"OPML 导入完成: 解析 {len(feeds)} 个 Feed, 创建 {created}, 跳过 {skipped}")
    return OPMLImportResponse(
        total_feeds=len(feeds),
        created=created,
        skipped=skipped,
        errors=errors[:20],
    )


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


@app.post("/api/trigger/smart-collect")
async def trigger_smart_collect():
    """智能采集：订阅采集 + 探索发现 + AI 分析（一键完成全链路）"""
    try:
        hunter = await get_hunter()
        results = {"fetch": 0, "explore": 0, "analyzed": 0}

        if hunter.dynamic_subscription_enabled:
            await hunter.run_fetch_cycle()
            results["fetch"] = 1

        if hunter.dynamic_explore_enabled:
            await hunter.run_explore_cycle()
            results["explore"] = 1

        if hunter.analyzer:
            await hunter.run_ai_analysis_job()
            results["analyzed"] = 1

        return {"status": "ok", "message": "Smart collect completed", "results": results}
    except Exception as e:
        logger.error(f"Smart collect failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trigger/daily-report")
async def trigger_daily_report():
    """手动触发日报"""
    try:
        hunter = await get_hunter()
        await hunter.send_daily_report()
        return {"status": "ok", "message": "Daily report triggered"}
    except Exception as e:
        logger.error(f"Trigger daily report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 系统配置 CRUD =====


class SystemConfigUpdate(BaseModel):
    value: dict = Field(..., description="配置值 (JSON)")
    description: Optional[str] = Field(None, description="配置描述")


@app.get("/api/config")
async def list_system_config():
    """获取所有系统配置"""
    db = get_db()
    configs = db.list_system_configs()
    return [
        {
            "key": c.config_key,
            "value": c.config_value,
            "description": c.description,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in configs
    ]


@app.get("/api/config/{key}")
async def get_system_config(key: str):
    """获取单个系统配置"""
    db = get_db()
    config = db.get_system_config(key)
    if not config:
        raise HTTPException(status_code=404, detail=f"Config '{key}' not found")
    return {
        "key": config.config_key,
        "value": config.config_value,
        "description": config.description,
    }


@app.put("/api/config/{key}")
async def set_system_config(key: str, data: SystemConfigUpdate):
    """设置系统配置"""
    db = get_db()
    config = db.set_system_config(key, data.value, data.description)
    return {
        "key": config.config_key,
        "value": config.config_value,
        "description": config.description,
        "status": "ok",
    }


@app.delete("/api/config/{key}")
async def delete_system_config(key: str):
    """删除系统配置"""
    db = get_db()
    if not db.delete_system_config(key):
        raise HTTPException(status_code=404, detail=f"Config '{key}' not found")
    return {"status": "deleted"}


@app.get("/api/stats")
async def get_stats():
    """获取系统统计信息"""
    db = get_db()
    from datetime import timedelta

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    # Dynamically read from running instance when available
    hunter = _hunter_instance

    explore_cfg = _get_config_value(db, "explore_config") or {}
    sub_cfg = _get_config_value(db, "subscription_config") or {}
    notify_cfg = _get_config_value(db, "notify_config") or {}
    notify_schedule_cfg = _get_config_value(db, "notify_schedule") or {}

    trend_interval = int(explore_cfg.get("trend_interval", settings.explore_trend_interval))
    keyword_interval = int(explore_cfg.get("keyword_interval", settings.explore_fetch_interval))
    max_trends = int(explore_cfg.get("max_trends_per_woeid", settings.explore_max_trends_per_woeid))
    woeids_str = explore_cfg.get("twitter_woeids", settings.explore_twitter_woeids)
    num_woeids = len([w.strip() for w in woeids_str.split(",") if w.strip()]) if woeids_str else 0
    kw_str = (explore_cfg.get("keywords") or "")
    if not kw_str:
        kw_cfg = _get_config_value(db, "explore_keywords") or {}
        kw_str = kw_cfg.get("keywords", ",".join(settings.explore_keywords))
    num_keywords = len([k.strip() for k in kw_str.split(",") if k.strip()]) if kw_str else 0
    limit_cfg = _get_config_value(db, "twitter_credit_limit") or {}
    credit_limit = limit_cfg.get("daily_limit")
    if credit_limit is None:
        credit_limit = explore_cfg.get("twitter_daily_credit_limit")
    if credit_limit is None:
        credit_limit = settings.twitter_daily_credit_limit
    credit_limit = int(credit_limit)

    trend_credits_per_run = num_woeids * 450 + num_woeids * max_trends * 75
    trend_runs_per_day = max(86400 // trend_interval, 1) if trend_interval > 0 else 0
    keyword_credits_per_run = num_keywords * 75
    keyword_runs_per_day = max(86400 // keyword_interval, 1) if keyword_interval > 0 else 0
    sub_count = db.get_subscription_count("active")
    twitter_sub_count = db.get_subscription_count("active", source="twitter")
    sub_twitter_credits_day = twitter_sub_count * 75 * max(86400 // settings.default_fetch_interval, 1)

    daily_estimate = (
        trend_credits_per_run * trend_runs_per_day
        + keyword_credits_per_run * keyword_runs_per_day
        + sub_twitter_credits_day
    )

    return {
        "subscriptions": {
            "active": sub_count,
            "paused": db.get_subscription_count("paused"),
            "total": sub_count + db.get_subscription_count("paused"),
        },
        "contents": {
            "total": db.get_content_count(),
            "twitter": db.get_content_count(source="twitter"),
            "youtube": db.get_content_count(source="youtube"),
            "blog": db.get_content_count(source="blog"),
            "today": db.get_content_count_since(today),
            "this_week": db.get_content_count_since(week_ago),
        },
        "notifications": {
            "pending": db.get_unnotified_count(),
        },
        "modules": {
            "subscription_enabled": sub_cfg.get("enabled", settings.subscription_enabled),
            "explore_enabled": explore_cfg.get("enabled", settings.explore_enabled),
            "notify_enabled": notify_cfg.get("enabled", settings.notify_enabled),
        },
        "explore": {
            "enabled": explore_cfg.get("enabled", settings.explore_enabled),
            "trend_interval": trend_interval,
            "keyword_interval": keyword_interval,
            "twitter_woeids": woeids_str,
            "youtube_regions": explore_cfg.get("youtube_regions", settings.explore_youtube_regions),
            "max_trends_per_woeid": max_trends,
            "max_search_per_keyword": int(explore_cfg.get("max_search_per_keyword", settings.explore_max_search_per_keyword)),
        },
        "schedule": {
            "fetch_interval": settings.default_fetch_interval,
            "notify_schedule": notify_schedule_cfg.get("schedule", settings.notify_schedule),
            "explore_interval": keyword_interval,
        },
        "twitter_credits": {
            "daily_limit": credit_limit,
            "used_today": hunter._twitter_credits_used if hunter else 0,
            "date": hunter._twitter_credits_date if hunter else "",
            "estimated_daily": daily_estimate,
            "breakdown": {
                "trends": f"{trend_credits_per_run}/轮 × {trend_runs_per_day}轮/天 = {trend_credits_per_run * trend_runs_per_day}",
                "keywords": f"{keyword_credits_per_run}/轮 × {keyword_runs_per_day}轮/天 = {keyword_credits_per_run * keyword_runs_per_day}",
                "subscriptions": f"{twitter_sub_count}个Twitter订阅 × 75/次 × {max(86400 // settings.default_fetch_interval, 1)}次/天 = {sub_twitter_credits_day}",
            },
        },
    }


# ===== 成本监控 =====


@app.get("/api/credits/summary")
async def get_credit_summary(
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天"),
):
    """Credit 成本看板汇总数据"""
    db = get_db()
    from datetime import timedelta

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    range_start = now - timedelta(days=days)

    hunter = _hunter_instance

    # 读取动态 credit limit（优先独立 key → explore_config fallback → .env）
    limit_cfg = _get_config_value(db, "twitter_credit_limit") or {}
    credit_limit = limit_cfg.get("daily_limit")
    if credit_limit is None:
        explore_cfg = _get_config_value(db, "explore_config") or {}
        credit_limit = explore_cfg.get("twitter_daily_credit_limit")
    if credit_limit is None:
        credit_limit = settings.twitter_daily_credit_limit
    credit_limit = int(credit_limit)

    used_today = int(db.get_credit_usage_today(source="twitter"))
    daily_totals = db.get_credit_daily_totals(days=days, source="twitter")
    for d in daily_totals:
        d["total_credits"] = int(d["total_credits"])

    used_week = sum(
        d["total_credits"]
        for d in daily_totals
        if d["date"] >= week_ago.strftime("%Y-%m-%d")
    )
    used_month = sum(
        d["total_credits"]
        for d in daily_totals
        if d["date"] >= month_ago.strftime("%Y-%m-%d")
    )

    by_operation_today = db.get_credit_usage_by_operation(since=today, source="twitter")
    by_operation_week = db.get_credit_usage_by_operation(since=week_ago, source="twitter")
    for lst in (by_operation_today, by_operation_week):
        for item in lst:
            item["total_credits"] = int(item["total_credits"])

    avg_daily = (used_month / 30) if used_month else 0
    estimated_monthly_cost = float(avg_daily) * 30 / 100000 * 9.9

    return {
        "today": {
            "used": used_today,
            "limit": credit_limit,
            "remaining": max(credit_limit - used_today, 0) if credit_limit > 0 else None,
            "percentage": round(used_today / credit_limit * 100, 1) if credit_limit > 0 else 0,
        },
        "period": {
            "week": used_week,
            "month": used_month,
            "avg_daily": round(avg_daily),
        },
        "cost_estimate": {
            "monthly_credits": round(avg_daily * 30),
            "monthly_usd": round(estimated_monthly_cost, 2),
            "plan": "$9.9/100K credits",
        },
        "daily_trend": daily_totals,
        "by_operation": {
            "today": by_operation_today,
            "week": by_operation_week,
        },
        "in_memory": {
            "used_today": hunter._twitter_credits_used if hunter else 0,
            "date": hunter._twitter_credits_date if hunter else "",
        },
    }


@app.get("/api/credits/records")
async def get_credit_records(
    limit: int = Query(50, ge=1, le=200),
    source: Optional[str] = Query(None, description="过滤 API 来源: twitter"),
):
    """获取最近的 credit 消耗明细记录"""
    db = get_db()
    records = db.get_credit_recent_records(limit=limit, source=source)
    return [
        {
            "id": r.id,
            "source": r.source,
            "operation": r.operation,
            "credits": r.credits,
            "detail": r.detail,
            "context": r.context,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@app.get("/api/credits/daily")
async def get_credit_daily(
    days: int = Query(30, ge=1, le=90),
    source: Optional[str] = Query(None),
):
    """获取每日 credit 消耗趋势数据"""
    db = get_db()
    return db.get_credit_daily_totals(days=days, source=source)


@app.get("/api/credits/breakdown")
async def get_credit_breakdown(
    days: int = Query(7, ge=1, le=90),
    source: Optional[str] = Query(None),
):
    """获取按操作类型+上下文分组的 credit 消耗分布"""
    db = get_db()
    from datetime import timedelta

    since = datetime.now() - timedelta(days=days)
    return db.get_credit_usage_range(since=since, source=source)


@app.get("/api/logs/fetch")
async def list_fetch_logs(
    limit: int = Query(50, ge=1, le=200),
    subscription_id: Optional[int] = Query(None),
):
    """获取采集日志"""
    db = get_db()
    logs = db.get_fetch_logs(limit=limit, subscription_id=subscription_id)
    return [
        {
            "id": log.id,
            "subscription_id": log.subscription_id,
            "source": log.source,
            "status": log.status,
            "total_fetched": log.total_fetched,
            "new_items": log.new_items,
            "filtered_items": log.filtered_items,
            "error_message": log.error_message,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "duration_seconds": log.duration_seconds,
        }
        for log in logs
    ]


# ===== YouTube OAuth 2.0 (桌面应用类型) =====

# 桌面应用 OAuth 使用固定的 redirect_uri，无需在 Google Console 配置回调地址
_DESKTOP_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


@app.get("/api/youtube/oauth/authorize")
async def youtube_oauth_authorize():
    """获取 YouTube OAuth 2.0 授权 URL (桌面应用模式)

    步骤:
    1. 在浏览器中打开返回的 auth_url
    2. 完成 Google 账号授权
    3. Google 页面会显示一个 authorization code，复制它
    4. 调用 POST /api/youtube/oauth/token?code=<复制的code> 换取 refresh_token
    """
    client_id = settings.youtube_oauth_client_id
    if not client_id:
        raise HTTPException(status_code=400, detail="YOUTUBE_OAUTH_CLIENT_ID not configured")

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}"
        f"&redirect_uri={_DESKTOP_REDIRECT_URI}"
        "&response_type=code"
        "&scope=https://www.googleapis.com/auth/youtube.readonly"
        "&access_type=offline"
        "&prompt=consent"
    )

    return {
        "auth_url": auth_url,
        "steps": [
            "1. 在浏览器中打开上面的 auth_url",
            "2. 登录 Google 账号并授权",
            "3. 页面会显示一个 authorization code，复制它",
            "4. 调用: POST /api/youtube/oauth/token?code=你复制的code",
            "5. 将返回的 refresh_token 填入 .env",
        ],
    }


@app.post("/api/youtube/oauth/token")
async def youtube_oauth_exchange_token(
    code: str = Query(..., description="从 Google 授权页面复制的 authorization code"),
):
    """用 authorization code 换取 refresh_token (桌面应用模式)"""
    import httpx

    client_id = settings.youtube_oauth_client_id
    client_secret = settings.youtube_oauth_client_secret
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="YouTube OAuth not configured")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _DESKTOP_REDIRECT_URI,
            },
        )

    if resp.status_code != 200:
        return {
            "status": "error",
            "detail": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:500],
        }

    data = resp.json()
    refresh_token = data.get("refresh_token", "")

    if not refresh_token:
        return {
            "status": "error",
            "detail": "未获取到 refresh_token，请确保授权时使用了 prompt=consent",
        }

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

    # YouTube Data API v3 (API Key 或 OAuth)
    if settings.youtube_api_key or settings.youtube_oauth_refresh_token:
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

    if settings.youtube_api_key or settings.youtube_oauth_refresh_token:
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
