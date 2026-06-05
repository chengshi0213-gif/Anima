/**
 * Anima — chat.js
 * Tab 切换、聊天 UI、模型选择器、文件上传、侧边栏历史
 */
import { CONFIG, AGENTS, WORKER_DETAILS, wsStatus, chatState, pendingFiles, selectedModel, runtime, escHtml, formatTime, toast, agentAvatarHtml, scrollBottom } from './state.js';
import { wsSend } from './ws.js';

// ══════════════════════════════════════════════════
//  Tab 切换
// ══════════════════════════════════════════════════
// 含独立人格主题的 Tab → 归一化的 data-agent 值（驱动 CSS 换主色/动效性格）
const AGENT_THEME_MAP = {
  xi: 'xi',
  'worker-executor': 'executor', 'worker-writer': 'writer',
  'worker-reader': 'reader', 'worker-critic': 'critic',
};

function applyAgentTheme(tabId) {
  const theme = AGENT_THEME_MAP[tabId];
  if (theme) document.body.dataset.agent = theme;
  else delete document.body.dataset.agent;
}

window.switchTab = function(tabId, el) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`tab-${tabId}`)?.classList.add('active');
  if (el) el.classList.add('active');
  else document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');

  applyAgentTheme(tabId);

  if (tabId === 'overview') window.loadOverview?.();
  if (tabId === 'dashboard') window.loadDashboard?.();
  if (tabId === 'settings') { window.membershipLoad?.(); window.inviteLoadPanel?.(); window.mailerLoad?.(); }
  if (tabId === 'workflow') setTimeout(() => window.PersonaWF?.init(), 30);  // Drawflow 需容器可见后初始化

  // 初始化子员工详情页
  const wrap = document.querySelector(`#tab-${tabId} .worker-detail-wrap`);
  if (wrap && !wrap.dataset.rendered) {
    const wId = wrap.dataset.worker;
    if (WORKER_DETAILS[wId]) window.renderWorkerDetail?.(wrap, wId);
    wrap.dataset.rendered = '1';
  }
};

// ══════════════════════════════════════════════════
//  团队展开/折叠
// ══════════════════════════════════════════════════
window.toggleTeam = function(e) {
  e.stopPropagation();
  // 团队展开/折叠已移除（人格合并），保留空函数避免调用报错
};

// ══════════════════════════════════════════════════
//  新对话
// ══════════════════════════════════════════════════
window.newChat = function() {
  window.switchTab('xi', document.querySelector('[data-tab=xi]'));
  window.clearChat('xi');
};

// ══════════════════════════════════════════════════
//  聊天 UI
// ══════════════════════════════════════════════════
window.sendMessage = function(agentId) {
  const inp  = document.getElementById(`input-${agentId}`);
  const text = inp?.value.trim();
  const files = pendingFiles[agentId] || [];
  if ((!text && !files.length) || chatState[agentId].pending) return;

  document.querySelector(`#messages-${agentId} .chat-welcome`)?.remove();
  appendUserMsg(agentId, text, files);
  inp.value = '';
  inp.style.height = 'auto';
  clearFileBar(agentId);

  const sent = wsSend(agentId, {
    action: 'chat',
    message: text,
    model: selectedModel[agentId],
    session_id: chatState[agentId].sessionId,
    files: files.map(f => ({ name: f.name, content: f.content, type: f.type })),
  });
  if (!sent) appendErrMsg(agentId, 'WebSocket 未连接，请等待自动重连');
  updateSendBtn(agentId);
};

export function appendUserMsg(agentId, text, files = []) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const filesHtml = files.map(f =>
    `<div style="font-size:11px;color:var(--muted);margin-top:4px">📎 ${escHtml(f.name)}</div>`
  ).join('');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `
    <div class="msg-avatar" style="background:var(--surface2)">🧑</div>
    <div class="msg-body">
      <div class="msg-bubble">${text ? escHtml(text) : ''}${filesHtml}</div>
      <div class="msg-meta">${formatTime(new Date())}</div>
    </div>`;
  box.appendChild(div);
  scrollBottom(agentId);
}

