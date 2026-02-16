# InfoHunter AG-UI Agent 配置指南

InfoHunter 使用 AG-UI 协议调用 AI Agent 进行内容分析。你需要在 Knot 平台（或其他兼容 AG-UI 协议的平台）上创建以下 Agent。

## Agent 列表

| Agent | 文件 | 环境变量 | 必需 |
|-------|------|----------|------|
| 内容分析师 | `content_analyzer.md` | `KNOT_AGENT_ID` | 是 |
| 趋势分析师 | `trend_analyzer.md` | `KNOT_TREND_AGENT_ID` | 否（复用内容分析师） |
| 博主评估师 | `recommend_evaluator.md` | - | 否（复用内容分析师） |

## 创建步骤

### 1. 创建内容分析 Agent（必需）

1. 登录 Knot 平台
2. 创建新 Agent，名称填 "InfoHunter 内容分析师"
3. 将 `content_analyzer.md` 中的 System Prompt 部分复制到 Agent 的系统提示词中
4. 选择模型（推荐 deepseek-v3.1）
5. 保存后获取 Agent ID，填入 `.env` 的 `KNOT_AGENT_ID`

### 2. 创建趋势分析 Agent（可选）

如果你希望趋势分析有更精准的效果：

1. 创建新 Agent，名称填 "InfoHunter 趋势分析师"
2. 将 `trend_analyzer.md` 中的 System Prompt 部分复制到 Agent 的系统提示词中
3. 保存后获取 Agent ID，填入 `.env` 的 `KNOT_TREND_AGENT_ID`

> 如果不创建，系统会自动复用内容分析 Agent 进行趋势分析。

### 3. 博主评估 Agent（可选）

博主评估功能默认复用内容分析 Agent，通过 Prompt 模板引导分析行为。
如果需要更精准的效果，可以参考 `recommend_evaluator.md` 单独创建。

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

## Prompt 模板

Agent 的 System Prompt 定义了 Agent 的基础能力，而具体的分析指令通过 Prompt 模板传入：

- `config/prompts/content_analysis.txt` - 单条内容分析模板
- `config/prompts/trend_analysis.txt` - 趋势分析模板
- `config/prompts/recommend_evaluation.txt` - 博主评估模板

你可以根据需要修改这些模板来调整分析效果。
