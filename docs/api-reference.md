# InfoHunter 数据源 API 参考

## 一、Twitter 数据源 (TwitterAPI.io)

> 文档入口: https://docs.twitterapi.io/introduction
> LLM 索引: https://docs.twitterapi.io/llms.txt
> 定价: $0.15/1k tweets, $0.18/1k user profiles, 最低 $0.00015/请求

### 1.1 核心端点

| 端点 | 方法 | 用途 | 定价 |
|------|------|------|------|
| `/twitter/tweet/advanced_search` | GET | 高级搜索 (关键词/话题) | $0.15/1k |
| `/twitter/user/last_tweets` | GET | 用户最新推文 (博主订阅) | $0.15/1k |
| `/twitter/trends` | GET | 热门趋势 (按地区) | - |
| `/twitter/tweet/by_ids` | GET | 按 ID 获取推文详情 | $0.15/1k |
| `/twitter/user/by_username` | GET | 用户资料 | $0.18/1k |

### 1.2 高级搜索参数 (`/twitter/tweet/advanced_search`)

| 参数 | 必填 | 说明 |
|------|------|------|
| `query` | 是 | 搜索查询，支持高级语法 |
| `queryType` | 是 | `"Latest"` (最新) 或 `"Top"` (热门/高质量) |
| `cursor` | 否 | 分页游标 |

**高级查询语法示例:**
- `"AI agent" OR "LLM"` - 关键词 OR 搜索
- `from:elonmusk` - 指定用户的推文
- `since:2026-01-01_00:00:00_UTC` - 时间范围
- `min_faves:100` - 最少点赞数
- `min_retweets:50` - 最少转发数
- `lang:en` - 指定语言
- 完整语法: https://github.com/igorbrigadir/twitter-advanced-search

**返回字段 (Tweet):**
- `id`, `url`, `text`, `createdAt`, `lang`
- `retweetCount`, `replyCount`, `likeCount`, `quoteCount`, `viewCount`, `bookmarkCount`
- `author`: { `userName`, `name`, `id`, `isBlueVerified`, `followers`, `following` }
- `entities`: { `hashtags`, `urls`, `user_mentions` }
- `quoted_tweet`, `retweeted_tweet`

### 1.3 热门趋势 (`/twitter/trends`)

| 参数 | 必填 | 说明 |
|------|------|------|
| `woeid` | 是 | 地区 ID (1=全球, 23424977=美国) |
| `count` | 否 | 趋势数量，默认 30 |

**返回字段 (Trend):**
- `name`: 趋势名称
- `target.query`: 搜索查询
- `target.rank`: 排名
- `target.meta_description`: 帖子数 (如 "17.7K posts")

**常用 WOEID:**
- `1` - 全球
- `23424977` - 美国
- `23424856` - 日本
- 完整列表: https://gist.github.com/tedyblood/5bb5a9f78314cc1f478b3dd7cde790b9

### 1.4 用户时间线 (`/twitter/user/last_tweets`)

| 参数 | 必填 | 说明 |
|------|------|------|
| `userName` | 是 | 用户名 (不含 @) |

每页最多 20 条，按时间倒序。

### 1.5 唯一标识

- **Tweet ID** (`id` 字段): 全局唯一数字字符串

---

## 二、YouTube 数据源 (Data API v3)

> 文档入口: https://developers.google.com/youtube/v3/docs?hl=zh-cn
> 认证: API Key 或 OAuth 2.0
> 配额: 每天 10,000 单位 (搜索=100单位, 视频详情=1单位)

### 2.1 核心端点

| 端点 | 方法 | 用途 | 配额消耗 |
|------|------|------|----------|
| `GET /search` | GET | 搜索视频/频道/播放列表 | 100 单位 |
| `GET /videos` | GET | 视频详情 (含统计) | 1 单位/视频 |
| `GET /channels` | GET | 频道信息 | 1 单位 |
| `GET /activities` | GET | 频道活动 (新上传等) | 1 单位 |
| `GET /playlistItems` | GET | 播放列表内容 | 1 单位 |

### 2.2 搜索参数 (`GET /search`)

| 参数 | 说明 |
|------|------|
| `q` | 搜索关键词 |
| `type` | `video` / `channel` / `playlist` |
| `order` | `relevance` / `date` / `viewCount` / `rating` |
| `maxResults` | 最多 50 |
| `publishedAfter` | ISO 8601 时间过滤 |
| `relevanceLanguage` | 语言偏好 |
| `regionCode` | 地区代码 (US, CN, JP) |
| `videoDuration` | `short` / `medium` / `long` |

### 2.3 排序策略对比

| order 值 | 适用场景 | 说明 |
|----------|---------|------|
| `relevance` | 探索发现 | 综合相关性 (默认) |
| `viewCount` | 热门内容 | 按播放量排序 |
| `date` | 博主订阅 | 按发布时间 |
| `rating` | 高质量 | 按评分排序 |

### 2.4 频道活动 (`GET /activities`) - 低配额方案

配额仅 1 单位 (vs search 的 100 单位)，适合频道订阅场景。

### 2.5 唯一标识

- **Video ID**: 11 位字符串 (如 `dQw4w9WgXcQ`)
- **Channel ID**: 以 `UC` 开头的 24 位字符串

---

## 三、去重策略

| 平台 | 唯一键 | 数据库约束 |
|------|--------|----------|
| Twitter | `tweet.id` | `UNIQUE(content_id, source)` |
| YouTube | `videoId` | `UNIQUE(content_id, source)` |

---

## 四、配额/成本优化

### Twitter
- 搜索用 `queryType: "Top"` 减少低质量结果
- 高级语法 `min_faves:100` 直接过滤
- 博主订阅用 `user/last_tweets` 而非 `from:username` 搜索

### YouTube
- 搜索昂贵 (100 单位/次)，每天上限 100 次搜索
- 频道订阅优先用 `activities` (1 单位) 而非 `search` (100 单位)
- 视频详情批量获取 (最多 50 个/次)
- 用 `order: viewCount` 获取热门内容