export function appendAssistantMsg(agentId, data) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const agent = AGENTS[agentId];
  const toolHtml = data.turn_count > 0 ? `
    <div class="tool-steps">
      <div class="tool-steps-hdr" onclick="toggleSteps(this)">
        <span class="chevron">▶</span>
        <span>${data.turn_count} 步推理</span>
        ${(data.files_changed||[]).length ? `<span style="margin-left:auto;font-size:10px;color:var(--warn)">${data.files_changed.length} 个文件</span>` : ''}
      </div>
      <div class="tool-steps-body">
        ${(data.files_changed||[]).map(f=>`<div class="tool-step-item">📄 <code>${escHtml(f)}</code></div>`).join('')||'<div class="tool-step-item">无文件变更</div>'}
      </div>
    </div>` : '';
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `
    ${agentAvatarHtml(agent)}
    <div class="msg-body">
      <div class="msg-bubble">${escHtml(data.summary || '（完成）')}</div>
      ${toolHtml}
      <div class="msg-meta">${agent.name} · ${formatTime(new Date())} · ${selectedModel[agentId]}</div>
    </div>`;
  box.appendChild(div);
  scrollBottom(agentId);
}
window.appendAssistantMsg = appendAssistantMsg;

export function appendErrMsg(agentId, text) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `
    <div class="msg-avatar" style="background:#FEE2E2">⚠️</div>
    <div class="msg-body">
      <div class="msg-bubble" style="border-color:#FCA5A5;color:var(--error)">${escHtml(text)}</div>
      <div class="msg-meta">${formatTime(new Date())}</div>
    </div>`;
  box.appendChild(div);
  scrollBottom(agentId);
}
window.appendErrMsg = appendErrMsg;

export function showThinking(agentId) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box || box.querySelector('.thinking-msg')) return;
  const agent = AGENTS[agentId];
  const div = document.createElement('div');
  div.className = 'msg assistant thinking-msg';
  div.innerHTML = `
    ${agentAvatarHtml(agent)}
    <div class="msg-body">
      <div class="thinking-indicator">
        思考中
        <div class="thinking-dots"><span></span><span></span><span></span></div>
      </div>
      <div class="thinking-live-steps"></div>
    </div>`;
  box.appendChild(div);
  scrollBottom(agentId);
}
window.showThinking = showThinking;

export function addThinkingStep(agentId, tool, args, turn) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const stepsEl = box.querySelector('.thinking-msg .thinking-live-steps');
  if (!stepsEl) return;

  const TOOL_ICONS = {
    file_read:'📄', file_write:'💾', file_edit:'✏️', file_list:'📁',
    shell_run:'⚙️', web_search:'🔍', web_fetch:'🌐', note_write:'📝',
  };
  const icon = TOOL_ICONS[tool] || '🔧';

  let argSummary = '';
  if (args && typeof args === 'object') {
    const firstVal = Object.values(args)[0];
    if (firstVal !== undefined) argSummary = String(firstVal).slice(0, 40);
  }

  const item = document.createElement('div');
  item.className = 'thinking-step-item running';
  item.dataset.tool = tool;
  item.innerHTML = `
    <span class="ts-icon">${icon}</span>
    <span class="ts-name">${escHtml(tool)}</span>
    ${argSummary ? `<span class="ts-arg">${escHtml(argSummary)}</span>` : ''}
    <span class="ts-spin">⟳</span>`;
  stepsEl.appendChild(item);
  scrollBottom(agentId);
}
window.addThinkingStep = addThinkingStep;

export function markThinkingStep(agentId, tool, ok, hint) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const items = [...box.querySelectorAll(`.thinking-live-steps .thinking-step-item[data-tool="${tool}"].running`)];
  const item = items[items.length - 1];
  if (!item) return;
  item.classList.remove('running');
  item.classList.add(ok ? 'done' : 'fail');
  const spin = item.querySelector('.ts-spin');
  if (spin) spin.textContent = ok ? '✓' : '✗';
  if (!ok && hint) {
    const err = document.createElement('span');
    err.className = 'ts-err';
    err.textContent = hint;
    item.appendChild(err);
  }
  scrollBottom(agentId);
}
window.markThinkingStep = markThinkingStep;

export function removeThinking(agentId) {
  document.querySelector(`#messages-${agentId} .thinking-msg`)?.remove();
}
window.removeThinking = removeThinking;

window.clearChat = function(agentId) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const agent = AGENTS[agentId];
  const avatar = agent.avatarImg
    ? `<div class="welcome-avatar ${agent.colorClass} welcome-avatar-img"><img src="${agent.avatarImg}" alt="${agent.name}"></div>`
    : `<div class="welcome-avatar ${agent.colorClass}">${agent.icon}</div>`;
  box.innerHTML = `
    <div class="chat-welcome">
      ${avatar}
      <div class="welcome-name">${agent.name}</div>
      <div class="welcome-desc">${agent.title}</div>
    </div>`;
  chatState[agentId].sessionId = null;
  clearFileBar(agentId);
};

