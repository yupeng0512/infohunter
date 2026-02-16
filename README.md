# InfoHunter

**AI-Powered Social Media Intelligence Monitor**

InfoHunter 是一个 AI 驱动的社交媒体智能订阅监控系统，帮助你突破信息茧房。它自动采集 Twitter 和 YouTube 上的内容，通过 AI 深度分析后精准推送，让你高效获取高价值信息。

## 核心特性

- **多源数据采集** - 支持 Twitter 关键词搜索、博主追踪；YouTube 视频搜索、频道订阅
- **AI 深度分析** - 通过 AG-UI 协议调用 AI Agent，对每条内容进行摘要、观点提取、情感分析、质量评估
- **智能过滤** - 基于互动数据、内容质量、新鲜度等多维度评分，自动过滤低质量内容
- **趋势报告** - 自动生成日报/周报，识别热门话题和新兴趋势
- **订阅管理** - 灵活的订阅系统，支持关键词、博主、话题三种订阅类型
- **即时分析** - 发送链接即时获取 AI 分析，评估博主是否值得订阅
- **多渠道推送** - 飞书 Webhook 实时通知 + 定时报告
- **MCP 集成** - 提供 MCP Server，支持 AI 对话式查询

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                    InfoHunter                         │
├──────────┬──────────┬──────────┬──────────┬──────────┤
│  数据采集  │  AI 分析  │  智能过滤  │  通知推送  │  API/MCP  │
├──────────┼──────────┼──────────┼──────────┼──────────┤
│TwitterAPI│ AG-UI    │ 去重     │ 飞书     │ FastAPI  │
│ScrapeC.  │ Protocol │ 质量评分  │ Webhook  │ Web UI   │
│YouTube   │ (Knot)   │ 相关性   │          │ MCP Srv  │
│RSSHub    │          │          │          │          │
└──────────┴──────────┴──────────┴──────────┴──────────┘
                         │
                    ┌────┴────┐
                    │  MySQL  │
                    └─────────┘
```

## 数据源策略

| 数据源 | 用途 | 费用 |
|--------|------|------|
| [TwitterAPI.io](https://twitterapi.io) | Twitter 关键词搜索（主力） | ~$30/月 |
| [ScrapeCreators](https://scrapecreators.com) | Twitter/YouTube 详情、字幕 | 按量付费 |
| [YouTube Data API v3](https://console.cloud.google.com) | YouTube 搜索、频道信息 | 免费额度 |
| [RSSHub](https://docs.rsshub.app) | 博主时间线备用方案 | 免费（自部署） |

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/infohunter.git
cd infohunter
```

### 2. 配置环境变量

```bash
cp config/.env.example .env
# 编辑 .env 填入你的 API Key 和配置
```

### 3. Docker 部署（推荐）

```bash
docker-compose up -d
```

### 4. 本地开发

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
uvicorn src.api:app --host 0.0.0.0 --port 6002 --reload

# 启动调度器（另一个终端）
python -m src.main
```

### 5. 访问管理面板

打开浏览器访问 `http://localhost:6002`

## 配置说明

### 必需配置

