# InfoHunter

**AI-Powered Social Media Intelligence Monitor**

InfoHunter 是一个 AI 驱动的社交媒体智能订阅监控系统，帮助你突破信息茧房。它自动采集 Twitter 和 YouTube 上的内容，通过 AI 深度分析后精准推送，让你高效获取高价值信息。

## 核心特性

- **多源数据采集** - 支持 Twitter 关键词搜索、博主追踪；YouTube 视频搜索、频道订阅；Blog/RSS 订阅
- **三阶段解耦架构** - 抓取、AI 分析、推送完全独立调度，互不阻塞
- **AI 深度分析** - 通过 AG-UI 协议调用 AI Agent，对每条内容进行摘要、深度分析、质量评估、可执行洞察提取
- **优先级智能排序** - 订阅流优先于探索流，新内容优先于旧内容，确保高价值内容优先分析
- **时间窗口批量简报** - 按时间窗口汇总推送，一份简报覆盖一个时间段，不再逐条轰炸
- **二次趋势汇总** - 推送前可选调用趋势分析 Agent 做跨内容归纳，提供全局视角
- **智能过滤** - 基于互动数据、内容质量、新鲜度等多维度评分，自动过滤低质量内容
- **趋势报告** - 自动生成日报/周报，识别热门话题和新兴趋势
- **订阅管理** - 灵活的订阅系统，支持关键词、博主、话题、RSS Feed 四种订阅类型
- **即时分析** - 发送链接即时获取 AI 分析，评估博主是否值得订阅
- **多渠道推送** - 飞书 Webhook 实时通知 + 定时简报 + 日报/周报
- **MCP 集成** - 提供 MCP Server，支持 AI 对话式查询
- **Web 管理面板** - 可视化配置、内容浏览、订阅管理、成本监控

## 三阶段解耦架构

```
┌─────────────────────────────────────────────────────────────┐
│                    阶段一：抓取与落库                          │
│                                                              │
│  订阅流（每30min检查到期）     探索流（趋势24h/关键词6h）       │
│     │                              │                         │
│     ├── Twitter sort=Top/Latest    ├── Twitter 趋势            │
│     ├── YouTube order=relevance    ├── YouTube 热门             │
│     └── RSS/Blog                   └── 自定义关键词搜索         │
│                    │                                          │
│                    ▼                                          │
│              落库（去重 + 基础质量评分）                         │
│              标记 ai_analysis = NULL                           │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    阶段二：独立 AI 分析                        │
│                                                              │
│  定时任务：每 30 分钟运行一次                                  │
│                                                              │
│  1. 查询 ai_analysis IS NULL 的内容                           │
│  2. 按优先级排序（订阅流 > 探索流 > 时效性）                    │
│  3. 逐条调用 content_analysis Agent                           │
│  4. 写回 ai_analysis JSON + importance → quality_score        │
│  5. 每轮上限 N 条，避免 Agent 过载                            │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    阶段三：汇总与推送                          │
│                                                              │
│  定时推送（默认 09:00, 21:00）                                │
│                                                              │
│  1. 确定时间窗口 [上次推送时间 ~ 当前]                         │
│  2. 查询窗口内 "已分析 + 未推送" 的内容                        │
│  3. 按 importance 排序，取 TOP N                              │
│  4. 可选：调用 trend_analysis Agent 做二次汇总                 │
│  5. 构建一份简报消息，一次性推送到飞书                          │
│  6. 标记已推送，避免重复                                       │
│                                                              │
│  补充报告：                                                   │
│  - 日报（09:30）：24h 全量 AI 汇总                             │
│  - 周报（周一 10:00）：本周 AI 汇总                            │
└─────────────────────────────────────────────────────────────┘
```

## 调度任务一览

| # | 任务 | 默认频率 | 说明 |
|---|------|---------|------|
| 1 | 订阅流检查 | 30 min | 检查到期订阅并采集，不触发 AI 分析 |
| 2 | 趋势发现 | 24 h | Twitter 趋势 + YouTube 热门，高 credit 消耗 |
| 3 | 关键词探索 | 6 h | 用户自定义关键词跨平台搜索 |
| 4 | AI 分析 | 30 min | 独立分析未处理内容，按优先级排序 |
| 5 | 简报推送 | 09:00, 21:00 | 时间窗口批量简报 + 可选二次汇总 |
| 6 | 日报 | 09:30 | 24h 全量内容 AI 趋势分析 |
| 7 | 周报 | 周一 10:00 | 本周内容 AI 趋势分析 |

## 数据源策略

