# InfoHunter Agent 目录

本目录存放 InfoHunter 使用的 AG-UI Agent 提示词。

## 目录说明

```
agents/
├── README.md                          # 本文件
├── content-analyzer/                  # 内容分析 Agent
│   └── main.md
├── trend-analyzer/                    # 趋势分析 Agent
│   └── main.md
└── recommend-evaluator/               # 博主评估 Agent
    └── main.md
```

## Agent 列表

| Agent | 环境变量 | 必需 | 说明 |
|-------|----------|------|------|
| `content-analyzer` | `KNOT_AGENT_ID` | ✅ 是 | 单条内容的深度分析（摘要、观点、情感、质量） |
| `trend-analyzer` | `KNOT_TREND_AGENT_ID` | ❌ 可选 | 批量内容的趋势分析（日报/周报） |
| `recommend-evaluator` | 复用 `KNOT_AGENT_ID` | ❌ 可选 | 博主/频道的订阅价值评估 |

> 如果不单独创建 `trend-analyzer`，系统会自动复用 `content-analyzer` 进行趋势分析。

## 创建步骤

### 1. 创建内容分析 Agent（必需）

1. 登录 Knot 平台
2. 创建新 Agent，名称填 "InfoHunter 内容分析师"
3. 将 `content-analyzer/main.md` 中 `## Prompt` 部分开始的全部内容复制到 Agent 的系统提示词中
4. 选择模型（推荐 deepseek-v3.1 或 glm-4.7）
5. 保存后获取 Agent ID，填入 `.env` 的 `KNOT_AGENT_ID`

### 2. 创建趋势分析 Agent（可选）

1. 创建新 Agent，名称填 "InfoHunter 趋势分析师"
2. 将 `trend-analyzer/main.md` 中 `## Prompt` 部分开始的全部内容复制到 Agent 的系统提示词中
3. 保存后获取 Agent ID，填入 `.env` 的 `KNOT_TREND_AGENT_ID`

### 3. 博主评估 Agent（可选）

博主评估默认复用 `content-analyzer`，通过 Prompt 模板引导分析行为。
如需更精准效果，可参考 `recommend-evaluator/main.md` 单独创建。

## 认证方式

支持两种认证方式（二选一）：

### 方式一：用户个人 Token（推荐）

```env
KNOT_API_TOKEN=your_personal_api_token
```

### 方式二：Agent Token

```env
KNOT_AGENT_TOKEN=your_agent_token
KNOT_USERNAME=your_username
```

## 命名规范

- 每个 Agent 独立一个文件夹
- 主 Agent 文件命名为 `main.md`
- 文件夹使用小写字母 + 连字符命名
