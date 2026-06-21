/**
 * Anima — mcp-panel.js
 * MCP 插件市场：预置常用 server 目录 + 接入向导 + 实时状态
 * v1.3.2: 重设计为市场模式，替换只读状态面板
 */
import { CONFIG, escHtml, toast } from './state.js';

const CATALOG = [
  // === 通用 ===
  {
    id: 'context7', name: 'Context7', region: 'universal', icon: '📚',
    desc: '官方文档库 · 实时拉取 npm/Python/React 等框架文档，减少幻觉',
    transport: 'stdio', command: 'npx', args: ['-y', '@upstash/context7-mcp'],
    fields: [],
  },
  {
    id: 'playwright', name: 'Playwright', region: 'universal', icon: '🌐',
    desc: '浏览器自动化 · 截图 / 点击 / 爬取网页，编写 UI 测试',
    transport: 'stdio', command: 'npx', args: ['-y', '@playwright/mcp@latest'],
    fields: [],
  },
  {
    id: 'filesystem', name: 'Filesystem', region: 'universal', icon: '📂',
    desc: '读写本地文件与目录 · 代码分析与文件操作必备',
    transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '/'],
    fields: [],
  },
  // === 国内 ===
  {
    id: 'amap', name: '高德地图', region: 'cn', icon: '🗺️',
    desc: '中国地图 / 路线规划 / POI 搜索（官方 MCP）',
    transport: 'stdio', command: 'npx', args: ['-y', '@amap/amap-maps-mcp-server'],
    fields: [{ key: 'AMAP_MAPS_API_KEY', label: '高德 API Key', hint: '高德开放平台 · lbs.amap.com', secret: false }],
  },
  {
    id: 'gitee', name: 'Gitee', region: 'cn', icon: '🐧',
    desc: '国内代码托管 · Issues / PR / 仓库管理',
    transport: 'stdio', command: 'npx', args: ['-y', '@gitee/mcp-gitee'],
    fields: [{ key: 'GITEE_API_TOKEN', label: 'Gitee API Token', hint: 'gitee.com/profile/personal_access_tokens', secret: true }],
  },
  {
    id: 'feishu', name: '飞书 / Lark', region: 'cn', icon: '🪶',
    desc: '消息 / 日历 / 文档 / 审批 · 飞书企业协作全套',
    transport: 'stdio', command: 'npx', args: ['-y', 'feishu-mcp'],
    fields: [
      { key: 'FEISHU_APP_ID', label: '飞书 App ID', hint: '开发者后台 → 应用信息', secret: false },
      { key: 'FEISHU_APP_SECRET', label: '飞书 App Secret', hint: '开发者后台 → 应用信息', secret: true },
    ],
  },
  {
    id: 'jina', name: 'Jina AI Reader', region: 'cn', icon: '🔍',
    desc: '网页阅读 / 语义搜索 · 对国内网站友好，支持中文',
    transport: 'stdio', command: 'npx', args: ['-y', 'jina-mcp-server'],
    fields: [{ key: 'JINA_API_KEY', label: 'Jina API Key', hint: 'jina.ai 免费注册获取', secret: true }],
  },
  {
    id: 'yuque', name: '语雀', region: 'cn', icon: '🦆',
    desc: '阿里语雀知识库 · 读写文档 / 知识空间 / 团队协作',
    transport: 'stdio', command: 'npx', args: ['-y', '@yuque/mcp-server'],
    fields: [{ key: 'YUQUE_TOKEN', label: '语雀 Token', hint: '语雀 → 个人中心 → Token', secret: true }],
  },
  {
    id: 'kling', name: 'Kling AI', region: 'cn', icon: '🎬',
    desc: '可灵 AI 视频生成 · 文生视频 / 图生视频，国产顶流',
    transport: 'stdio', command: 'npx', args: ['-y', 'kling-mcp'],
    fields: [{ key: 'KLING_API_KEY', label: '可灵 API Key', hint: 'klingai.com 开放平台申请', secret: true }],
  },
  {
    id: 'baidu-search', name: '百度搜索', region: 'cn', icon: '🔎',
    desc: '百度实时搜索 · 国内搜索结果覆盖更全面',
    transport: 'stdio', command: 'npx', args: ['-y', '@baidu/mcp-server-baidu-search'],
    fields: [{ key: 'BAIDU_API_KEY', label: '百度 API Key', hint: '百度 AI 开放平台申请', secret: true }],
  },
  // === 国际 ===
  {
    id: 'github', name: 'GitHub', region: 'global', icon: '🐙',
    desc: '仓库 / Issues / PR / 代码搜索 · GitHub 官方 MCP',
    transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-github'],
    fields: [{ key: 'GITHUB_PERSONAL_ACCESS_TOKEN', label: 'GitHub Token', hint: 'github.com/settings/tokens (repo scope)', secret: true }],
  },
  {
    id: 'exa', name: 'Exa Search', region: 'global', icon: '🌍',
    desc: '高质量语义网络搜索 · 返回全文而非摘要',
    transport: 'stdio', command: 'npx', args: ['-y', 'exa-mcp-server'],
    fields: [{ key: 'EXA_API_KEY', label: 'Exa API Key', hint: 'exa.ai 注册获取', secret: true }],
  },
  {
    id: 'slack', name: 'Slack', region: 'global', icon: '💬',
    desc: '团队协作 · 发消息 / 读频道 / 管理工作区',
    transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-slack'],
    fields: [
      { key: 'SLACK_BOT_TOKEN', label: 'Bot Token', hint: 'Slack App 管理界面 → OAuth Tokens', secret: true },
      { key: 'SLACK_TEAM_ID', label: 'Team ID', hint: 'Slack 工作区 URL 中可找到', secret: false },
    ],
  },
  {
    id: 'heygen', name: 'HeyGen', region: 'global', icon: '🎭',
    desc: 'AI 数字人视频生成 · 克隆声音 / 口播视频',
    transport: 'stdio', command: 'npx', args: ['-y', '@heygen/mcp-server'],
    fields: [{ key: 'HEYGEN_API_KEY', label: 'HeyGen API Key', hint: 'app.heygen.com/settings', secret: true }],
  },
];

