/**
 * InfoHunter — 前端应用逻辑
 */
const API = '';

/* ===== Navigation ===== */
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function switchTab(tab) {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    const btn = document.querySelector(`.nav-btn[data-tab="${tab}"]`);
    if (btn) btn.classList.add('active');
    document.getElementById(tab).classList.add('active');
    if (tab === 'subscriptions') loadSubscriptions();
    if (tab === 'contents') loadContents();
    if (tab === 'costs') { loadCostData(); loadCostRecords(); }
    if (tab === 'settings') { loadSettings(); loadFetchLogs(); }
}

/* ===== Health ===== */
async function checkHealth() {
    try {
        const r = await fetch(`${API}/api/health`);
        const d = await r.json();
        document.getElementById('status-text').textContent = '运行中';
        document.getElementById('status-dot').style.background = 'var(--emerald)';
        document.getElementById('stat-subs').textContent = d.subscriptions || 0;
        document.getElementById('stat-total').textContent = d.contents || 0;
        document.getElementById('stat-twitter').textContent = d.twitter_contents || 0;
        document.getElementById('stat-youtube').textContent = d.youtube_contents || 0;
        document.getElementById('stat-blog').textContent = d.blog_contents || 0;
    } catch {
        document.getElementById('status-text').textContent = '离线';
        document.getElementById('status-dot').style.background = 'var(--rose)';
    }
}

/* ===== Subscriptions ===== */
let _subFilterType = '';

