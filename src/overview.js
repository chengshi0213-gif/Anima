/**
 * Anima — overview.js
 * Overview panel, dashboard, worker detail, reports, skills
 */
import { CONFIG, AGENTS, WORKER_DETAILS, wsConns, escHtml, formatTime, toast, markdownToHtml, scrollBottom } from './state.js';
import { initAgentWS } from './ws.js';
//  总览面板
// ══════════════════════════════════════════════════
export async function loadOverview() {
  const body = document.getElementById('overviewBody');
  if (!body) return;
  body.innerHTML = '<div class="overview-loading">加载中…</div>';
  try {
    const [usage, statusAll, skillsData, membershipData] = await Promise.all([
      fetch(`${CONFIG.api}/usage?days=7`).then(r => r.json()),
      fetch(`${CONFIG.api}/status`).then(r => r.json()),
      fetch(`${CONFIG.api}/skills`).then(r => r.json()).catch(() => ({ skills:[], summary:{} })),
      fetch(`${CONFIG.api}/membership/status`).then(r => r.json()).catch(() => ({ tier:'free', active:false })),
    ]);
    renderOverview(usage, statusAll, skillsData, membershipData);
  } catch (_) {
    body.innerHTML = '<div class="overview-loading" style="color:var(--error)">⚠️ 无法加载，请检查后端</div>';
  }
}
window.loadOverview = loadOverview;

/**
 * 纯 SVG 雷达图 — 根据 Skill 分类使用量生成六边形/八边形蜘蛛图
 * @param {Array} skills - 来自 /skills 的 skill 列表
 * @returns {string} SVG HTML 字符串
 */
