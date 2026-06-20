/**
 * Anima — mcp-panel.js
 * 设置页「MCP 外部工具」面板：调用只读路由 /mcp/status|servers|tools 渲染状态。
 * v1.2.1: CN/Global 分栏展示，状态指示（已连/未连/需配置）。
 */
import { CONFIG, escHtml } from './state.js';

const REGION_GROUPS = {
  universal: { label: '通用', servers: new Set(['context7', 'mcp-video', 'playwright']) },
  cn:        { label: '国内', servers: new Set(['gitee', 'jina', 'kling', 'feishu', 'dingtalk', 'yuque']) },
  global:    { label: '国际', servers: new Set(['github', 'exa', 'slack', 'heygen', 'penpot']) },
};

function classifyServer(name) {
  for (const [region, { servers }] of Object.entries(REGION_GROUPS)) {
    if (servers.has(name)) return region;
  }
  return 'universal';
}

window.mcpPanelLoad = async function () {
  const body = document.getElementById('mcpPanelBody');
  if (!body) return;
  body.innerHTML = '<div class="mcp-empty">加载中…</div>';
  try {
    const [status, serversResp, toolsResp] = await Promise.all([
      fetch(`${CONFIG.api}/mcp/status`, CONFIG.fetchOpts()).then(r => r.json()),
      fetch(`${CONFIG.api}/mcp/servers`, CONFIG.fetchOpts()).then(r => r.json()),
      fetch(`${CONFIG.api}/mcp/tools`, CONFIG.fetchOpts()).then(r => r.json()),
    ]);
    body.innerHTML = renderPanel(status, serversResp.servers || [], toolsResp.tools || []);
  } catch (_) {
    body.innerHTML = '<div class="mcp-empty">无法读取 MCP 状态（后端未连接？）</div>';
  }
};

export function renderPanel(status, servers, tools) {
  const total = status.tool_count || 0;
  const head = `
    <div class="mcp-summary">
      <span class="mcp-stat"><b>${servers.length}</b> 个 server</span>
      <span class="mcp-dot">·</span>
      <span class="mcp-stat"><b>${(status.connected || []).length}</b> 已连接</span>
      <span class="mcp-dot">·</span>
      <span class="mcp-stat"><b>${total}</b> 个工具</span>
    </div>`;

  if (!servers.length) {
    return head + `
      <div class="mcp-empty">
        还没有配置 MCP server。<br>
        在 <code>~/.anima/config.yaml</code> 的 <code>mcp.servers</code> 下添加并设 <code>enabled: true</code>，重启后端即生效。
      </div>`;
  }

  const grouped = { universal: [], cn: [], global: [] };
  for (const s of servers) {
    const region = classifyServer(s.name);
    (grouped[region] || grouped.universal).push(s);
  }

  let sections = '';
  for (const [region, { label }] of Object.entries(REGION_GROUPS)) {
    const list = grouped[region];
    if (!list || !list.length) continue;
    sections += `<div class="mcp-region-section">
      <div class="mcp-region-label">${label}</div>
      <div class="mcp-srv-list">${list.map(renderServer).join('')}</div>
    </div>`;
  }

  const toolList = tools.length ? `
    <details class="mcp-tools">
      <summary>已连接的 ${tools.length} 个工具</summary>
      <div class="mcp-tool-grid">
        ${tools.map(t => `<div class="mcp-tool"><code>${escHtml(t.name)}</code><span>${escHtml((t.description || '').slice(0, 60))}</span></div>`).join('')}
      </div>
    </details>` : '';

  return head + sections + toolList;
}

function renderServer(s) {
  const state = s.connected
    ? '<span class="mcp-badge ok">● 已连接</span>'
    : s.enabled
      ? (s.error ? `<span class="mcp-badge err" title="${escHtml(s.error)}">● 失败</span>` : '<span class="mcp-badge off">○ 未连接</span>')
      : '<span class="mcp-badge off">○ 已禁用</span>';
  const meta = s.transport === 'stdio'
    ? `${escHtml(s.command || '')} ${escHtml((s.args || []).join(' '))}`.trim()
    : escHtml(s.url || '');
  const envHint = (s.env_keys || []).length
    ? `<span class="mcp-env" title="环境变量（仅显示名，值不外泄）">env: ${s.env_keys.map(escHtml).join(', ')}</span>`
    : '';
  return `
    <div class="mcp-srv">
      <div class="mcp-srv-top">
        <span class="mcp-srv-name">${escHtml(s.name)}</span>
        ${state}
        <span class="mcp-srv-count">${s.tool_count || 0} 工具</span>
      </div>
      <div class="mcp-srv-meta"><code>${meta}</code></div>
      ${s.error ? `<div class="mcp-srv-err">${escHtml(s.error)}</div>` : ''}
      ${envHint}
    </div>`;
}
