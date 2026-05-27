/**
 * Anima — main.js v2.0
 * Slim entry point: imports all modules, runs init, command palette, global keys
 */

// ── Module imports (side effects: each module registers its window.* functions) ──
import { CONFIG, AGENTS, runtime } from './state.js';
import { checkBackend, wsSend } from './ws.js';
import './chat.js';
import './overview.js';
import './workflow.js';
import './settings.js';

// ══════════════════════════════════════════════════
//  命令面板 (Ctrl+K)
// ══════════════════════════════════════════════════
const CMD_LIST = [
  { icon:'👩‍💼', label:'与 Anima 对话',   sub:'私人助理',     action:()=>window.switchTab('xi',   document.querySelector('[data-tab=xi]'))   },
  { icon:'🌸',  label:'与晞聊聊',       sub:'情感伙伴',     action:()=>window.switchTab('yiyi',     document.querySelector('[data-tab=yiyi]'))     },
  { icon:'🏢',  label:'向陶朱汇报',       sub:'创业CEO',      action:()=>window.switchTab('tianyuan', document.querySelector('[data-tab=tianyuan]')) },
  { icon:'🎓',  label:'守藏研究',         sub:'文献分析',     action:()=>window.switchTab('shoucang',  document.querySelector('[data-tab=shoucang]'))  },
  { icon:'🏠',  label:'总览',            sub:'工作台',       action:()=>window.switchTab('overview', document.querySelector('[data-tab=overview]')) },
  { icon:'📊',  label:'仪表盘',          sub:'Dashboard',    action:()=>window.switchTab('dashboard',document.querySelector('[data-tab=dashboard]'))},
  { icon:'🏗️', label:'陶朱团队',         sub:'子员工看板',   action:()=>{window.switchTab('tianyuan-team',document.querySelector('[data-tab=tianyuan-team]'));document.getElementById('subGroup-tianyuan')?.classList.remove('hidden');}},
  { icon:'✏️', label:'新对话',           sub:'打开新会话',   action:()=>window.newChat() },
  { icon:'↺',  label:'刷新总览',         sub:'',             action:()=>{window.switchTab('overview',document.querySelector('[data-tab=overview]'));window.loadOverview?.();} },
  { icon:'⚙️', label:'设置',            sub:'端口·快捷键',  action:()=>window.switchTab('settings', document.querySelector('[data-tab=settings]')) },
];

let cmdItems = CMD_LIST;
let cmdFocusIdx = -1;

window.openCmdPalette = function() {
  const overlay = document.getElementById('cmdOverlay');
  const input   = document.getElementById('cmdInput');
  overlay?.classList.remove('hidden');
  input && (input.value = '');
  input?.focus();
  cmdItems = CMD_LIST;
  cmdFocusIdx = -1;
  renderCmd();
};

window.closeCmdPalette = function(e) {
  if (!e || e.target === document.getElementById('cmdOverlay'))
    document.getElementById('cmdOverlay')?.classList.add('hidden');
};

window.updateCmdResults = function(q) {
  if (!q.trim()) { cmdItems = CMD_LIST; }
  else {
    const lq = q.toLowerCase();
    cmdItems = CMD_LIST.filter(c => c.label.toLowerCase().includes(lq) || c.sub.toLowerCase().includes(lq));
  }
  cmdFocusIdx = -1;
  renderCmd();
};

function renderCmd() {
  const el = document.getElementById('cmdResults');
  if (!el) return;
  el.innerHTML = cmdItems.map((c, i) => `
    <div class="cmd-result-item${i===cmdFocusIdx?' focused':''}" onclick="execCmd(${i})">
      <span class="cmd-icon">${c.icon}</span>
      <div><div class="cmd-result-label">${c.label}</div>${c.sub?`<div class="cmd-result-sub">${c.sub}</div>`:''}</div>
    </div>`).join('') || '<div style="padding:14px 20px;color:var(--muted);font-size:13px">无匹配</div>';
}

window.execCmd = function(idx) {
  const cmd = cmdItems[idx];
  if (!cmd) return;
  document.getElementById('cmdOverlay')?.classList.add('hidden');
  cmd.action();
};

window.handleCmdKey = function(e) {
  if (e.key === 'Escape') { document.getElementById('cmdOverlay')?.classList.add('hidden'); return; }
  if (e.key === 'ArrowDown') { e.preventDefault(); cmdFocusIdx = Math.min(cmdFocusIdx+1, cmdItems.length-1); renderCmd(); }
  if (e.key === 'ArrowUp')   { e.preventDefault(); cmdFocusIdx = Math.max(cmdFocusIdx-1, 0); renderCmd(); }
  if (e.key === 'Enter') { if (cmdFocusIdx>=0) window.execCmd(cmdFocusIdx); else if (cmdItems.length) window.execCmd(0); }
};

// ══════════════════════════════════════════════════
//  全局快捷键
// ══════════════════════════════════════════════════
document.addEventListener('keydown', e => {
  if ((e.ctrlKey||e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const ov = document.getElementById('cmdOverlay');
    if (ov?.classList.contains('hidden')) window.openCmdPalette();
    else ov?.classList.add('hidden');
  }
});

// ══════════════════════════════════════════════════
//  初始化
// ══════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', async () => {
  // 1. 等待后端就绪
  let ok = false;
  for (let i = 0; i < 20 && !ok; i++) {
    ok = await checkBackend();
    if (!ok) await new Promise(r => setTimeout(r, 2000));
  }
  if (!ok) setTimeout(() => checkBackend(false), 5000);
  setInterval(checkBackend, 30_000);
  setInterval(() => { for (const id of Object.keys(AGENTS)) wsSend(id, { action:'status' }); }, 60_000);

  // 2. 加载 agent 配置（名称/音色）
  if (ok) {
    await window.loadAgentConfig?.();

    // 3. 检查是否需要显示 Onboarding 向导
    try {
      const r = await fetch(`${CONFIG.api}/setup/status`);
      const { configured } = await r.json();
      if (!configured) {
        setTimeout(() => window.showOnboarding?.(), 500);
      } else {
        setTimeout(() => window.checkMorningReport?.(), 1500);
        setTimeout(() => window.apiCatalogLoad?.(), 2000);
      }
    } catch(_) {}
  }

  // GitHub 链接
  const ghLink = document.getElementById('ghLink');
  if (ghLink && window.__TAURI__) {
    try {
      const { open } = await import('@tauri-apps/plugin-opener');
      ghLink.addEventListener('click', e => {
        e.preventDefault();
        open('https://github.com/tianyuan-team/anima');
      });
    } catch(_) {}
  }
});
