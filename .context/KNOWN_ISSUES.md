# InfoHunter 已知问题

## 2026-02-26: YouTube OAuth Token 过期（已修复）

### 症状

每次 YouTube 数据采集失败，日志：
```
YouTube OAuth token refresh failed: 400 "Token has been expired or revoked."
YouTube API forbidden: "Requests to this API youtube method youtube.api.v3.V3DataSearchService.List are blocked."
```

### 根因

Google OAuth 2.0 refresh_token 已过期/被撤销。Google 的 refresh_token 在以下情况会失效：
- 项目处于测试模式（refresh_token 有效期 7 天）
- 用户手动撤销授权
- token 超过 6 个月未使用

### 修复

已于 2026-02-26 重新授权并更新 `.env` 中的 `YOUTUBE_OAUTH_REFRESH_TOKEN`，容器已重启，YouTube 采集恢复正常。

### 下次 Token 过期时的修复步骤

1. 访问 OAuth 授权端点获取授权 URL：
   ```bash
   curl http://localhost:6003/api/youtube/oauth/authorize
   ```

2. 在浏览器中打开返回的 URL，登录 Google 账号并授权

3. 获取 authorization code 后，换取新的 refresh_token（注意 code 是 query 参数）：
   ```bash
   curl -X POST "http://localhost:6003/api/youtube/oauth/token?code=YOUR_AUTHORIZATION_CODE"
   ```

4. 将返回的 refresh_token 更新到 `.env` 文件中的 `YOUTUBE_OAUTH_REFRESH_TOKEN`

5. 重启容器：
   ```bash
   cd /data/workspace/infohunter && docker compose up -d
   ```

### 长期方案：将 Google Cloud 项目从测试模式发布到生产模式

测试模式下 refresh_token 仅 7 天有效，发布到生产模式后 token 不会自动过期（除非用户主动撤销或 6 个月不使用）。

本项目使用的 scope 是 `youtube.readonly`（敏感范围），发布到生产需要通过 Google 的 **Sensitive Scope Verification** 审核。

#### 前置准备

1. **准备一个可公开访问的域名**（用于应用主页、隐私政策、服务条款页面）
2. **准备隐私政策页面**（说明应用如何收集、使用、存储 YouTube 用户数据）
3. **准备一段录屏视频**（演示 OAuth 授权流程和应用如何使用 YouTube 数据）

#### 操作步骤

**第 1 步：完善 OAuth 同意屏幕信息**

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 选择 InfoHunter 所在的项目
3. 进入 **API 和服务 → OAuth 同意屏幕**
4. 填写以下信息：
   - **应用名称**: InfoHunter
   - **用户支持电子邮件**: 你的邮箱
   - **应用徽标**: 上传一个 120×120px 的图标（可选，但推荐）
   - **应用首页链接**: 你的域名首页（如 `https://yourdomain.com`）
   - **应用隐私权政策链接**: `https://yourdomain.com/privacy`
   - **应用服务条款链接**: `https://yourdomain.com/terms`
   - **已获授权的网域**: 添加你的域名（如 `yourdomain.com`）
   - **开发者联系信息**: 你的邮箱

**第 2 步：确认 Scope 配置**

1. 在同意屏幕的 **范围（Scopes）** 页面
2. 确保已添加 `https://www.googleapis.com/auth/youtube.readonly`
3. 这个 scope 会被标记为 **敏感范围**（Sensitive scope），这是正常的

**第 3 步：发布应用**

1. 在 OAuth 同意屏幕页面顶部，找到 **发布状态**
2. 当前应该显示 **"测试中"**，点击 **"发布应用"** 按钮
3. 系统会提示你需要进行验证，点击 **"确认"**

**第 4 步：提交敏感范围验证**

发布后，Google 会要求你提交验证材料：

1. 进入 **API 和服务 → OAuth 同意屏幕 → 验证状态**
2. 点击 **"准备验证"** 或 **"提交验证"**
3. 填写验证表单：
   - **项目说明**: 说明 InfoHunter 是什么（信息聚合工具，用于监控 YouTube 频道的新视频发布）
   - **Scope 用途说明**: 解释为什么需要 `youtube.readonly`（用于搜索视频、获取频道内容和热门视频列表，仅读取公开数据）
   - **演示视频**: 上传到 YouTube（不公开即可）或提供可访问的链接，内容包括：
     - 展示 OAuth 登录授权流程
     - 展示应用如何使用获取到的 YouTube 数据
     - 展示应用名称和 OAuth Client ID
   - **隐私政策链接**: 填写你准备好的隐私政策页面 URL
4. 提交审核

**第 5 步：等待审核**

- 敏感范围审核通常需要 **3-5 个工作日**
- 审核通过后，你的应用状态会变为 **"已验证"**
- 此时 refresh_token 将不再有 7 天的过期限制

#### 审核可能被拒绝的常见原因

| 原因 | 解决方式 |
|------|---------|
| 隐私政策页面缺失或无法访问 | 确保页面可公开访问且内容完整 |
| 演示视频不清晰或缺少关键步骤 | 重新录制，确保包含完整的 OAuth 授权流程 |
| Scope 申请过于宽泛 | 说明只使用 `readonly`，不修改用户数据 |
| 域名未验证 | 在 Google Search Console 中验证域名所有权 |

#### 备选方案：降级为 API Key 模式

如果暂时不想走审核流程，可以降级为 API Key 模式：
- 优点：不需要 OAuth，无 token 过期问题
- 缺点：每日配额较少（默认 10,000 units/天），且某些 API 功能受限
- 操作：删除 `.env` 中的 `YOUTUBE_OAUTH_*` 三个变量，保留 `YOUTUBE_API_KEY` 即可

## RSS SSL 连接间歇失败（非阻塞）

- 与 TrendRadar 同样的服务器网络环境 TLS 问题
- 不影响核心功能，已有错误处理和重试机制

## 部署信息

- 端口：6003 (映射到容器 6002)
- 数据库：复用 github-sentinel 的 MySQL（通过 sentinel-network）
- 日志目录：`./logs/`
- 配置文件：`.env`