| 数据源 | 用途 | 费用 |
|--------|------|------|
| [TwitterAPI.io](https://twitterapi.io) | Twitter 关键词搜索（主力） | ~$30/月 |
| [ScrapeCreators](https://scrapecreators.com) | Twitter/YouTube 详情 | 按量付费 |
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | YouTube 字幕提取（主力，ScrapeCreators 备用） | 免费 |
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

### AI 分析配置

| 环境变量 | 说明 | 获取方式 |
|----------|------|----------|
| `KNOT_ENABLED` | 启用 AI 分析 | 设为 `true` |
| `KNOT_API_BASE_URL` | AG-UI 平台地址 | 你的 Knot/AG-UI 平台地址 |
| `KNOT_CONTENT_AGENT_ID` | 内容分析 Agent ID | 在平台上创建 Agent 后获取 |
| `KNOT_CONTENT_AGENT_KEY` | 内容分析 Agent API Key | 在平台上创建 Agent 后获取 |
| `KNOT_TREND_AGENT_ID` | 趋势分析 Agent ID | 在平台上创建 Agent 后获取 |
| `KNOT_TREND_AGENT_KEY` | 趋势分析 Agent API Key | 在平台上创建 Agent 后获取 |
| `KNOT_RECOMMEND_AGENT_ID` | 博主评估 Agent ID | 在平台上创建 Agent 后获取 |
| `KNOT_RECOMMEND_AGENT_KEY` | 博主评估 Agent API Key | 在平台上创建 Agent 后获取 |

### 推送配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `FEISHU_WEBHOOK_URL` | - | 飞书 Webhook URL |
| `FEISHU_SECRET` | - | 飞书签名密钥 |
| `NOTIFY_SCHEDULE` | `09:00,21:00` | 简报推送时间表（逗号分隔） |
| `NOTIFY_TOP_N` | `15` | 简报展示的 TOP N 内容数 |
| `NOTIFY_ENABLE_TREND_SUMMARY` | `true` | 推送时是否启用二次趋势汇总 |

### 调度配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DEFAULT_FETCH_INTERVAL` | `14400` (4h) | 默认采集间隔（秒） |
| `FETCH_CHECK_INTERVAL` | `1800` (30min) | 检查到期订阅的频率（秒） |
| `ANALYSIS_CHECK_INTERVAL` | `1800` (30min) | AI 分析定时任务间隔（秒） |
| `ANALYSIS_BATCH_SIZE` | `20` | 每轮 AI 分析最大处理条数 |
| `MIN_QUALITY_SCORE` | `0.3` | 最低质量评分阈值 |

## AI Agent 提示词

InfoHunter 使用三套专业 AI Agent 提示词，位于 `config/prompts/` 目录：

| 提示词文件 | 角色定位 | 用途 |
|-----------|---------|------|
| `content_analysis.txt` | 10年经验科技产业研究分析师 | 单条内容深度分析（摘要、观点、评分、洞察） |
| `trend_analysis.txt` | 顶级科技产业趋势分析师 | 多条内容趋势汇总（热点、信号、机会） |
| `recommend_evaluation.txt` | 内容策展专家与信源评估分析师 | 博主/频道价值评估（是否值得订阅） |

详细的 Agent 创建指南参考 [`config/agents/README.md`](config/agents/README.md)。

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
# 智能采集（采集 + 分析）
curl -X POST http://localhost:6002/api/trigger/smart-collect

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
│   ├── main.py                # 核心调度器（三阶段解耦）
│   ├── config.py              # 配置管理
│   ├── sources/               # 数据源客户端
│   │   ├── base.py            # 抽象基类
│   │   ├── twitter_search.py  # TwitterAPI.io 搜索
│   │   ├── twitter_detail.py  # ScrapeCreators Twitter
│   │   ├── youtube.py         # YouTube Data API v3
│   │   ├── youtube_transcript.py  # ScrapeCreators YouTube
│   │   ├── transcript_service.py # 字幕提取服务（主: youtube-transcript-api, 备: ScrapeCreators）
│   │   └── rss.py             # RSSHub / RSS Feed
│   ├── analyzer/              # AI 分析
│   │   ├── agui_client.py     # AG-UI 协议客户端
│   │   └── content_analyzer.py # 内容分析器
│   ├── filter/
│   │   └── smart_filter.py    # 智能过滤器
│   ├── storage/               # 数据存储
│   │   ├── models.py          # SQLAlchemy 模型
│   │   └── database.py        # 数据库操作（含优先级查询、时间窗口查询）
│   ├── subscription/          # 订阅管理
│   │   ├── models.py          # Pydantic 模型
│   │   └── manager.py         # 订阅管理器
│   ├── notification/          # 通知推送
│   │   ├── client.py          # 飞书客户端
│   │   └── builder.py         # 消息构建器（含批量简报模板）
│   ├── mcp/
│   │   └── server.py          # MCP Server
│   └── web/
│       ├── index.html         # Web 管理面板
│       └── app.js             # 前端逻辑
├── config/
│   ├── .env.example           # 环境变量模板
│   ├── prompts/               # AI Prompt 模板
│   │   ├── content_analysis.txt   # 内容分析提示词
│   │   ├── trend_analysis.txt     # 趋势分析提示词
│   │   └── recommend_evaluation.txt # 博主评估提示词
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
- **调度**: APScheduler (异步)
- **HTTP 客户端**: httpx (异步)
- **AI 协议**: AG-UI (Knot 平台)
- **容器化**: Docker + Docker Compose
- **MCP**: Model Context Protocol SDK
- **前端**: Vanilla JS + CSS

## License

MIT