const REGION_LABELS = { universal: '通用', cn: '国内', global: '国际' };
const REGION_COLORS = { universal: '#7C3AED', cn: '#D97706', global: '#2563EB' };

let _currentFilter = 'all';

window.mcpPanelLoad = async function () {
  const body = document.getElementById('mcpPanelBody');
  if (!body) return;
  body.innerHTML = '<div class="mcp-empty">加载中…</div>';
  try {
    const [statusResp, serversResp] = await Promise.all([
      fetch(`${CONFIG.api}/mcp/status`, CONFIG.fetchOpts()).then(r => r.json()),
      fetch(`${CONFIG.api}/mcp/servers`, CONFIG.fetchOpts()).then(r => r.json()),
    ]);
    body.innerHTML = _renderMarketplace(statusResp, serversResp.servers || []);
  } catch (_) {
    body.innerHTML = '<div class="mcp-empty">无法读取 MCP 状态（后端未连接？）</div>';
  }
};

function _renderMarketplace(status, configuredServers) {
  const connectedSet = new Set(status.connected || []);
  const configMap = {};
  for (const s of configuredServers) configMap[s.name] = s;

  const total = CATALOG.length;
  const connCount = connectedSet.size;

  const filterBar = `
    <div class="mcp-filters">
      <button class="mcp-filter-btn${_currentFilter === 'all' ? ' active' : ''}" onclick="mcpSetFilter('all')">全部 ${total}</button>
      <button class="mcp-filter-btn${_currentFilter === 'universal' ? ' active' : ''}" onclick="mcpSetFilter('universal')">通用</button>
      <button class="mcp-filter-btn${_currentFilter === 'cn' ? ' active' : ''}" onclick="mcpSetFilter('cn')">国内</button>
      <button class="mcp-filter-btn${_currentFilter === 'global' ? ' active' : ''}" onclick="mcpSetFilter('global')">国际</button>
    </div>`;

  const banner = connCount > 0
    ? `<div class="mcp-status-bar"><span class="mcp-status-dot">●</span> 已接入 ${connCount} 个 · ${status.tool_count || 0} 个工具可用 <span class="mcp-status-hint">改动需重启后端生效</span></div>`
    : '';

  const filtered = _currentFilter === 'all' ? CATALOG : CATALOG.filter(s => s.region === _currentFilter);

  const cards = filtered.map(item => {
    const cfg = configMap[item.id];
    const connected = connectedSet.has(item.id);
    const configured = !!cfg;
    const regionColor = REGION_COLORS[item.region] || '#666';

    let badge = '';
    let actionBtn = '';
    if (connected) {
      badge = `<span class="mcp-badge ok">● 已连接 · ${cfg?.tool_count || 0} 工具</span>`;
      actionBtn = `<button class="mcp-market-btn mcp-btn-disconnect" onclick="mcpDisconnect('${item.id}')">断开</button>`;
    } else if (configured) {
      const err = cfg?.error;
      badge = err
        ? `<span class="mcp-badge err" title="${escHtml(err)}">● 连接失败</span>`
        : `<span class="mcp-badge off">○ 已配置</span>`;
      actionBtn = `<button class="mcp-market-btn mcp-btn-connect" onclick="mcpOpenModal('${item.id}')">重配</button>`;
    } else {
      actionBtn = `<button class="mcp-market-btn mcp-btn-add" onclick="mcpOpenModal('${item.id}')">接入</button>`;
    }

    return `
      <div class="mcp-market-card${connected ? ' mcp-card-connected' : ''}">
        <div class="mcp-card-icon">${item.icon}</div>
        <div class="mcp-card-body">
          <div class="mcp-card-name">
            ${escHtml(item.name)}
            <span class="mcp-region-tag" style="color:${regionColor}">${REGION_LABELS[item.region]}</span>
          </div>
          <div class="mcp-card-desc">${escHtml(item.desc)}</div>
          ${badge}
        </div>
        <div class="mcp-card-action">${actionBtn}</div>
      </div>`;
  }).join('');

  return filterBar + banner + `<div class="mcp-market-grid">${cards}</div>`;
}