function filterSubs(btn) {
    _subFilterType = btn.dataset.filter;
    document.querySelectorAll('.sub-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadSubscriptions();
}

async function loadSubscriptions() {
    const el = document.getElementById('sub-list');
    el.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
    try {
        const p = new URLSearchParams({status:'active'});
        if (_subFilterType) p.set('type', _subFilterType);
        const r = await fetch(`${API}/api/subscriptions?${p}`);
        const subs = await r.json();
        if (!subs.length) {
            el.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg><p>暂无订阅，点击上方「新建订阅」开始</p></div>';
            return;
        }
        el.innerHTML = subs.map(s => {
            const typeLabel = {keyword:'关键词',author:'博主',topic:'话题',feed:'RSS'}[s.type]||s.type;
            const interval = s.fetch_interval >= 3600 ? `${s.fetch_interval/3600}h` : `${s.fetch_interval/60}m`;
            return `<div class="sub-row">
                <div class="sub-info">
                    <div class="sub-name">
                        <span class="tag tag-${s.source}">${s.source}</span>
                        <span class="tag tag-${s.type}">${typeLabel}</span>
                        ${s.name}
                    </div>
                    <div class="sub-meta">
                        <span title="${esc(s.target)}">${s.target.length > 50 ? s.target.substring(0,50)+'...' : s.target}</span>
                        <span>每 ${interval}</span>
                        <span class="tag tag-${s.status}">${s.status}</span>
                        ${s.last_fetched_at ? `<span>上次: ${new Date(s.last_fetched_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</span>` : ''}
                    </div>
                </div>
                <div class="sub-actions">
                    <button class="btn btn-ghost btn-sm" onclick="toggleSub(${s.id},'${s.status}')">${s.status==='active'?'暂停':'启用'}</button>
                    <button class="btn btn-rose btn-sm" onclick="deleteSub(${s.id})">删除</button>
                </div>
            </div>`;
        }).join('');
    } catch { el.innerHTML = '<div class="empty-state"><p>加载失败</p></div>'; }
}

/* ===== Contents (paginated + tab filter) ===== */
let _contentPage = 1;
let _contentPageSize = 20;
let _contentSource = '';

function filterContent(btn) {
    document.querySelectorAll('.content-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _contentSource = btn.dataset.source;
    _contentPage = 1;
    loadContents();
}

function changePageSize() {
    _contentPageSize = parseInt(document.getElementById('content-page-size').value);
    _contentPage = 1;
    loadContents();
}

function goContentPage(p) {
    _contentPage = p;
    loadContents();
}

function _renderContentRow(c) {
    const m = c.metrics || {};
    const metrics = [];
    if (m.views) metrics.push(`<span class="metric"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>${fmtN(m.views)}</span>`);
    if (m.likes) metrics.push(`<span class="metric"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>${fmtN(m.likes)}</span>`);
    if (m.retweets) metrics.push(`<span class="metric"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>${m.retweets}</span>`);

    const aiTags = [];
    if (c.ai_analysis) {
        const a = c.ai_analysis;
        if (a.importance) aiTags.push(`<span class="ai-badge">${a.importance}/10</span>`);
        if (a.sentiment) aiTags.push(`<span class="ai-badge">${a.sentiment}</span>`);
    }

    return `<div class="content-row">
        <div class="content-title">
            <span class="tag tag-${c.source}" style="flex-shrink:0">${c.source}</span>
            <a href="${c.url||'#'}" target="_blank" rel="noopener">${esc(c.title || (c.content||'').substring(0,120))}</a>
        </div>
        ${c.content ? `<div class="content-text">${esc(c.content.substring(0,280))}</div>` : ''}
        <div class="content-footer">
            <span>@${c.author_id || c.author || '—'}</span>
            ${metrics.join('')}
            ${c.quality_score ? `<span>质量 ${(c.quality_score*100).toFixed(0)}%</span>` : ''}
            ${aiTags.join('')}
            ${c.posted_at ? `<span>${new Date(c.posted_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</span>` : ''}
        </div>
    </div>`;
}

function _renderPagination(page, pageSize, total) {
    const totalPages = Math.ceil(total / pageSize);
    if (totalPages <= 1) return '';

    const maxVisible = 7;
    let pages = [];
    if (totalPages <= maxVisible) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        let start = Math.max(2, page - 2);
        let end = Math.min(totalPages - 1, page + 2);
        if (page <= 3) end = Math.min(5, totalPages - 1);
        if (page >= totalPages - 2) start = Math.max(totalPages - 4, 2);
        if (start > 2) pages.push('...');
        for (let i = start; i <= end; i++) pages.push(i);
        if (end < totalPages - 1) pages.push('...');
        pages.push(totalPages);
    }

    const from = (page - 1) * pageSize + 1;
    const to = Math.min(page * pageSize, total);

    let html = `<div class="pagination-info">显示 ${from}-${to} / 共 ${total} 条</div><div class="pagination-btns">`;
    html += `<button class="pg-btn" ${page===1?'disabled':''} onclick="goContentPage(${page-1})">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
    </button>`;
    for (const p of pages) {
        if (p === '...') {
            html += `<span class="pg-ellipsis">…</span>`;
        } else {
            html += `<button class="pg-btn${p===page?' active':''}" onclick="goContentPage(${p})">${p}</button>`;
        }
    }
    html += `<button class="pg-btn" ${page===totalPages?'disabled':''} onclick="goContentPage(${page+1})">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
    </button>`;
    html += '</div>';
    return html;
}

async function loadContents() {
    const el = document.getElementById('content-list');
    const pgEl = document.getElementById('content-pagination');
    const badge = document.getElementById('content-total-badge');
    el.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
    pgEl.innerHTML = '';

    const p = new URLSearchParams({page: _contentPage, page_size: _contentPageSize});
    if (_contentSource) p.set('source', _contentSource);
    try {
        const r = await fetch(`${API}/api/contents?${p}`);
        const data = await r.json();
        const items = data.items || [];
        const total = data.total || 0;

        badge.textContent = total > 0 ? total : '';

        if (!items.length) {
            el.innerHTML = '<div class="empty-state"><p>暂无内容</p></div>';
            return;
        }
        el.innerHTML = items.map(_renderContentRow).join('');
        pgEl.innerHTML = _renderPagination(data.page, data.page_size, total);
    } catch { el.innerHTML = '<div class="empty-state"><p>加载失败</p></div>'; }
}

/* ===== Analyze ===== */
async function analyzeUrl() {
    const url = document.getElementById('analyze-url').value.trim();
    if (!url) return;
    const btn = document.getElementById('analyze-url-btn');
    const el = document.getElementById('url-result');
    btn.disabled = true; btn.textContent = '分析中...';
    el.className = 'analyze-result'; el.innerHTML = '';
    try {
        const r = await fetch(`${API}/api/analyze/url`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url})});
        const d = await r.json();
        el.className = 'analyze-result show';
        if (d.error) { el.innerHTML = `<div style="color:var(--rose)">错误: ${esc(d.error)}</div>`; return; }
        let html = '';
        if (d.content) {
            const c = d.content;
            html += `<div style="margin-bottom:12px"><strong>@${esc(c.author_id||c.author||'')}</strong> · ${c.source}</div>`;
            html += `<div style="margin-bottom:12px;color:var(--text-dim)">${esc((c.content||'').substring(0,300))}</div>`;
        }
        if (d.analysis) {
            const a = d.analysis;
            if (a.summary) html += `<div style="margin-bottom:8px"><strong>摘要:</strong> ${esc(a.summary)}</div>`;
            if (a.key_points) html += `<div style="margin-bottom:8px"><strong>要点:</strong><ul style="margin:4px 0 0 16px">${a.key_points.map(p=>`<li>${esc(p)}</li>`).join('')}</ul></div>`;
            if (a.importance) html += `<span class="ai-badge" style="margin-right:6px">重要性 ${a.importance}/10</span>`;
            if (a.sentiment) html += `<span class="ai-badge" style="margin-right:6px">${a.sentiment}</span>`;
            if (a.recommendation) html += `<div style="margin-top:10px;color:var(--text-dim);font-size:12px">${esc(a.recommendation)}</div>`;
        }
        el.innerHTML = html || '无分析结果';
    } catch { el.className = 'analyze-result show'; el.innerHTML = '<div style="color:var(--rose)">请求失败</div>'; }
    finally { btn.disabled = false; btn.textContent = '分析'; }
}

async function analyzeAuthor() {
    const author = document.getElementById('analyze-author').value.trim();
    const source = document.getElementById('analyze-source').value;
    if (!author) return;
    const btn = document.getElementById('analyze-author-btn');
    const el = document.getElementById('author-result');
    btn.disabled = true; btn.textContent = '评估中...';
    el.className = 'analyze-result'; el.innerHTML = '';
    try {
        const r = await fetch(`${API}/api/analyze/author`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({author_id:author,source})});
        const d = await r.json();
        el.className = 'analyze-result show';
        if (d.error) { el.innerHTML = `<div style="color:var(--rose)">错误: ${esc(d.error)}</div>`; return; }
        let html = `<div style="margin-bottom:8px"><strong>@${esc(d.author_id)}</strong> · ${d.source} · ${d.recent_contents?.length||0} 条内容</div>`;
        if (d.analysis) {
            const a = d.analysis;
            if (a.summary) html += `<div style="margin-bottom:8px">${esc(a.summary)}</div>`;
            if (a.subscribe_recommendation) {
                const colors = {strongly_recommend:'var(--emerald)',recommend:'var(--emerald)',neutral:'var(--amber)',not_recommend:'var(--rose)'};
                const labels = {strongly_recommend:'强烈推荐',recommend:'推荐',neutral:'中性',not_recommend:'不推荐'};
                html += `<span class="ai-badge" style="background:${colors[a.subscribe_recommendation]||'var(--accent)'}20;color:${colors[a.subscribe_recommendation]||'var(--accent)'}">${labels[a.subscribe_recommendation]||a.subscribe_recommendation}</span> `;
            }
            if (a.content_quality) html += `<span class="ai-badge">质量 ${a.content_quality}/10</span> `;
            if (a.reason) html += `<div style="margin-top:10px;color:var(--text-dim);font-size:12px">${esc(a.reason)}</div>`;
        }
        el.innerHTML = html;
    } catch { el.className = 'analyze-result show'; el.innerHTML = '<div style="color:var(--rose)">请求失败</div>'; }
    finally { btn.disabled = false; btn.textContent = '评估'; }
}

/* ===== Modal ===== */
function showCreateModal() { document.getElementById('create-modal').classList.add('active'); }
function closeModal() { document.getElementById('create-modal').classList.remove('active'); }

function updateSourceOptions() {
    const source = document.getElementById('sub-source').value;
    const typeSelect = document.getElementById('sub-type');
    if (source === 'blog') {
        typeSelect.value = 'feed';
        typeSelect.disabled = true;
    } else {
        typeSelect.disabled = false;
        if (typeSelect.value === 'feed') typeSelect.value = 'keyword';
    }
    updateTargetHint();
}

function updateTargetHint() {
    const type = document.getElementById('sub-type').value;
    const source = document.getElementById('sub-source').value;
    const input = document.getElementById('sub-target');
    const hint = document.getElementById('target-hint');
    if (type === 'feed' || source === 'blog') {
        input.placeholder = 'https://example.com/feed.xml';
        hint.textContent = '完整的 RSS/Atom Feed URL，如: https://simonwillison.net/atom/everything/';
    } else if (type === 'keyword') {
        input.placeholder = 'AI agent OR LLM';
        hint.textContent = '支持 OR 语法，如: "AI agent" OR "LLM" from:sama';
    } else if (type === 'author') {
        input.placeholder = '@sama 或 UCxxxxxx';
        hint.textContent = 'Twitter 用户名 (不含 @) 或 YouTube 频道 ID (UC 开头)';
    } else {
        input.placeholder = '#AI #MachineLearning';
        hint.textContent = '话题标签，支持多个';
    }
}

async function createSubscription() {
    const data = {
        name: document.getElementById('sub-name').value,
        source: document.getElementById('sub-source').value,
        type: document.getElementById('sub-type').value,
        target: document.getElementById('sub-target').value,
        fetch_interval: parseInt(document.getElementById('sub-interval').value),
    };
    if (!data.name || !data.target) { showToast('请填写名称和目标','error'); return; }
    try {
        const r = await fetch(`${API}/api/subscriptions`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
        if (r.ok) { showToast('订阅创建成功','success'); closeModal(); loadSubscriptions(); checkHealth(); }
        else { const e = await r.json(); showToast(`失败: ${e.detail||'未知错误'}`,'error'); }
    } catch { showToast('网络错误','error'); }
}

async function toggleSub(id, st) {
    const ns = st==='active'?'paused':'active';
    try {
        const r = await fetch(`${API}/api/subscriptions/${id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:ns})});
        if (r.ok) { showToast(ns==='active'?'已启用':'已暂停','success'); loadSubscriptions(); }
    } catch { showToast('操作失败','error'); }
}

async function deleteSub(id) {
    if (!confirm('确定删除此订阅？')) return;
    try {
        const r = await fetch(`${API}/api/subscriptions/${id}`, {method:'DELETE'});
        if (r.ok) { showToast('已删除','success'); loadSubscriptions(); checkHealth(); }
    } catch { showToast('删除失败','error'); }
}

/* ===== Triggers ===== */
async function triggerSmartCollect() {
    showToast('智能采集中：采集 → 分析 → 入库...', 'success');
    try {
        await fetch(`${API}/api/trigger/smart-collect`, {method:'POST'});
        showToast('智能采集完成', 'success');
        checkHealth();
        loadStats();
    } catch { showToast('采集失败','error'); }
}

async function triggerDailyReport() {
    showToast('正在生成日报...','success');
    try { await fetch(`${API}/api/trigger/daily-report`,{method:'POST'}); showToast('日报已发送','success'); }
    catch { showToast('生成失败','error'); }
}

/* ===== Stats ===== */
async function loadStats() {
    try {
        const r = await fetch(`${API}/api/stats`);
        const d = await r.json();
        const el = (id) => document.getElementById(id);
        if (el('stat-pending')) el('stat-pending').textContent = d.notifications?.pending || 0;
        if (el('stat-today')) el('stat-today').textContent = d.contents?.today || 0;
        if (el('stat-explore')) el('stat-explore').textContent = d.explore?.enabled ? '已启用' : '未启用';
        if (el('stat-schedule')) el('stat-schedule').textContent = d.schedule?.notify_schedule || '—';
        if (d.twitter_credits) {
            const tc = d.twitter_credits;
            if (el('stat-credits-used'))
                el('stat-credits-used').textContent =
                    `${tc.used_today} / ${tc.daily_limit || '∞'} (预估日消耗: ${tc.estimated_daily || '—'})`;
        }
    } catch {}
}

/* ===== Settings ===== */
async function loadSettings() {
    // Load defaults from stats
    try {
        const r = await fetch(`${API}/api/stats`);
        const d = await r.json();
        document.getElementById('set-notify-schedule').value = d.schedule?.notify_schedule || '09:00,21:00';
        document.getElementById('set-notify-threshold').value = d.schedule?.notify_threshold || 0.6;
        document.getElementById('set-explore-enabled').checked = d.explore?.enabled !== false;
        if (d.explore?.trend_interval) document.getElementById('set-explore-trend-interval').value = d.explore.trend_interval;
        if (d.explore?.keyword_interval) document.getElementById('set-explore-keyword-interval').value = d.explore.keyword_interval;
        document.getElementById('set-explore-woeids').value = d.explore?.twitter_woeids || '1,23424977,23424868';
        document.getElementById('set-explore-yt-regions').value = d.explore?.youtube_regions || 'US,CN';
        document.getElementById('set-fetch-interval').value = d.schedule?.fetch_interval || 14400;
        if (d.modules) {
            document.getElementById('set-sub-enabled').checked = d.modules.subscription_enabled !== false;
            document.getElementById('set-notify-enabled').checked = d.modules.notify_enabled !== false;
        }
    } catch {}

    // Load from system config (overrides defaults)
    try {
        const r = await fetch(`${API}/api/config`);
        const configs = await r.json();
        for (const c of configs) {
            if (c.key === 'feishu_webhook') {
                document.getElementById('set-feishu-url').value = c.value?.url || '';
                document.getElementById('set-feishu-secret').value = c.value?.secret || '';
            }
            if (c.key === 'explore_keywords') {
                document.getElementById('set-explore-keywords').value = c.value?.keywords || '';
            }
            if (c.key === 'min_quality_score') {
                document.getElementById('set-min-quality').value = c.value?.value || 0.3;
            }
            if (c.key === 'analysis_focus') {
                document.getElementById('set-analysis-focus').value = c.value?.focus || 'comprehensive';
            }
            if (c.key === 'subscription_config') {
                const v = c.value || {};
                if (v.enabled !== undefined) document.getElementById('set-sub-enabled').checked = v.enabled;
            }
            if (c.key === 'notify_config') {
                const v = c.value || {};
                if (v.enabled !== undefined) document.getElementById('set-notify-enabled').checked = v.enabled;
            }
            if (c.key === 'explore_config') {
                const v = c.value || {};
                if (v.enabled !== undefined) document.getElementById('set-explore-enabled').checked = v.enabled;
                if (v.twitter_woeids) document.getElementById('set-explore-woeids').value = v.twitter_woeids;
                if (v.youtube_regions) document.getElementById('set-explore-yt-regions').value = v.youtube_regions;
                if (v.trend_interval) document.getElementById('set-explore-trend-interval').value = v.trend_interval;
                if (v.keyword_interval) document.getElementById('set-explore-keyword-interval').value = v.keyword_interval;
                if (v.max_trends_per_woeid) document.getElementById('set-explore-max-trends').value = v.max_trends_per_woeid;
                if (v.max_search_per_keyword) document.getElementById('set-explore-search-limit').value = v.max_search_per_keyword;
            }
            if (c.key === 'notify_schedule') {
                const v = c.value || {};
                if (v.schedule) document.getElementById('set-notify-schedule').value = v.schedule;
            }
            if (c.key === 'twitter_credit_limit') {
                const v = c.value || {};
                if (v.daily_limit !== undefined) document.getElementById('set-twitter-credit-limit').value = v.daily_limit;
            }
        }
    } catch {}
}

async function saveSettings() {
    try {
        const put = (key, value, desc) => fetch(`${API}/api/config/${key}`, {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({value, description: desc})
        });

        // Subscription config
        await put('subscription_config', {
            enabled: document.getElementById('set-sub-enabled').checked,
        }, '订阅流配置');

        // Notify config
        await put('notify_config', {
            enabled: document.getElementById('set-notify-enabled').checked,
        }, '推送通知配置');

        // Feishu webhook
        const feishuUrl = document.getElementById('set-feishu-url').value.trim();
        const feishuSecret = document.getElementById('set-feishu-secret').value.trim();
        if (feishuUrl) {
            await put('feishu_webhook', {url: feishuUrl, secret: feishuSecret}, '飞书 Webhook 配置');
        }

        // Notify schedule
        await put('notify_schedule', {
            schedule: document.getElementById('set-notify-schedule').value.trim(),
        }, '推送时间表');

        // Quality threshold
        await put('min_quality_score', {
            value: parseFloat(document.getElementById('set-min-quality').value) || 0.3,
        }, '最低质量评分');

        // Analysis focus
        await put('analysis_focus', {
            focus: document.getElementById('set-analysis-focus').value || 'comprehensive',
        }, 'AI 分析侧重点');

        // Explore keywords
        await put('explore_keywords', {
            keywords: document.getElementById('set-explore-keywords').value.trim(),
        }, '自定义探索关键词');

        // Explore config (all explore params in one key)
        await put('explore_config', {
            enabled: document.getElementById('set-explore-enabled').checked,
            trend_interval: parseInt(document.getElementById('set-explore-trend-interval').value),
            keyword_interval: parseInt(document.getElementById('set-explore-keyword-interval').value),
            twitter_woeids: document.getElementById('set-explore-woeids').value.trim(),
            youtube_regions: document.getElementById('set-explore-yt-regions').value.trim(),
            max_trends_per_woeid: parseInt(document.getElementById('set-explore-max-trends').value) || 2,
            max_search_per_keyword: parseInt(document.getElementById('set-explore-search-limit').value) || 5,
        }, '探索流配置');

        // Credit limit (独立 key，便于直接读取)
        await put('twitter_credit_limit', {
            daily_limit: parseInt(document.getElementById('set-twitter-credit-limit').value) || 10000,
        }, 'Twitter 每日 Credit 上限');

        showToast('设置已保存','success');
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

/* ===== Fetch Logs ===== */
async function loadFetchLogs() {
    const el = document.getElementById('fetch-logs');
    el.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/logs/fetch?limit=30`);
        const logs = await r.json();
        if (!logs.length) {
            el.innerHTML = '<div class="empty-state"><p>暂无采集日志</p></div>';
            return;
        }
        el.innerHTML = logs.map(l => {
            const time = l.started_at ? new Date(l.started_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
            const dur = l.duration_seconds ? `${l.duration_seconds.toFixed(1)}s` : '';
            return `<div class="log-row">
                <div class="log-status ${l.status}"></div>
                <span class="tag tag-${l.source}">${l.source}</span>
                <span>获取 ${l.total_fetched || 0} / 新增 ${l.new_items || 0}</span>
                ${l.error_message ? `<span style="color:var(--rose);font-size:12px">${esc(l.error_message.substring(0,60))}</span>` : ''}
                <span class="log-meta">${time} · ${dur}</span>
            </div>`;
        }).join('');
    } catch { el.innerHTML = '<div class="empty-state"><p>加载失败</p></div>'; }
}

/* ===== OPML Import ===== */
function showOpmlModal() { document.getElementById('opml-modal').classList.add('active'); document.getElementById('opml-result').style.display='none'; }
function closeOpmlModal() { document.getElementById('opml-modal').classList.remove('active'); }

async function importOpml() {
    const fileInput = document.getElementById('opml-file');
    if (!fileInput.files.length) { showToast('请选择 OPML 文件','error'); return; }
    const btn = document.getElementById('opml-import-btn');
    const resultEl = document.getElementById('opml-result');
    btn.disabled = true; btn.textContent = '导入中...';
    resultEl.style.display = 'none';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    const interval = document.getElementById('opml-interval').value;
    const aiEnabled = document.getElementById('opml-ai').checked;

    try {
        const r = await fetch(`${API}/api/subscriptions/import/opml?fetch_interval=${interval}&ai_analysis_enabled=${aiEnabled}`, {
            method: 'POST', body: formData
        });
        const d = await r.json();
        if (!r.ok) { showToast(`导入失败: ${d.detail || '未知错误'}`, 'error'); return; }

        resultEl.style.display = 'block';
        let html = `<div style="color:var(--emerald);font-weight:600;margin-bottom:6px">导入完成</div>`;
        html += `<div>解析 Feed: ${d.total_feeds} 个 | 新建: ${d.created} 个 | 跳过: ${d.skipped} 个</div>`;
        if (d.errors && d.errors.length) {
            html += `<div style="color:var(--rose);margin-top:6px">错误 (${d.errors.length}):</div>`;
            html += d.errors.map(e => `<div style="font-size:12px;color:var(--text-dim)">· ${esc(e)}</div>`).join('');
        }
        resultEl.innerHTML = html;
        showToast(`成功导入 ${d.created} 个 RSS 订阅`, 'success');
        loadSubscriptions();
        checkHealth();
    } catch (e) {
        showToast('导入失败: ' + e.message, 'error');
    } finally {
        btn.disabled = false; btn.textContent = '导入';
    }
}

/* ===== Cost Monitor ===== */
const OP_LABELS = {
    trends: '趋势查询',
    trend_search: '趋势搜索',
    keyword_search: '关键词搜索',
    author_search: '博主搜索',
    subscription: '订阅采集',
    unknown: '其他',
};
const OP_COLORS = {
    trends: '#f59e0b',
    trend_search: '#ef4444',
    keyword_search: '#6366f1',
    author_search: '#a855f7',
    subscription: '#10b981',
    unknown: '#6b7280',
};

async function loadCostData() {
    try {
        const r = await fetch(`${API}/api/credits/summary?days=30`);
        const d = await r.json();
        const el = (id) => document.getElementById(id);

        // Summary cards
        el('cost-today').textContent = fmtN(d.today?.used || 0);
        const pct = d.today?.percentage || 0;
        const limit = d.today?.limit || 0;
        el('cost-today-sub').textContent = limit > 0
            ? `${d.today.used} / ${fmtN(limit)} (${pct}%)`
            : `${d.today?.used || 0} credits`;
        el('cost-week').textContent = fmtN(d.period?.week || 0);
        el('cost-avg-daily').textContent = fmtN(d.period?.avg_daily || 0);
        el('cost-monthly').textContent = `$${d.cost_estimate?.monthly_usd || 0}`;

        // Budget progress bar
        const fillEl = el('cost-budget-fill');
        const budgetText = el('cost-budget-text');
        if (limit > 0) {
            const width = Math.min(pct, 100);
            fillEl.style.width = width + '%';
            fillEl.className = 'budget-bar-fill' + (pct > 80 ? ' danger' : pct > 50 ? ' warning' : '');
            budgetText.textContent = `${d.today.used} / ${fmtN(limit)} credits (${pct}%)`;
        } else {
            fillEl.style.width = '0%';
            budgetText.textContent = '未设置每日上限';
        }

        // Daily trend chart (pure CSS bar chart)
        const trend = d.daily_trend || [];
        renderBarChart(el('cost-chart'), trend, limit);

        // Operation breakdown
        renderBreakdown(el('cost-breakdown-today'), d.by_operation?.today || []);
        renderBreakdown(el('cost-breakdown-week'), d.by_operation?.week || []);

    } catch (e) {
        console.error('Load cost data failed:', e);
    }
}

function renderBarChart(container, data, limit) {
    if (!data.length) {
        container.innerHTML = '<div class="empty-state"><p>暂无数据</p></div>';
        return;
    }
    const maxVal = Math.max(...data.map(d => d.total_credits), limit || 0, 1);
    const barWidth = Math.max(Math.floor((container.clientWidth || 700) / data.length) - 4, 12);

    container.innerHTML = data.map(d => {
        const h = Math.max(Math.round((d.total_credits / maxVal) * 140), 2);
        const date = d.date.substring(5); // MM-DD
        const isToday = d.date === new Date().toISOString().substring(0, 10);
        return `<div class="bar-col${isToday ? ' today' : ''}" style="width:${barWidth}px" title="${d.date}: ${d.total_credits} credits (${d.call_count} 次)">
            <div class="bar-value">${d.total_credits > 999 ? fmtN(d.total_credits) : d.total_credits}</div>
            <div class="bar" style="height:${h}px"></div>
            <div class="bar-label">${date}</div>
        </div>`;
    }).join('') + (limit > 0 ? `<div class="bar-limit-line" style="bottom:${Math.round((limit / maxVal) * 140) + 28}px" title="每日上限: ${fmtN(limit)}">
        <span>${fmtN(limit)}</span>
    </div>` : '');
}

function renderBreakdown(container, data) {
    if (!data.length) {
        container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-dim);font-size:13px">暂无数据</div>';
        return;
    }
    const total = data.reduce((s, d) => s + d.total_credits, 0);
    container.innerHTML = data.map(d => {
        const label = OP_LABELS[d.operation] || d.operation;
        const color = OP_COLORS[d.operation] || '#6b7280';
        const pct = total > 0 ? ((d.total_credits / total) * 100).toFixed(1) : 0;
        const ctxLabel = d.context === 'subscription' ? '订阅' : d.context === 'explore' ? '探索' : d.context;
        return `<div class="breakdown-row">
            <div class="breakdown-label">
                <span class="breakdown-dot" style="background:${color}"></span>
                <span>${label}</span>
                <span class="breakdown-ctx">${ctxLabel}</span>
            </div>
            <div class="breakdown-bar-track">
                <div class="breakdown-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <div class="breakdown-value">${fmtN(d.total_credits)} <span class="breakdown-pct">(${pct}%)</span></div>
            <div class="breakdown-calls">${d.call_count} 次</div>
        </div>`;
    }).join('') + `<div class="breakdown-total">合计: ${fmtN(total)} credits</div>`;
}

async function loadCostRecords() {
    const el = document.getElementById('cost-records');
    el.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/credits/records?limit=50`);
        const records = await r.json();
        if (!records.length) {
            el.innerHTML = '<div class="empty-state"><p>暂无 API 调用记录</p></div>';
            return;
        }
        el.innerHTML = `<div class="credit-records-table">
            <div class="cr-header">
                <span class="cr-col-time">时间</span>
                <span class="cr-col-op">操作</span>
                <span class="cr-col-detail">详情</span>
                <span class="cr-col-ctx">上下文</span>
                <span class="cr-col-credits">Credits</span>
            </div>
            ${records.map(r => {
                const time = r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
                const opLabel = OP_LABELS[r.operation] || r.operation;
                const color = OP_COLORS[r.operation] || '#6b7280';
                const ctxLabel = r.context === 'subscription' ? '订阅' : r.context === 'explore' ? '探索' : r.context || '';
                return `<div class="cr-row">
                    <span class="cr-col-time">${time}</span>
                    <span class="cr-col-op"><span class="breakdown-dot" style="background:${color}"></span>${opLabel}</span>
                    <span class="cr-col-detail" title="${esc(r.detail || '')}">${esc((r.detail || '—').substring(0, 40))}</span>
                    <span class="cr-col-ctx"><span class="tag tag-${r.context || 'explore'}">${ctxLabel}</span></span>
                    <span class="cr-col-credits">${r.credits}</span>
                </div>`;
            }).join('')}
        </div>`;
    } catch { el.innerHTML = '<div class="empty-state"><p>加载失败</p></div>'; }
}

/* ===== Helpers ===== */
function fmtN(n) { return n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':n; }
function esc(t) { const d=document.createElement('div'); d.textContent=t||''; return d.innerHTML; }
function showToast(msg,type='') {
    const t=document.getElementById('toast'); t.textContent=msg; t.className=`toast show ${type}`;
    setTimeout(()=>t.className='toast',3000);
}

/* ===== Init ===== */
checkHealth();
loadStats();
setInterval(checkHealth, 30000);
setInterval(loadStats, 60000);
