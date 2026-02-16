"""InfoHunter MCP Server

提供 AI 对话式查询接口，支持通过 MCP 协议与 InfoHunter 交互。
工具列表:
- search_content: 搜索已采集的内容
- list_subscriptions: 列出所有订阅
- create_subscription: 创建新订阅
- analyze_url: 即时分析链接
- analyze_author: 分析博主/频道
- get_trending: 获取热门内容
- get_stats: 获取系统统计
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

# MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("MCP SDK not installed. Run: pip install mcp")

from src.config import settings
from src.storage.database import get_db_manager


def create_mcp_server() -> "Server":
    """创建 MCP Server 实例"""
    if not MCP_AVAILABLE:
        raise ImportError("MCP SDK not installed. Run: pip install mcp")

    server = Server("infohunter")
    db = get_db_manager()
    db.init_db()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_content",
                description="搜索 InfoHunter 已采集的 Twitter/YouTube 内容。可按来源、关键词过滤。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "数据源过滤: twitter / youtube，不填则搜索全部",
                            "enum": ["twitter", "youtube"],
                        },
                        "subscription_id": {
                            "type": "integer",
                            "description": "按订阅 ID 过滤",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回数量限制，默认 20",
                            "default": 20,
                        },
                    },
                },
            ),
            Tool(
                name="list_subscriptions",
                description="列出所有 InfoHunter 订阅，包含名称、来源、目标、状态等信息。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "按来源过滤: twitter / youtube",
                            "enum": ["twitter", "youtube"],
                        },
                        "status": {
                            "type": "string",
                            "description": "按状态过滤: active / paused",
                            "enum": ["active", "paused"],
                            "default": "active",
                        },
                    },
                },
            ),
            Tool(
                name="create_subscription",
                description="创建新的 InfoHunter 订阅。支持 Twitter/YouTube 的关键词搜索或博主/频道订阅。",
                inputSchema={
                    "type": "object",
                    "required": ["name", "source", "type", "target"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "订阅名称，如 'AI 趋势追踪'",
                        },
                        "source": {
                            "type": "string",
                            "description": "数据源: twitter / youtube",
                            "enum": ["twitter", "youtube"],
                        },
                        "type": {
                            "type": "string",
                            "description": "订阅类型: keyword(关键词) / author(博主/频道) / topic(话题)",
                            "enum": ["keyword", "author", "topic"],
                        },
                        "target": {
                            "type": "string",
                            "description": "订阅目标: 关键词 / @用户名 / 频道ID",
                        },
                        "fetch_interval": {
                            "type": "integer",
                            "description": "采集间隔(秒)，默认 3600",
                            "default": 3600,
                        },
                    },
                },
            ),
            Tool(
                name="analyze_url",
                description="即时分析 Twitter/YouTube 链接。获取内容详情并进行 AI 分析。",
                inputSchema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Twitter 或 YouTube 链接",
                        },
                    },
                },
            ),
            Tool(
                name="analyze_author",
                description="分析 Twitter 博主或 YouTube 频道。获取博主信息、最新内容和 AI 评估。",
                inputSchema={
                    "type": "object",
                    "required": ["author_id", "source"],
                    "properties": {
                        "author_id": {
                            "type": "string",
                            "description": "Twitter 用户名(不含@) 或 YouTube 频道 ID",
                        },
                        "source": {
                            "type": "string",
                            "description": "平台: twitter / youtube",
                            "enum": ["twitter", "youtube"],
                        },
                    },
                },
            ),
            Tool(
                name="get_trending",
                description="获取最近的热门内容，按质量评分排序。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "获取最近 N 小时的内容，默认 24",
                            "default": 24,
                        },
                        "source": {
                            "type": "string",
                            "description": "按来源过滤",
                            "enum": ["twitter", "youtube"],
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回数量，默认 10",
                            "default": 10,
                        },
                    },
                },
            ),
            Tool(
                name="get_stats",
                description="获取 InfoHunter 系统统计信息，包括订阅数、内容数等。",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "search_content":
                return await _search_content(db, arguments)
            elif name == "list_subscriptions":
                return await _list_subscriptions(db, arguments)
            elif name == "create_subscription":
                return await _create_subscription(db, arguments)
            elif name == "analyze_url":
                return await _analyze_url(arguments)
            elif name == "analyze_author":
                return await _analyze_author(arguments)
            elif name == "get_trending":
                return await _get_trending(db, arguments)
            elif name == "get_stats":
                return await _get_stats(db)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
        except Exception as e:
            logger.error(f"MCP tool {name} error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


async def _search_content(db, args: dict) -> list["TextContent"]:
    source = args.get("source")
    sub_id = args.get("subscription_id")
    limit = args.get("limit", 20)

    if sub_id:
        contents = db.get_contents_by_subscription(sub_id, limit=limit)
    else:
        since = datetime.now() - timedelta(days=30)
        contents = db.get_contents_for_report(since=since, source=source, limit=limit)

    if not contents:
        return [TextContent(type="text", text="未找到内容。")]

    results = []
    for c in contents:
        entry = {
            "id": c.id,
            "source": c.source,
            "title": c.title,
            "content": (c.content or "")[:300],
            "author": c.author,
            "url": c.url,
            "metrics": c.metrics,
            "quality_score": c.quality_score,
            "posted_at": c.posted_at.isoformat() if c.posted_at else None,
        }
        if c.ai_analysis:
            entry["ai_analysis"] = c.ai_analysis
        results.append(entry)

    return [TextContent(
        type="text",
        text=json.dumps({"count": len(results), "contents": results}, ensure_ascii=False, indent=2),
    )]


async def _list_subscriptions(db, args: dict) -> list["TextContent"]:
    source = args.get("source")
    status = args.get("status", "active")
    subs = db.list_subscriptions(source=source, status=status)

    if not subs:
        return [TextContent(type="text", text="暂无订阅。")]

    results = []
    for s in subs:
        results.append({
            "id": s.id,
            "name": s.name,
            "source": s.source,
            "type": s.type,
            "target": s.target,
            "status": s.status,
            "fetch_interval": s.fetch_interval,
            "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        })

    return [TextContent(
        type="text",
        text=json.dumps({"count": len(results), "subscriptions": results}, ensure_ascii=False, indent=2),
    )]


async def _create_subscription(db, args: dict) -> list["TextContent"]:
    from src.subscription.manager import SubscriptionManager

    mgr = SubscriptionManager(db)
    sub = mgr.create(args)

    return [TextContent(
        type="text",
        text=json.dumps({
            "status": "created",
            "subscription": {
                "id": sub.id,
                "name": sub.name,
                "source": sub.source,
                "type": sub.type,
                "target": sub.target,
            },
        }, ensure_ascii=False, indent=2),
    )]


async def _analyze_url(args: dict) -> list["TextContent"]:
    """通过 HTTP 调用 API 的 analyze_url 端点"""
    import httpx

    url = args.get("url", "")
    api_base = getattr(settings, "api_base_url", "http://localhost:6002")
    api_url = f"{api_base}/api/analyze/url"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(api_url, json={"url": url})
            if response.status_code == 200:
                data = response.json()
                return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]
            else:
                return [TextContent(type="text", text=f"API error: {response.status_code} {response.text}")]
    except httpx.ConnectError:
        return [TextContent(type="text", text="InfoHunter API 未运行。请先启动服务。")]


async def _analyze_author(args: dict) -> list["TextContent"]:
    """通过 HTTP 调用 API 的 analyze_author 端点"""
    import httpx

    api_base = getattr(settings, "api_base_url", "http://localhost:6002")
    api_url = f"{api_base}/api/analyze/author"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(api_url, json=args)
            if response.status_code == 200:
                data = response.json()
                return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]
            else:
                return [TextContent(type="text", text=f"API error: {response.status_code} {response.text}")]
    except httpx.ConnectError:
        return [TextContent(type="text", text="InfoHunter API 未运行。请先启动服务。")]


async def _get_trending(db, args: dict) -> list["TextContent"]:
    hours = args.get("hours", 24)
    source = args.get("source")
    limit = args.get("limit", 10)

    since = datetime.now() - timedelta(hours=hours)
    contents = db.get_contents_for_report(since=since, source=source, limit=limit)

    if not contents:
        return [TextContent(type="text", text=f"最近 {hours} 小时无内容。")]

    results = []
    for c in contents:
        entry = {
            "source": c.source,
            "title": c.title,
            "content": (c.content or "")[:200],
            "author": c.author,
            "url": c.url,
            "metrics": c.metrics,
            "quality_score": c.quality_score,
        }
        if c.ai_analysis and isinstance(c.ai_analysis, dict):
            entry["ai_summary"] = c.ai_analysis.get("summary", "")
        results.append(entry)

    return [TextContent(
        type="text",
        text=json.dumps({"period": f"最近 {hours} 小时", "count": len(results), "trending": results}, ensure_ascii=False, indent=2),
    )]


async def _get_stats(db) -> list["TextContent"]:
    stats = {
        "active_subscriptions": db.get_subscription_count("active"),
        "paused_subscriptions": db.get_subscription_count("paused"),
        "total_contents": db.get_content_count(),
        "twitter_contents": db.get_content_count("twitter"),
        "youtube_contents": db.get_content_count("youtube"),
    }

    return [TextContent(
        type="text",
        text=json.dumps(stats, ensure_ascii=False, indent=2),
    )]


async def main():
    """MCP Server 入口"""
    if not MCP_AVAILABLE:
        print("Error: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