window.fillInput = function(agentId, text) {
  const inp = document.getElementById(`input-${agentId}`);
  if (!inp) return;
  inp.value = text;
  inp.focus();
  window.autoResize(inp);
  updateSendBtn(agentId);
};

window.handleInputKey = function(e, agentId) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); window.sendMessage(agentId); }
  if (e.key === 'Escape') {
    const inp = document.getElementById(`input-${agentId}`);
    if (inp) { inp.value = ''; window.autoResize(inp); updateSendBtn(agentId); }
  }
};

window.autoResize = function(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  const agentId = el.id.replace('input-', '');
  updateSendBtn(agentId);
};

window.toggleSteps = function(hdr) {
  hdr.classList.toggle('open');
  hdr.nextElementSibling?.classList.toggle('open');
};

export function setInputState(agentId, disabled) {
  const inp = document.getElementById(`input-${agentId}`);
  const btn = document.getElementById(`send-${agentId}`);
  if (inp) inp.disabled = disabled;
  if (btn) btn.disabled = disabled || true;
  if (!disabled) updateSendBtn(agentId);
}
window.setInputState = setInputState;

function updateSendBtn(agentId) {
  const inp  = document.getElementById(`input-${agentId}`);
  const btn  = document.getElementById(`send-${agentId}`);
  if (!btn) return;
  const hasText  = inp?.value.trim().length > 0;
  const hasFiles = (pendingFiles[agentId]||[]).length > 0;
  const pending  = chatState[agentId]?.pending;
  btn.disabled = pending || (!hasText && !hasFiles);
}

export function updateAgentUI(agentId) {
  const s = wsStatus[agentId];
  const agent = AGENTS[agentId];
  const meta = document.getElementById(`meta-${agentId}`);
  if (meta) meta.textContent = s.connected
    ? `${agent.title} · ${s.model} · ${s.tools} 工具`
    : `${agent.title} · 未连接`;
  const dot = document.getElementById(`dot-${agentId}`);
  if (dot) dot.className = 'agent-dot ' + (s.busy ? 'busy' : s.connected ? 'online' : 'offline');
}
window.updateAgentUI = updateAgentUI;

// ══════════════════════════════════════════════════
//  模型选择器
// ══════════════════════════════════════════════════
window.toggleModelMenu = function(agentId, e) {
  e?.stopPropagation();
  const menu = document.getElementById(`modelMenu-${agentId}`);
  if (!menu) return;
  document.querySelectorAll('.model-menu').forEach(m => { if (m !== menu) m.classList.add('hidden'); });
  menu.classList.toggle('hidden');
};

window.selectModel = function(agentId, model) {
  selectedModel[agentId] = model;
  const label = document.getElementById(`modelLabel-${agentId}`);
  if (label) label.textContent = model;
  document.getElementById(`modelMenu-${agentId}`)?.classList.add('hidden');
  document.querySelectorAll(`#modelMenu-${agentId} .model-option`).forEach(opt => {
    opt.classList.toggle('selected', opt.textContent.trim().startsWith(model));
  });
  toast(`${AGENTS[agentId].name} 已切换到 ${model}`);
};

document.addEventListener('click', () => {
  document.querySelectorAll('.model-menu').forEach(m => m.classList.add('hidden'));
});

// ══════════════════════════════════════════════════
//  文件上传（Claude 风格）
// ══════════════════════════════════════════════════
window.triggerFileUpload = function(agentId) {
  document.getElementById(`fileInput-${agentId}`)?.click();
};

window.handleFileSelect = async function(agentId, input) {
  const files = Array.from(input.files || []);
  if (!files.length) return;

  for (const file of files) {
    if (file.size > 4 * 1024 * 1024) {
      toast(`${file.name} 超过 4MB 限制`, 'warn');
      continue;
    }
    const content = await readFileAsText(file);
    pendingFiles[agentId].push({ name: file.name, content, type: file.type, size: file.size });
    addFileChip(agentId, file.name, pendingFiles[agentId].length - 1);
  }
  input.value = '';
  updateSendBtn(agentId);
};

function readFileAsText(file) {
  return new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result || '');
    reader.onerror = () => resolve('');
    reader.readAsText(file, 'utf-8');
  });
}

function addFileChip(agentId, name, idx) {
  const bar = document.getElementById(`fileBar-${agentId}`);
  if (!bar) return;
  bar.classList.remove('hidden');
  const chip = document.createElement('div');
  chip.className = 'file-chip';
  chip.dataset.idx = idx;
  chip.innerHTML = `<span>📎 ${escHtml(name)}</span><span class="file-chip-remove" onclick="removeFile('${agentId}',${idx})">×</span>`;
  bar.appendChild(chip);
}