function buildRadarChart(skills) {
  const AXES = [
    { key:'编程', label:'编程', icon:'💻' },
    { key:'分析', label:'分析', icon:'📊' },
    { key:'写作', label:'写作', icon:'✍️' },
    { key:'沟通', label:'沟通', icon:'💬' },
    { key:'效率', label:'效率', icon:'⚡' },
    { key:'记忆', label:'记忆', icon:'🧠' },
    { key:'学习', label:'学习', icon:'📚' },
    { key:'自动化', label:'自动化', icon:'🤖' },
  ];
  const N = AXES.length;
  const CX = 120, CY = 120, R = 90;

  // 每个分类的使用量总和
  const catScores = {};
  AXES.forEach(a => { catScores[a.key] = 0; });
  skills.forEach(s => {
    const cat = s.category || '';
    if (cat in catScores) catScores[cat] += (s.usage_count || 0) + (s.avg_score || 3);
  });
  const maxVal = Math.max(...Object.values(catScores), 1);

  const toXY = (idx, r) => {
    const angle = (Math.PI * 2 * idx / N) - Math.PI / 2;
    return { x: CX + r * Math.cos(angle), y: CY + r * Math.sin(angle) };
  };

  // 背景网格（4层）
  let grid = '';
  [0.25, 0.5, 0.75, 1].forEach(frac => {
    const pts = AXES.map((_, i) => {
      const p = toXY(i, R * frac);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }).join(' ');
    grid += `<polygon points="${pts}" fill="none" stroke="var(--border)" stroke-width="${frac === 1 ? 1.5 : 0.8}" opacity="0.6"/>`;
  });

  // 轴线
  let axes = AXES.map((_, i) => {
    const p = toXY(i, R);
    return `<line x1="${CX}" y1="${CY}" x2="${p.x.toFixed(1)}" y2="${p.y.toFixed(1)}" stroke="var(--border)" stroke-width="0.8" opacity="0.5"/>`;
  }).join('');

  // 数据多边形
  const dataPts = AXES.map((a, i) => {
    const score = catScores[a.key] / maxVal;
    const p = toXY(i, R * Math.max(0.05, score));
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(' ');

  // 标签
  let labels = AXES.map((a, i) => {
    const p = toXY(i, R + 18);
    const anchor = p.x < CX - 5 ? 'end' : p.x > CX + 5 ? 'start' : 'middle';
    const score = catScores[a.key] / maxVal;
    const opacity = 0.4 + score * 0.6;
    return `<text x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}" text-anchor="${anchor}" font-size="9" fill="var(--text)" opacity="${opacity.toFixed(2)}" dominant-baseline="middle">${a.icon} ${a.label}</text>`;
  }).join('');

  const hasData = Object.values(catScores).some(v => v > 0);
  const noDataMsg = hasData ? '' : `<text x="${CX}" y="${CY + R + 32}" text-anchor="middle" font-size="11" fill="var(--muted)">首次使用后图表自动更新</text>`;

  return `
    <div style="display:flex;align-items:center;justify-content:center;gap:20px;flex-wrap:wrap">
      <svg width="${CX*2}" height="${CY*2+24}" viewBox="0 0 ${CX*2} ${CY*2+24}" style="overflow:visible">
        ${grid}${axes}
        <polygon points="${dataPts}"
          fill="rgba(var(--accent-rgb),.15)"
          stroke="var(--accent)"
          stroke-width="2"
          stroke-linejoin="round"/>
        ${dataPts.split(' ').map((pt, i) => {
          const [px, py] = pt.split(',');
          return `<circle cx="${px}" cy="${py}" r="3.5" fill="var(--accent)" opacity=".85"/>`;
        }).join('')}
        ${labels}
        ${noDataMsg}
      </svg>
      <div style="font-size:12px;color:var(--muted);max-width:150px;line-height:1.7">
        <div style="font-weight:600;color:var(--text);margin-bottom:6px">能力覆盖</div>
        ${AXES.map(a => {
          const pct = Math.round((catScores[a.key] / maxVal) * 100);
          return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
            <span>${a.icon}</span>
            <span style="flex:1">${a.label}</span>
            <div style="width:50px;height:4px;background:var(--border);border-radius:2px;overflow:hidden">
              <div style="width:${pct}%;height:100%;background:var(--accent);opacity:.7;border-radius:2px"></div>
            </div>
          </div>`;
        }).join('')}
      </div>
    </div>`;
}

function renderOverview(usage, statusAll, skillsData = {}, membershipData = {}) {
  const body = document.getElementById('overviewBody');
  if (!body) return;

  const agentCards = Object.values(AGENTS).map(agent => {
    const s = statusAll[agent.id] || null;
    const isBusy = s?.busy;
    const isOff  = !s;
    const pillClass = isOff ? 'off' : isBusy ? 'busy' : 'ready';
    const pillText  = isOff ? '离线' : isBusy ? '⚡ 工作中' : '✓ 就绪';
    return `
      <div class="card agent-card" onclick="switchTab('${agent.id}',document.querySelector('[data-tab=${agent.id}]'))">
        <div class="agent-card-top">
          <div class="agent-card-avatar ${agent.colorClass}">${agent.icon}</div>
          <div>
            <div class="agent-card-name">${agent.name}</div>
            <div class="agent-card-title">${agent.title}</div>
          </div>
        </div>
        <div class="agent-status-pill ${pillClass}">${pillText}</div>
        <div class="agent-stat-row">
          <div class="agent-stat">模型 <strong>${s?.model || '-'}</strong></div>
          <div class="agent-stat">工具 <strong>${s?.tools || 0}</strong></div>
        </div>
      </div>`;
  }).join('');

  const days    = (usage.daily||[]).length || 7;
  const projCost = usage.total_cost > 0 ? (usage.total_cost / Math.max(days,1) * 30).toFixed(1) : '0.0';
  const maxTokens = Math.max(...(usage.daily||[{tokens:1}]).map(d=>d.tokens), 1);
  const trendHtml = (usage.daily||[]).slice(-7).map(d => `
    <div class="trend-row">
      <span class="trend-date">${d.date.slice(5)}</span>
      <div class="trend-bar-wrap"><div class="trend-bar" style="width:${Math.max(2,(d.tokens/maxTokens)*100).toFixed(0)}%;background:var(--accent)"></div></div>
      <span class="trend-val">${(d.tokens/1000).toFixed(0)}K</span>
    </div>`).join('') || '<div style="color:var(--muted);font-size:12px">暂无数据</div>';

  // Skill 预览卡（最多4个）
  const skills = (skillsData.skills || []).slice(0, 4);
  const skillMini = skills.length ? skills.map(s => `
    <div class="skill-mini-card" onclick="switchTab('skills',document.querySelector('[data-tab=skills]'))">
      <div class="skill-mini-icon">${s.icon||'⚙️'}</div>
      <div class="skill-mini-name">${s.name}</div>
      <div class="skill-mini-score">${s.avg_score ? '★'.repeat(Math.round(s.avg_score)) : '新'}</div>
    </div>`).join('') : `<div style="color:var(--muted);font-size:12px">暂无 Skill 数据</div>`;
  const summary = skillsData.summary || {};

  body.innerHTML = agentCards + `
    <div class="card">
      <h3>💰 API 用量（7天）</h3>
      <div class="big">¥${(usage.total_cost||0).toFixed(2)}</div>
      <div class="sub">预估月费 ¥${projCost} · ${usage.total_sessions||0} 会话</div>
      <div class="api-bar-wrap" style="margin-top:12px">
        <div class="api-bar-label"><span>Token 消耗</span><span>${((usage.total_tokens||0)/1000).toFixed(1)}K</span></div>
        <div class="api-bar"><div class="api-fill safe" style="width:${Math.min(100,((usage.total_cost||0)/50)*100).toFixed(0)}%"></div></div>
      </div>
    </div>
    <div class="card">
      <h3>📈 7日趋势</h3>
      ${trendHtml}
    </div>
    <div class="card skill-overview-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0">🧩 Skill 概览</h3>
        <button class="hdr-btn-sm" onclick="switchTab('skills',document.querySelector('[data-tab=skills]'))">查看全部 →</button>
      </div>
      <div style="display:flex;gap:6px;margin-bottom:10px;font-size:12px;color:var(--muted)">
        <span>共 <b>${summary.total||0}</b> 个 Skill</span>
        <span>·</span>
        <span>守藏已升级 <b>${summary.upgraded||0}</b> 次</span>
      </div>
      <div class="skill-mini-row">${skillMini}</div>
    </div>
    <div class="card">
      <h3>🕸 Skill 雷达图</h3>
      ${buildRadarChart(skillsData.skills || [])}
    </div>
    <div class="card">
      <h3>👑 会员</h3>
      ${membershipData.active && membershipData.tier === 'pro'
        ? `<div style="display:flex;align-items:center;gap:10px;margin-top:8px">
            <span class="membership-badge-pro">PRO</span>
            <span style="font-size:13px;color:var(--muted)">有效至 ${membershipData.expires}（${membershipData.days_left} 天）</span>
          </div>
          ${membershipData.days_left <= 14
            ? `<div style="margin-top:8px;padding:6px 12px;background:#fef3cd;border-radius:8px;font-size:12px;color:#856404">⚠️ 会员即将到期，届时 Pro Skill 将被锁定</div>`
            : `<div style="font-size:12px;color:var(--muted);margin-top:8px">全部 ${summary.total||30} 个 Skill + 工作流模板已解锁</div>`
          }`
        : `<div style="font-size:13px;color:var(--muted);margin-top:6px">
            当前 Free · ${(skillsData.skills||[]).filter(s=>s.locked).length} 个 Skill 已锁定
          </div>
          <button class="hdr-btn-sm" style="margin-top:10px" onclick="switchTab('settings',document.querySelector('[data-tab=settings]'))">🔑 激活 Pro →</button>`
      }
    </div>
    <div class="card">
      <h3>⚡ 快速操作</h3>
      ${Object.values(AGENTS).map(a=>`<button class="quick-btn" onclick="switchTab('${a.id}',document.querySelector('[data-tab=${a.id}]'))">${a.icon} ${a.name}</button>`).join('')}
      <button class="quick-btn" onclick="switchTab('tianyuan-team',document.querySelector('[data-tab=tianyuan-team]'))">🏢 陶朱团队</button>
      <button class="quick-btn" onclick="switchTab('reports',document.querySelector('[data-tab=reports]'))">📈 今日报告</button>
      <button class="quick-btn" onclick="loadOverview()">↺ 刷新</button>
    </div>`;
}

// ══════════════════════════════════════════════════
//  仪表盘面板
// ══════════════════════════════════════════════════

// 简单的本地 Kanban 状态（session 内存）
let kanbanTasks = JSON.parse(localStorage.getItem('animaKanban') || 'null') || {
  todo: [
    { id:1, title:'配置 API 密钥', meta:'Anima · 待处理' },
    { id:2, title:'上传项目文档给守藏分析', meta:'守藏 · 待处理' },
  ],
  inprogress: [],
  done: [
    { id:3, title:'搭建 Anima v1.0 UI', meta:'陶朱 · 已完成' },
  ],
};
let nextTaskId = 10;

function saveKanban() {
  localStorage.setItem('animaKanban', JSON.stringify(kanbanTasks));
}

export async function loadDashboard() {
  // 更新统计卡片
  try {
    const [usage, statusAll] = await Promise.all([
      fetch(`${CONFIG.api}/usage?days=7`).then(r => r.json()),
      fetch(`${CONFIG.api}/status`).then(r => r.json()),
    ]);
    const cost    = (usage.total_cost  || 0).toFixed(2);
    const tokens  = ((usage.total_tokens || 0) / 1000).toFixed(1) + 'K';
    const sessions = usage.total_sessions || 0;
    const days    = (usage.daily || []).length || 7;
    const proj    = usage.total_cost > 0 ? (usage.total_cost / Math.max(days,1) * 30).toFixed(2) : '0.00';
    const agentCount = Object.keys(statusAll).length;

    document.getElementById('dashCost').textContent    = `¥${cost}`;
    document.getElementById('dashCostSub').textContent = `预估月费 ¥${proj}`;
    document.getElementById('dashTokens').textContent  = tokens;
    document.getElementById('dashTokensSub').textContent = `${sessions} 次会话`;
    document.getElementById('dashSessions').textContent  = sessions;
    document.getElementById('dashAgents').textContent    = agentCount;

    // 渲染柱状图
    const bars = document.getElementById('dashChartBars');
    if (bars) {
      const daily = (usage.daily || []).slice(-7);
      const maxT  = Math.max(...daily.map(d => d.tokens || 0), 1);
      bars.innerHTML = daily.length
        ? daily.map(d => {
            const pct = Math.max(2, ((d.tokens || 0) / maxT) * 100).toFixed(0);
            const zero = (d.tokens || 0) === 0;
            return `<div class="chart-bar-wrap">
              <div class="chart-bar${zero?' zero':''}" style="height:${pct}%" title="${((d.tokens||0)/1000).toFixed(1)}K"></div>
              <div class="chart-label">${(d.date||'').slice(5)}</div>
            </div>`;
          }).join('')
        : '<div style="color:var(--muted);font-size:12px;padding:8px">暂无数据</div>';
    }
  } catch(_) {
    document.getElementById('dashCost').textContent = '¥—';
  }

  // 渲染 Kanban
  renderKanban();
}
window.loadDashboard = loadDashboard;

function renderKanban() {
  for (const col of ['todo','inprogress','done']) {
    const el = document.getElementById(`kanban-${col}`);
    if (!el) continue;
    const tasks = kanbanTasks[col] || [];
    el.innerHTML = tasks.length
      ? tasks.map(t => `
          <div class="kanban-card">
            ${escHtml(t.title)}
            <div class="kanban-card-meta">${escHtml(t.meta || '')}</div>
          </div>`).join('')
      : '<div class="kanban-empty">暂无任务</div>';
  }
}

window.addKanbanTask = function() {
  const title = prompt('新任务名称：');
  if (!title?.trim()) return;
  kanbanTasks.todo.unshift({ id: nextTaskId++, title: title.trim(), meta: new Date().toLocaleDateString('zh-CN') });
  saveKanban();
  renderKanban();
};

// ══════════════════════════════════════════════════
//  陶朱子员工详情页（含完整对话界面）
// ══════════════════════════════════════════════════
export function renderWorkerDetail(wrap, workerId) {
  const w = WORKER_DETAILS[workerId];
  if (!w) return;

  const TOOL_NAMES = {
    executor: ['list_dir','file_read','file_write','file_edit','search_code','shell_run'],
    writer:   ['file_read','file_write'],
    reader:   ['file_read','search_code'],
    critic:   ['file_read','search_code'],
  };
  const toolChips = (TOOL_NAMES[workerId] || [])
    .map(t => `<span class="model-tag" style="font-size:11px">${t}</span>`).join('');

  wrap.innerHTML = `
    <div class="chat-wrap" data-agent="${workerId}">
      <div class="chat-header">
        <div class="agent-info">
          <div class="agent-avatar-lg ${w.cls}">${w.icon}</div>
          <div>
            <div class="agent-name">${w.name}</div>
            <div class="agent-meta" id="meta-${workerId}">${w.model} · ${w.desc}</div>
          </div>
        </div>
        <div class="chat-hdr-btns">
          <div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;max-width:320px">${toolChips}</div>
          <button class="icon-btn" title="清空对话" onclick="clearChat('${workerId}')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="chat-messages" id="messages-${workerId}">
        <div class="chat-welcome">
          <div class="welcome-avatar ${w.cls}">${w.icon}</div>
          <div class="welcome-name">${w.name}</div>
          <div class="welcome-desc">${w.model} · ${w.desc}</div>
        </div>
      </div>
      <div class="chat-composer" id="composer-${workerId}">
        <div class="file-chips-bar hidden" id="fileBar-${workerId}"></div>
        <textarea class="composer-input" id="input-${workerId}"
          placeholder="向${w.name}发送任务…"
          rows="1"
          onkeydown="handleInputKey(event,'${workerId}')"
          oninput="autoResize(this)"></textarea>
        <div class="composer-toolbar">
          <div class="toolbar-left">
            <button class="toolbar-btn" title="上传文件" onclick="triggerFileUpload('${workerId}')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
              </svg>
            </button>
            <input type="file" hidden id="fileInput-${workerId}" multiple onchange="handleFileSelect('${workerId}',this)">
            <span class="model-btn" style="cursor:default;opacity:0.75;pointer-events:none" title="固定模型">🔒 ${w.model}</span>
          </div>
          <button class="send-btn" id="send-${workerId}" onclick="sendMessage('${workerId}')" disabled>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 4l8 16H4z" transform="rotate(180,12,12)"/></svg>
          </button>
        </div>
      </div>
    </div>`;

  // 初始化 WS（渲染时按需连接）
  if (!wsConns[workerId] || wsConns[workerId].readyState >= WebSocket.CLOSING) {
    initAgentWS(workerId);
  }
}
window.renderWorkerDetail = renderWorkerDetail;

// ════════════════════════════════════════════════════
//  晨间报告 Morning Card
// ════════════════════════════════════════════════════
export async function checkMorningReport() {
  try {
    const r = await fetch(`${CONFIG.api}/reports/status`);
    const { send_daily, send_weekly } = await r.json();
    if (send_weekly) {
      const rpt = await fetch(`${CONFIG.api}/reports/weekly`).then(x => x.json());
      showMorningCard(rpt, 'weekly');
    } else if (send_daily) {
      const rpt = await fetch(`${CONFIG.api}/reports/daily`).then(x => x.json());
      showMorningCard(rpt, 'daily');
    }
    // 更新侧边栏小红点
    const dot = document.getElementById('reportDot');
    if (dot && (send_daily || send_weekly)) dot.classList.remove('hidden');
  } catch(_) {}
}
window.checkMorningReport = checkMorningReport;

function showMorningCard(report, type) {
  if (!report || !report.warm_text) return;
  const overlay = document.getElementById('morningOverlay');
  if (!overlay) return;

  document.getElementById('morningBadge').textContent = type === 'weekly' ? '📊 本周周报' : '📅 今日日报';
  document.getElementById('morningDate').textContent   = report.date || '';
  document.getElementById('morningWarm').textContent   = report.warm_text || '';

  // 统计行
  const stats = report.stats || {};
  document.getElementById('morningStats').innerHTML = `
    <div class="mstat"><div class="mstat-n">${stats.total_sessions||0}</div><div class="mstat-l">对话</div></div>
    <div class="mstat"><div class="mstat-n">${stats.total_messages||0}</div><div class="mstat-l">消息</div></div>
    <div class="mstat"><div class="mstat-n">${stats.peak_hour||0}:00</div><div class="mstat-l">活跃时段</div></div>
    <div class="mstat"><div class="mstat-n">${Object.keys(stats.by_agent||{}).length}</div><div class="mstat-l">使用 Agent</div></div>
  `;

  // Skill 升级
  const upgrades = report.skill_upgrades || [];
  if (upgrades.length) {
    document.getElementById('morningSkills').style.display = '';
    document.getElementById('morningSkillsList').innerHTML = upgrades.map(s =>
      `<span class="morning-skill-chip">${s.icon||'⚙️'} ${s.name} v${s.version}</span>`
    ).join('');
  }

  // 简易图表（时间线条 / 热力）
  const chart = document.getElementById('morningChart');
  if (type === 'daily' && report.chart_data?.timeline) {
    const timeline = report.chart_data.timeline;
    const maxC = Math.max(...timeline.map(t => t.count), 1);
    chart.innerHTML = `<div class="morning-bars">` +
      timeline.filter(t => t.hour >= 7).map(t => `
        <div class="mbar-wrap" title="${t.hour}:00 — ${t.count}次">
          <div class="mbar" style="height:${Math.max(4,(t.count/maxC)*60).toFixed(0)}px"></div>
          <div class="mbar-label">${t.hour}</div>
        </div>`).join('') + `</div>`;
  } else if (type === 'weekly' && report.chart_data?.heatmap) {
    chart.innerHTML = `<div class="morning-heatmap">` +
      report.chart_data.heatmap.map(d => {
        const maxC = Math.max(...report.chart_data.heatmap.map(x => x.count), 1);
        const opacity = (d.count / maxC * 0.9 + 0.1).toFixed(2);
        return `<div class="heat-cell" title="${d.date}: ${d.count}次"
          style="background:rgba(var(--accent-rgb),${opacity})">
          <div class="heat-date">${d.date.slice(8)}</div>
          <div class="heat-count">${d.count}</div>
        </div>`;
      }).join('') + `</div>`;
  }

  overlay.classList.remove('hidden');
}

window.morningClose = function(e) {
  if (e && e.target !== document.getElementById('morningOverlay')) return;
  document.getElementById('morningOverlay')?.classList.add('hidden');
};

// ════════════════════════════════════════════════════
//  报告页面 tab-reports
// ════════════════════════════════════════════════════
window.reportSwitchTab = function(type) {
  document.getElementById('reportDailyPanel').style.display  = type === 'daily'  ? '' : 'none';
  document.getElementById('reportWeeklyPanel').style.display = type === 'weekly' ? '' : 'none';
  document.getElementById('rTabDaily').classList.toggle('active', type === 'daily');
  document.getElementById('rTabWeekly').classList.toggle('active', type === 'weekly');
  reportLoad(type);
};

async function reportLoad(type, force = false) {
  const url = `${CONFIG.api}/reports/${type}${force ? '?force=1' : ''}`;
  const card = document.getElementById(`report${type.charAt(0).toUpperCase()+type.slice(1)}Card`);
  if (!card) return;
  try {
    const r = await fetch(url);
    const report = await r.json();
    renderReportCard(report, type);
  } catch(_) {}
}
window.reportLoad = reportLoad;

function renderReportCard(report, type) {
  if (!report) return;
  const pfx = type.charAt(0).toUpperCase() + type.slice(1);
  const warmEl  = document.getElementById(`report${pfx}Text`);
  const statsEl = document.getElementById(`report${pfx}Stats`);
  const chartEl = document.getElementById(`report${pfx}Chart`);
  const skillEl = document.getElementById(`report${pfx}Skills`);
  if (warmEl)  warmEl.textContent  = report.warm_text || '暂无数据';
  const stats = report.stats || {};
  if (statsEl) statsEl.innerHTML = `
    <div class="rstat-card"><div class="rstat-n">${stats.total_sessions||0}</div><div class="rstat-l">对话次数</div></div>
    <div class="rstat-card"><div class="rstat-n">${stats.total_messages||0}</div><div class="rstat-l">消息数</div></div>
    <div class="rstat-card"><div class="rstat-n">${stats.peak_hour||0}:00</div><div class="rstat-l">最活跃时段</div></div>
    <div class="rstat-card"><div class="rstat-n">${Object.keys(stats.by_agent||{}).length}</div><div class="rstat-l">使用 Agent</div></div>
  `;
  // 图表
  if (chartEl && report.chart_data) {
    if (type === 'daily' && report.chart_data.timeline) {
      const tl = report.chart_data.timeline;
      const mx = Math.max(...tl.map(t=>t.count), 1);
      chartEl.innerHTML = `<div style="font-size:12px;color:var(--muted);margin-bottom:8px">24小时活跃分布</div>
        <div class="report-bars">` + tl.filter(t=>t.hour>=6).map(t=>`
        <div class="rbar-wrap">
          <div class="rbar" style="height:${Math.max(4,(t.count/mx)*80).toFixed(0)}px"></div>
          <div class="rbar-lbl">${t.hour}</div>
        </div>`).join('') + `</div>`;
    } else if (type === 'weekly' && report.chart_data.heatmap) {
      const hm = report.chart_data.heatmap;
      const mx = Math.max(...hm.map(d=>d.count), 1);
      chartEl.innerHTML = `<div style="font-size:12px;color:var(--muted);margin-bottom:8px">7日活跃热力图</div>
        <div class="report-heatmap">` + hm.map(d=>`
        <div class="rheat-cell" title="${d.date}: ${d.count}次"
          style="background:rgba(var(--accent-rgb),${(d.count/mx*0.8+0.15).toFixed(2)})">
          <div>${d.date.slice(5)}</div><div>${d.count}</div>
        </div>`).join('') + `</div>`;
    }
  }
  // Skill 升级
  const upgrades = report.skill_upgrades || [];
  if (skillEl) {
    skillEl.innerHTML = upgrades.length ?
      `<div style="font-weight:600;margin-bottom:8px;font-size:13px">🚀 期间 Skill 升级</div>` +
      upgrades.map(s=>`<div class="skill-upgrade-item">${s.icon||'⚙️'} <b>${s.name}</b> → v${s.version}${s.note?' · '+s.note:''}</div>`).join('') :
      '';
  }
  // 会员到期提醒
  const mem = report.membership;
  if (mem && mem.warning && skillEl) {
    skillEl.innerHTML += `
      <div style="margin-top:12px;padding:10px 14px;background:#fef3cd;border-radius:10px;font-size:13px;color:#856404;border:1px solid #ffc107">
        ${mem.message}
        <button class="hdr-btn-sm" style="margin-left:8px;font-size:11px" onclick="switchTab('settings',document.querySelector('[data-tab=settings]'))">续费 →</button>
      </div>`;
  }
}

// ════════════════════════════════════════════════════

//  Skill 墙 tab-skills
// ════════════════════════════════════════════════════
async function skillsLoad() {
  const wall = document.getElementById('skillWall');
  const sumRow = document.getElementById('skillSummaryRow');
  const growthEl = document.getElementById('skillGrowthLog');
  if (wall) wall.innerHTML = '<div style="color:var(--muted);font-size:13px">加载中…</div>';
  try {
    const data = await fetch(`${CONFIG.api}/skills`).then(r => r.json());
    const { skills, summary } = data;
    // 摘要行
    if (sumRow && summary) {
      sumRow.innerHTML = `
        <div class="skill-sum-chip">共 <b>${summary.total||0}</b> 个 Skill</div>
        <div class="skill-sum-chip">内置 <b>${summary.builtin||0}</b> · 社区 <b>${summary.community||0}</b></div>
        <div class="skill-sum-chip">守藏升级 <b>${summary.upgraded||0}</b> 次</div>
        <div class="skill-sum-chip">平均评分 <b>${summary.avg_score ? summary.avg_score.toFixed(1) : '-'}</b></div>
      `;
    }
    // Skill 网格
    if (wall) {
      if (!(skills||[]).length) {
        wall.innerHTML = `
          <div class="empty-state-box" style="grid-column:1/-1">
            <div class="es-emoji">🧩</div>
            <div class="es-title">Skill 墙还没有积木</div>
            <div class="es-desc">Skill 是 Anima 的专项能力模块<br>守藏会在每日 SOP 后自动分析对话，为低分 Skill 自动升级</div>
            <div class="es-actions">
              <button class="btn-primary" onclick="fetch('${CONFIG.api}/shoucang/sop',{method:'POST'}).then(()=>toast('守藏 SOP 已启动','success'))">📜 立即运行守藏 SOP</button>
              <button class="hdr-btn-sm" onclick="document.getElementById('skillInstallUrl')?.focus()">📦 安装社区 Skill</button>
            </div>
            <div class="es-hint">首次运行 SOP 后，内置 Skill 将自动出现</div>
          </div>`;
        return;
      }
      wall.innerHTML = (skills||[]).map(s => `
        <div class="skill-card${s.locked?' locked':''}" data-id="${s.id}">
          <div class="skill-card-top">
            <div class="skill-icon">${s.icon||'⚙️'}</div>
            <div class="skill-card-meta">
              <div class="skill-card-name">${s.name}${s.premium?'<span class="skill-premium-badge">Pro</span>':''}</div>
              <div class="skill-card-cat">${s.category||''} · v${s.version||1}</div>
            </div>
            <div class="skill-score-badge">${s.avg_score ? s.avg_score.toFixed(1) : 'new'}</div>
          </div>
          <div class="skill-desc">${s.description||''}</div>
          <div class="skill-uses">${(s.use_cases||[]).map(u=>`<span class="skill-use-chip">${u}</span>`).join('')}</div>
          <div class="skill-footer">
            <span class="skill-stat">使用 ${s.usage_count||0} 次</span>
            ${s.last_improved ? `<span class="skill-stat">上次升级 ${s.last_improved}</span>` : ''}
            <span class="skill-source-badge ${s.source||'builtin'}">${s.source==='community'?'社区':'内置'}</span>
          </div>
        </div>
      `).join('') || '<div style="color:var(--muted)">暂无 Skill</div>';
      // Locked Skill 点击提示
      wall.querySelectorAll('.skill-card.locked').forEach(card => {
        card.addEventListener('click', () => {
          toast('🔒 此 Skill 为 Pro 专属，请在设置页激活会员', 'info');
          setTimeout(() => switchTab('settings', document.querySelector('[data-tab=settings]')), 1500);
        });
      });
    }
    // 成长记录：从升级记录里提取
    if (growthEl) {
      const upgraded = (skills||[]).filter(s => s.improvement_log?.length);
      if (upgraded.length) {
        growthEl.innerHTML = upgraded.flatMap(s =>
          (s.improvement_log||[]).slice(-2).reverse().map(log => `
            <div class="growth-log-item">
              <span class="growth-icon">${s.icon||'⚙️'}</span>
              <div>
                <span class="growth-skill">${s.name}</span> v${log.version||1}
                <span class="growth-date">${log.date||''}</span>
                <div class="growth-note">${log.note||''}</div>
              </div>
            </div>`)
        ).join('');
      } else {
        growthEl.textContent = '守藏尚未升级过任何 Skill。每天夜间，守藏会自动分析聊天记录并改进低分 Skill。';
      }
    }
  } catch(e) {
    if (wall) wall.innerHTML = `<div style="color:var(--error);font-size:13px">加载失败: ${e.message}</div>`;
  }
}
window.skillsLoad = skillsLoad;

window.skillInstall = async function() {
  const url = document.getElementById('skillInstallUrl')?.value.trim();
  if (!url) return;
  toast('⏳ 安装中…', 'info');
  try {
    const r = await fetch(`${CONFIG.api}/skills/install`, {
      method: 'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ url })
    });
    const data = await r.json();
    if (data.error) toast(`安装失败: ${data.error}`, 'error');
    else { toast(`✅ Skill 安装成功：${data.name||url}`, 'success'); skillsLoad(); }
  } catch(e) { toast(`安装失败: ${e.message}`, 'error'); }
};