window.mcpSetFilter = function (filter) {
  _currentFilter = filter;
  mcpPanelLoad();
};

window.mcpOpenModal = function (serverId) {
  const item = CATALOG.find(s => s.id === serverId);
  if (!item) return;

  document.getElementById('mcpModal')?.remove();

  const fieldsHtml = item.fields.length
    ? item.fields.map(f => `
        <div style="margin-bottom:12px">
          <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">${escHtml(f.label)}</label>
          <input id="mcpField_${f.key}" type="${f.secret ? 'password' : 'text'}"
            placeholder="${f.hint ? escHtml(f.hint) : ''}"
            style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-main);color:var(--text-main);font-size:13px;box-sizing:border-box;font-family:monospace">
        </div>`).join('')
    : '<p style="font-size:13px;color:var(--muted);margin:0 0 4px">无需额外配置，直接接入即可。</p>';

  const overlay = document.createElement('div');
  overlay.id = 'mcpModal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999';
  overlay.innerHTML = `
    <div style="background:var(--bg-card,var(--bg));border-radius:14px;padding:24px 28px;width:460px;max-width:92vw;box-shadow:0 8px 40px rgba(0,0,0,.35)">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="font-size:24px">${item.icon}</span>
        <span style="font-size:17px;font-weight:700">${escHtml(item.name)}</span>
        <span class="mcp-region-tag" style="color:${REGION_COLORS[item.region]}">${REGION_LABELS[item.region]}</span>
      </div>
      <p style="font-size:13px;color:var(--muted);margin:0 0 18px;line-height:1.6">${escHtml(item.desc)}</p>
      ${fieldsHtml}
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
        <button onclick="document.getElementById('mcpModal').remove()"
          style="padding:8px 18px;border:1px solid var(--border);border-radius:8px;background:none;color:var(--muted);cursor:pointer">取消</button>
        <button onclick="mcpConnect('${serverId}')"
          style="padding:8px 20px;border:none;border-radius:8px;background:var(--accent,#7C3AED);color:#fff;font-weight:600;cursor:pointer">接入</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
};

window.mcpConnect = async function (serverId) {
  const item = CATALOG.find(s => s.id === serverId);
  if (!item) return;

  const env = {};
  for (const f of item.fields) {
    const val = document.getElementById(`mcpField_${f.key}`)?.value.trim() || '';
    if (val) env[f.key] = val;
  }

  document.getElementById('mcpModal')?.remove();
  toast(`正在接入 ${item.name}…`, 'info');

  try {
    const r = await fetch(`${CONFIG.api}/mcp/server`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: item.id,
        transport: item.transport,
        command: item.command,
        args: item.args,
        env,
        enabled: true,
      }),
    }).then(r => r.json());

    if (r.ok) {
      const toolNote = r.tool_count ? `，${r.tool_count} 个工具` : `（将在重启后端后连接）`;
      toast(`${item.name} 已接入${toolNote}`, 'success');
    } else {
      toast(`接入失败：${r.error || '未知错误'}`, 'error');
    }
  } catch (e) {
    toast(`接入失败：${e.message}`, 'error');
  }
  await mcpPanelLoad();
};

window.mcpDisconnect = async function (serverId) {
  const item = CATALOG.find(s => s.id === serverId);
  const name = item?.name || serverId;
  try {
    const r = await fetch(`${CONFIG.api}/mcp/server/${encodeURIComponent(serverId)}`, {
      method: 'DELETE',
    }).then(r => r.json());
    toast(r.ok ? `${name} 已断开并移除配置` : `操作失败：${r.error}`, r.ok ? 'success' : 'error');
  } catch (e) {
    toast(`操作失败：${e.message}`, 'error');
  }
  await mcpPanelLoad();
};

// 保留旧 API 供测试用
export function renderPanel(status, servers, tools) {
  return _renderMarketplace(status, servers);
}