window.removeFile = function(agentId, idx) {
  pendingFiles[agentId].splice(idx, 1);
  rebuildFileBar(agentId);
  updateSendBtn(agentId);
};

function rebuildFileBar(agentId) {
  const bar = document.getElementById(`fileBar-${agentId}`);
  if (!bar) return;
  bar.innerHTML = '';
  if (!pendingFiles[agentId].length) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  pendingFiles[agentId].forEach((f, i) => {
    const chip = document.createElement('div');
    chip.className = 'file-chip';
    chip.innerHTML = `<span>📎 ${escHtml(f.name)}</span><span class="file-chip-remove" onclick="removeFile('${agentId}',${i})">×</span>`;
    bar.appendChild(chip);
  });
}

function clearFileBar(agentId) {
  pendingFiles[agentId] = [];
  const bar = document.getElementById(`fileBar-${agentId}`);
  if (bar) { bar.innerHTML = ''; bar.classList.add('hidden'); }
  updateSendBtn(agentId);
}

// ══════════════════════════════════════════════════
//  侧边栏历史（按时间分组）
// ══════════════════════════════════════════════════
export async function loadSidebarHistory() {
  const container = document.getElementById('historyGroups');
  if (!container) return;
  try {
    const { sessions } = await fetch(`${CONFIG.api}/sessions?limit=40`).then(r => r.json());
    renderSidebarHistory(sessions || []);
  } catch (_) {
    container.innerHTML = '<div class="history-loading">暂无记录</div>';
  }
}
window.loadSidebarHistory = loadSidebarHistory;

function renderSidebarHistory(sessions) {
  const container = document.getElementById('historyGroups');
  if (!container) return;
  if (!sessions.length) { container.innerHTML = '<div class="history-loading">暂无会话记录</div>'; return; }

  const now   = new Date();
  const today = startOfDay(now);
  const yest  = startOfDay(new Date(now - 86400000));
  const week  = startOfDay(new Date(now - 6 * 86400000));

  const groups = { today:[], yesterday:[], week:[], older:[] };
  for (const s of sessions) {
    const d = new Date(s.timestamp || 0);
    if (d >= today)     groups.today.push(s);
    else if (d >= yest) groups.yesterday.push(s);
    else if (d >= week) groups.week.push(s);
    else                groups.older.push(s);
  }

  const labels = { today:'今天', yesterday:'昨天', week:'7天内', older:'更早' };
  let html = '';
  for (const [key, label] of Object.entries(labels)) {
    if (!groups[key].length) continue;
    html += `<div class="history-group"><div class="history-group-label">${label}</div>`;
    for (const s of groups[key]) {
      const agent = AGENTS[s.agent] || { icon:'💬' };
      const sum   = (s.summary || s.session_id.slice(-10)).slice(0, 28);
      html += `<div class="history-item" onclick="openSession('${s.session_id}','${s.agent}')">${agent.icon} ${escHtml(sum)}</div>`;
    }
    html += '</div>';
  }
  container.innerHTML = html;
}

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

window.openSession = async function(sessionId, agentId) {
  if (!AGENTS[agentId]) return;
  window.switchTab(agentId, document.querySelector(`[data-tab="${agentId}"]`));
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  box.innerHTML = `<div style="text-align:center;padding:24px;color:var(--muted);font-size:13px">加载历史…</div>`;
  chatState[agentId].sessionId = sessionId;
  try {
    const { messages } = await fetch(`${CONFIG.api}/sessions/${sessionId}/messages`).then(r => r.json());
    box.innerHTML = '';
    for (const m of (messages || [])) {
      if (m.role === 'user')      appendUserMsg(agentId, m.content);
      else if (m.role === 'assistant') appendAssistantMsg(agentId, { summary: m.content, turn_count: 0 });
    }
    if (!messages?.length) box.innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted)">该会话无消息</div>';
    toast('已加载历史会话', 'success');
  } catch (_) {
    box.innerHTML = '<div style="text-align:center;padding:40px;color:var(--error)">加载失败</div>';
  }
};

// ══════════════════════════════════════════════════
//  端口设置
// ══════════════════════════════════════════════════
window.applyPorts = function() {
  CONFIG.wsPort   = parseInt(document.getElementById('wsPort')?.value) || 9100;
  CONFIG.dashPort = parseInt(document.getElementById('dashPort')?.value) || 9119;
  runtime.backendOnline = false;
  for (const id of Object.keys(AGENTS)) {
    wsConns[id]?.close();
    wsStatus[id] = { model:'-', tools:0, busy:false, connected:false };
    updateAgentUI(id);
  }
  window.checkBackend();
};