| 环境变量 | 说明 | 获取方式 |
|----------|------|----------|
| `TWITTERAPI_IO_KEY` | Twitter 搜索 API Key | [twitterapi.io](https://twitterapi.io) 注册获取 |
| `YOUTUBE_API_KEY` | YouTube Data API Key | [Google Cloud Console](https://console.cloud.google.com) 创建项目启用 API |
| `MYSQL_HOST` | MySQL 主机地址 | 自行部署或使用云服务 |
| `MYSQL_PASSWORD` | MySQL 密码 | 自行设置 |

### 推荐配置

| 环境变量 | 说明 | 获取方式 |
|----------|------|----------|
| `SCRAPECREATORS_API_KEY` | 视频字幕/详情 | [scrapecreators.com](https://scrapecreators.com) 注册 |
| `KNOT_ENABLED` | 启用 AI 分析 | 设为 `true` |
| `KNOT_API_BASE_URL` | AG-UI 平台地址 | 你的 Knot/AG-UI 平台地址 |
| `KNOT_AGENT_ID` | 内容分析 Agent ID | 在平台上创建 Agent 后获取 |
| `KNOT_API_TOKEN` | 平台 API Token | 在平台个人设置中获取 |
| `FEISHU_WEBHOOK_URL` | 飞书通知 Webhook | 飞书群设置 > 群机器人 > 自定义机器人 |

### 可选配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `KNOT_TREND_AGENT_ID` | 复用 KNOT_AGENT_ID | 趋势分析专用 Agent |
| `RSSHUB_BASE_URL` | `http://localhost:1200` | RSSHub 实例地址 |
| `DEFAULT_FETCH_INTERVAL` | `3600` | 默认采集间隔（秒） |
| `MIN_QUALITY_SCORE` | `0.3` | 最低质量评分阈值 |
| `REALTIME_NOTIFY_THRESHOLD` | `0.6` | 实时推送质量阈值 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## AI Agent 配置

InfoHunter 通过 AG-UI 协议调用 AI Agent 进行内容分析。详细的 Agent 创建指南请参考：

- [`config/agents/README.md`](config/agents/README.md) - 完整配置指南
- [`config/agents/content_analyzer.md`](config/agents/content_analyzer.md) - 内容分析 Agent
- [`config/agents/trend_analyzer.md`](config/agents/trend_analyzer.md) - 趋势分析 Agent
- [`config/agents/recommend_evaluator.md`](config/agents/recommend_evaluator.md) - 博主评估 Agent

## API 接口

### 订阅管理

```bash
# 创建订阅
curl -X POST http://localhost:6002/api/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"name": "AI趋势", "source": "twitter", "type": "keyword", "target": "AI agent"}'

# 列出订阅
curl http://localhost:6002/api/subscriptions

# 更新订阅
curl -X PUT http://localhost:6002/api/subscriptions/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "paused"}'

# 删除订阅
curl -X DELETE http://localhost:6002/api/subscriptions/1
```

### 内容查询

```bash
# 查询内容
curl "http://localhost:6002/api/contents?source=twitter&limit=20"

# 获取未分析内容
curl http://localhost:6002/api/contents/unanalyzed
```

### 即时分析

```bash
# 分析链接
curl -X POST http://localhost:6002/api/analyze/url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://twitter.com/user/status/123456"}'

# 分析博主
curl -X POST http://localhost:6002/api/analyze/author \
  -H "Content-Type: application/json" \
  -d '{"author_id": "elonmusk", "source": "twitter"}'
```

### 手动触发

```bash
# 触发采集
curl -X POST http://localhost:6002/api/trigger/fetch

# 触发日报
curl -X POST http://localhost:6002/api/trigger/daily-report
```

## MCP Server

InfoHunter 提供 MCP Server，可以集成到 Cursor、Claude Desktop 等 AI 工具中。

### 配置示例（Cursor）

```json
{
  "mcpServers": {
    "infohunter": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/infohunter",
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PASSWORD": "your_password"
      }
    }
  }
}
```

### 可用工具

| 工具 | 说明 |
|------|------|
| `search_content` | 搜索已采集的内容 |
| `list_subscriptions` | 列出所有订阅 |
| `create_subscription` | 创建新订阅 |
| `analyze_url` | 即时分析链接 |
| `analyze_author` | 分析博主/频道 |
| `get_trending` | 获取热门内容 |
| `get_stats` | 获取系统统计 |

## 项目结构

```
infohunter/
├── src/
│   ├── api.py                 # FastAPI REST API
│   ├── main.py                # 核心调度器
│   ├── config.py              # 配置管理
│   ├── sources/               # 数据源客户端
│   │   ├── base.py            # 抽象基类
│   │   ├── twitter_search.py  # TwitterAPI.io 搜索
│   │   ├── twitter_detail.py  # ScrapeCreators Twitter
│   │   ├── youtube.py         # YouTube Data API v3
│   │   ├── youtube_transcript.py  # ScrapeCreators YouTube
│   │   └── rss.py             # RSSHub 备用
│   ├── analyzer/              # AI 分析
│   │   ├── agui_client.py     # AG-UI 协议客户端
│   │   └── content_analyzer.py # 内容分析器
│   ├── filter/
│   │   └── smart_filter.py    # 智能过滤器
│   ├── storage/               # 数据存储
│   │   ├── models.py          # SQLAlchemy 模型
│   │   └── database.py        # 数据库操作
│   ├── subscription/          # 订阅管理
│   │   ├── models.py          # Pydantic 模型
│   │   └── manager.py         # 订阅管理器
│   ├── notification/          # 通知推送
│   │   ├── client.py          # 飞书客户端
│   │   └── builder.py         # 消息构建器
│   ├── mcp/
│   │   └── server.py          # MCP Server
│   └── web/
│       └── index.html         # Web 管理面板
├── config/
│   ├── .env.example           # 环境变量模板
│   ├── prompts/               # AI Prompt 模板
│   └── agents/                # AG-UI Agent 配置指南
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## 技术栈

- **语言**: Python 3.11+
- **Web 框架**: FastAPI + Uvicorn
- **数据库**: MySQL + SQLAlchemy
- **调度**: APScheduler
- **HTTP 客户端**: httpx (异步)
- **AI 协议**: AG-UI (Knot 平台)
- **容器化**: Docker + Docker Compose
- **MCP**: Model Context Protocol SDK

## License

MIT
