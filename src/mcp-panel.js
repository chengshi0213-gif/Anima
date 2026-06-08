/**
 * Anima — mcp-panel.js
 * 设置页「MCP 外部工具」面板（#22）：调用只读路由 /mcp/status|servers|tools 渲染状态。
 * 懒加载：设置页该 <details> 展开时由 ontoggle 调 window.mcpPanelLoad()。
 * 启停/增删 server 走编辑 config.yaml 的 mcp.servers（本面板只读展示 + 指引）。
 */
import { CONFIG, escHtml } from './state.js';

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
        一个协议接入无限外部工具（GitHub / 文件系统 / Notion…），无需手写集成。<br>
        在 <code>~/.anima/config.yaml</code> 的 <code>mcp.servers</code> 下添加并设 <code>enabled: true</code>，重启后端即生效。
      </div>`;
  }

  const rows = servers.map(s => {
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
  }).join('');

  const toolList = tools.length ? `
    <details class="mcp-tools">
      <summary>已连接的 ${tools.length} 个工具</summary>
      <div class="mcp-tool-grid">
        ${tools.map(t => `<div class="mcp-tool"><code>${escHtml(t.name)}</code><span>${escHtml((t.description || '').slice(0, 60))}</span></div>`).join('')}
      </div>
    </details>` : '';

  return head + `<div class="mcp-srv-list">${rows}</div>` + toolList;
}
