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
    } catch {
        document.getElementById('status-text').textContent = '离线';
        document.getElementById('status-dot').style.background = 'var(--rose)';
    }
}

/* ===== Subscriptions ===== */
async function loadSubscriptions() {
    const el = document.getElementById('sub-list');
    el.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
    try {
        const r = await fetch(`${API}/api/subscriptions`);
        const subs = await r.json();
        if (!subs.length) {
            el.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg><p>暂无订阅，点击上方「新建订阅」开始</p></div>';
            return;
        }
        el.innerHTML = subs.map(s => {
            const typeLabel = {keyword:'关键词',author:'博主',topic:'话题'}[s.type]||s.type;
            const interval = s.fetch_interval >= 3600 ? `${s.fetch_interval/3600}h` : `${s.fetch_interval/60}m`;
            return `<div class="sub-row">
                <div class="sub-info">
                    <div class="sub-name">
                        <span class="tag tag-${s.source}">${s.source}</span>
                        <span class="tag tag-${s.type}">${typeLabel}</span>
                        ${s.name}
                    </div>
                    <div class="sub-meta">
                        <span>${s.target}</span>
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

/* ===== Contents ===== */
async function loadContents() {
    const el = document.getElementById('content-list');
    el.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
    const src = document.getElementById('content-source').value;
    const p = new URLSearchParams({limit:'100'});
    if (src) p.set('source', src);
    try {
        const r = await fetch(`${API}/api/contents?${p}`);
        const items = await r.json();
        if (!items.length) {
            el.innerHTML = '<div class="empty-state"><p>暂无内容</p></div>';
            return;
        }
        el.innerHTML = items.map(c => {
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
        }).join('');
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

function updateTargetHint() {
    const type = document.getElementById('sub-type').value;
    const input = document.getElementById('sub-target');
    const hint = document.getElementById('target-hint');
    if (type === 'keyword') {
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
async function triggerFetch() {
    showToast('正在采集...','success');
    try { await fetch(`${API}/api/trigger/fetch`,{method:'POST'}); showToast('采集完成','success'); checkHealth(); }
    catch { showToast('采集失败','error'); }
}

async function triggerDailyReport() {
    showToast('正在生成日报...','success');
    try { await fetch(`${API}/api/trigger/daily-report`,{method:'POST'}); showToast('日报已发送','success'); }
    catch { showToast('生成失败','error'); }
}

async function triggerExplore() {
    showToast('正在探索...','success');
    try { await fetch(`${API}/api/trigger/explore`,{method:'POST'}); showToast('探索完成','success'); checkHealth(); loadStats(); }
    catch { showToast('探索失败','error'); }
}

async function triggerNotify() {
    showToast('正在推送...','success');
    try { await fetch(`${API}/api/trigger/notify`,{method:'POST'}); showToast('推送完成','success'); loadStats(); }
    catch { showToast('推送失败','error'); }
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
    } catch {}
}

/* ===== Settings ===== */
async function loadSettings() {
    try {
        const r = await fetch(`${API}/api/stats`);
        const d = await r.json();
        document.getElementById('set-notify-schedule').value = d.schedule?.notify_schedule || '09:00,13:00,18:00';
        document.getElementById('set-notify-batch').value = 20;
        document.getElementById('set-notify-threshold').value = d.schedule?.notify_threshold || 0.6;
        document.getElementById('set-explore-enabled').checked = d.explore?.enabled !== false;
        document.getElementById('set-explore-interval').value = d.schedule?.explore_interval || 21600;
        document.getElementById('set-explore-woeids').value = d.explore?.twitter_woeids || '1,23424977,23424868';
        document.getElementById('set-explore-yt-regions').value = d.explore?.youtube_regions || 'US,CN';
        document.getElementById('set-fetch-interval').value = d.schedule?.fetch_interval || 14400;
    } catch {}

    // Load from system config (overrides defaults above)
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
            if (c.key === 'explore_config') {
                const v = c.value || {};
                if (v.enabled !== undefined) document.getElementById('set-explore-enabled').checked = v.enabled;
                if (v.twitter_woeids) document.getElementById('set-explore-woeids').value = v.twitter_woeids;
                if (v.youtube_regions) document.getElementById('set-explore-yt-regions').value = v.youtube_regions;
                if (v.interval) document.getElementById('set-explore-interval').value = v.interval;
                if (v.max_trends_per_woeid) document.getElementById('set-explore-max-trends').value = v.max_trends_per_woeid;
                if (v.max_search_per_keyword) document.getElementById('set-explore-search-limit').value = v.max_search_per_keyword;
                if (v.twitter_daily_credit_limit) document.getElementById('set-twitter-credit-limit').value = v.twitter_daily_credit_limit;
            }
        }
    } catch {}
}

async function saveSettings() {
    try {
        // Save feishu config
        const feishuUrl = document.getElementById('set-feishu-url').value.trim();
        const feishuSecret = document.getElementById('set-feishu-secret').value.trim();
        if (feishuUrl) {
            await fetch(`${API}/api/config/feishu_webhook`, {
                method: 'PUT', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({value: {url: feishuUrl, secret: feishuSecret}, description: '飞书 Webhook 配置'})
            });
        }

        // Save explore keywords
        const keywords = document.getElementById('set-explore-keywords').value.trim();
        await fetch(`${API}/api/config/explore_keywords`, {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({value: {keywords}, description: '自定义探索关键词'})
        });

        // Save notify schedule
        const schedule = document.getElementById('set-notify-schedule').value.trim();
        await fetch(`${API}/api/config/notify_schedule`, {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({value: {schedule}, description: '推送时间表'})
        });

        // Save quality threshold
        const minQuality = document.getElementById('set-min-quality').value;
        await fetch(`${API}/api/config/min_quality_score`, {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({value: {value: parseFloat(minQuality) || 0.3}, description: '最低质量评分'})
        });

        // Save explore config (including credit control)
        const exploreEnabled = document.getElementById('set-explore-enabled').checked;
        const exploreWoeids = document.getElementById('set-explore-woeids').value.trim();
        const exploreRegions = document.getElementById('set-explore-yt-regions').value.trim();
        const exploreInterval = document.getElementById('set-explore-interval').value;
        const maxTrends = document.getElementById('set-explore-max-trends').value;
        const searchLimit = document.getElementById('set-explore-search-limit').value;
        const creditLimit = document.getElementById('set-twitter-credit-limit').value;
        await fetch(`${API}/api/config/explore_config`, {
            method: 'PUT', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({value: {
                enabled: exploreEnabled,
                twitter_woeids: exploreWoeids,
                youtube_regions: exploreRegions,
                interval: parseInt(exploreInterval),
                max_trends_per_woeid: parseInt(maxTrends) || 2,
                max_search_per_keyword: parseInt(searchLimit) || 5,
                twitter_daily_credit_limit: parseInt(creditLimit) || 5000,
            }, description: '探索流配置'})
        });

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
