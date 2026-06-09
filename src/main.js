/**
 * Anima — main.js v2.0
 * Slim entry point: imports all modules, runs init, command palette, global keys
 */

// ── Module imports (side effects: each module registers its window.* functions) ──
// ?v=1.2.1 强制浏览器跳过 ES module 缓存（开发期 cache-bust，生产 Tauri 直接读磁盘无需关心）
import { CONFIG, AGENTS, runtime } from './state.js?v=1.2.1';
import { checkBackend, wsSend } from './ws.js?v=1.2.3';
import './invite-gate.js?v=1.2.1';
import './auth.js?v=1.2.1';
import './chat.js?v=1.2.3';
import './overview.js?v=1.2.1';
import './workflow.js?v=1.2.1';
import './settings.js?v=1.2.1';
import './mcp-panel.js?v=1.2.1';
import './economy.js?v=1.2.1';
import './anim.js?v=1.2.3';   // GSAP 编排层（必须最后 import：包装其它模块已注册的 window.* 函数）

// ══════════════════════════════════════════════════
//  命令面板 (Ctrl+K)
// ══════════════════════════════════════════════════
const CMD_LIST = [
  { icon:'🪔',  label:'与 Anima 对话',   sub:'可依靠的她',   action:()=>window.switchTab('xi',   document.querySelector('[data-tab=xi]'))   },
  { icon:'🏠',  label:'总览',            sub:'工作台',       action:()=>window.switchTab('overview', document.querySelector('[data-tab=overview]')) },
  { icon:'📊',  label:'仪表盘',          sub:'Dashboard',    action:()=>window.switchTab('dashboard',document.querySelector('[data-tab=dashboard]'))},
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

function applyThemeSwitchState(dark) {
  document.getElementById('themeToggle')?.classList.toggle('on', dark);
}

window.toggleTheme = function() {
  const dark = document.body.classList.toggle('dark');
  localStorage.setItem('anima-theme', dark ? 'dark' : 'light');
  applyThemeSwitchState(dark);
};

window.switchAutomationPane = function(pane, btn) {
  document.querySelectorAll('.automation-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.automation-tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`automation-${pane}`)?.classList.add('active');
  btn?.classList.add('active');

  if (pane === 'scheduler') { window.schedLoadTasks?.(); window.schedLoadLogs?.(); }
  if (pane === 'filewatcher') { window.fwLoadRules?.(); window.fwLoadEvents?.(); }
};

if (localStorage.getItem('anima-theme') === 'dark') {
  document.body.classList.add('dark');
}

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
  applyThemeSwitchState(document.body.classList.contains('dark'));

  // 1. 等待后端就绪
  let ok = false;
  for (let i = 0; i < 20 && !ok; i++) {
    ok = await checkBackend();
    if (!ok) await new Promise(r => setTimeout(r, 2000));
  }
  if (!ok) setTimeout(() => checkBackend(false), 5000);
  setInterval(checkBackend, 30_000);
  setInterval(() => { for (const id of Object.keys(AGENTS)) wsSend(id, { action:'status' }); }, 60_000);

  // 2. 结缘码门（未激活设备需输入邀请码）。后端离线/未配置时自动放行。
  await window.runInviteGate?.();

  // 3. 登录门控（首次设置密码 / 返回登录）。后端离线时自动跳过。
  await window.runAuthGate?.();

  // 4. 加载 agent 配置（名称/音色）
  if (ok) {
    await window.loadAgentConfig?.();

    // 5. 检查是否需要显示 Onboarding 向导
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

    // 6. 邀请人对账：补发"邀请成功 +30"灵犀（静默，有新增才提示）
    setTimeout(() => window.inviteReconcile?.(), 2500);
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

  // 监听 Tauri 后端推送的 update-available 事件，显示更新通知条
  // 同时监听后端守护进程的 backend-down / backend-up 健康事件
  if (window.__TAURI__) {
    try {
      const { listen } = await import('@tauri-apps/api/event');
      await listen('update-available', (event) => {
        const { version, body } = event.payload || {};
        showUpdateBanner(version, body);
      });
      // 后端连续重启失败：提示用户后端不可用
      await listen('backend-down', (event) => {
        const n = (event.payload && event.payload.failures) || 0;
        showBackendDownBanner(n);
      });
      // 后端恢复：移除提示条，并刷新邀请面板（修复"后端无响应"残留）
      await listen('backend-up', () => {
        const bar = document.getElementById('backend-down-banner');
        if (bar) bar.remove();
        // 若邀请面板正在显示（内容为"后端无响应"），自动重新加载
        const inviteList = document.getElementById('inviteCodesList');
        if (inviteList && inviteList.textContent.includes('后端无响应')) {
          window.inviteLoadPanel?.();
        }
      });
    } catch(_) {}
  }
});

// 后端不可用提示条
function showBackendDownBanner(failures) {
  if (document.getElementById('backend-down-banner')) return;
  const bar = document.createElement('div');
  bar.id = 'backend-down-banner';
  bar.innerHTML = `
    <span>⚠ 本地后端服务多次启动失败（已重试 ${failures} 次），AI 功能暂不可用</span>
    <button onclick="window.location.reload()">重新加载</button>
    <button onclick="this.closest('#backend-down-banner').remove()">忽略</button>
  `;
  document.body.appendChild(bar);
}

function showUpdateBanner(version, notes) {
  if (document.getElementById('update-banner')) return; // 已显示
  const bar = document.createElement('div');
  bar.id = 'update-banner';
  bar.innerHTML = `
    <span>✦ 新版本 <b>v${version || ''}</b> 已就绪</span>
    <button id="update-install-btn" onclick="installUpdate()">立即更新</button>
    <button id="update-dismiss-btn" onclick="this.closest('#update-banner').remove()">稍后</button>
  `;
  document.body.appendChild(bar);
}

window.installUpdate = async function() {
  const btn = document.getElementById('update-install-btn');
  if (btn) { btn.textContent = '下载中…'; btn.disabled = true; }
  try {
    const { check } = await import('@tauri-apps/plugin-updater');
    const { relaunch } = await import('@tauri-apps/plugin-process');
    const update = await check();
    if (update) {
      await update.downloadAndInstall();
      await relaunch();
    }
  } catch(e) {
    toast('更新失败：' + e, 'error');
    const btn = document.getElementById('update-install-btn');
    if (btn) { btn.textContent = '立即更新'; btn.disabled = false; }
  }
};
