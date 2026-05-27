/**
 * Anima — main.js v1.0
 * Light Theme · Onboarding · Agent Names · TTS · Feishu-style Group Chat
 */

// ══════════════════════════════════════════════════
//  配置 & 常量
// ══════════════════════════════════════════════════
let CONFIG = {
  wsPort: 9100,
  dashPort: 9119,
  token: localStorage.getItem('anima_local_token') || '',
  get api()   { return `http://localhost:${this.wsPort}`; },
  get wsBase(){ return `ws://localhost:${this.wsPort}`; },
  /** 构造带 Authorization 头的 fetch options */
  fetchOpts(extra = {}) {
    const headers = { ...(extra.headers || {}) };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    return { ...extra, headers };
  },
};

const AGENTS = {
  // avatarImg: 自定义图片头像路径（相对 src/），优先于 icon emoji
  xi:       { id:'xi',   name:'Anima', icon:'👩‍💼', avatarImg:'assets/xi-avatar.png', title:'私人助理',  colorClass:'xi-bg'   },
  yiyi:     { id:'yiyi',     name:'晞',   icon:'🌸',  title:'情感伙伴',  colorClass:'yiyi-bg'     },
  tianyuan: { id:'tianyuan', name:'陶朱',   icon:'🏢',  title:'创业CEO',   colorClass:'tianyuan-bg' },
  shoucang: { id:'shoucang', name:'守藏',   icon:'📜',  title:'知识研究员', colorClass:'shoucang-bg' },
  executor: { id:'executor', name:'执行者', icon:'⚡',  title:'任务执行',   colorClass:'executor-bg' },
  writer:   { id:'writer',   name:'写手',   icon:'✍️',  title:'内容创作',   colorClass:'writer-bg'   },
  reader:   { id:'reader',   name:'阅读者', icon:'📖',  title:'文档阅读',   colorClass:'reader-bg'   },
  critic:   { id:'critic',   name:'评审',   icon:'🔍',  title:'质量把关',   colorClass:'critic-bg'   },
};

const WORKER_DETAILS = {
  executor: { name:'执行者', icon:'⚡', model:'DeepSeek-V4-Flash', desc:'代码执行 · 任务拆解 · 自动化',    cls:'executor-bg', tools:6 },
  writer:   { name:'写手',   icon:'✍️', model:'Kimi-K2.6',          desc:'文案撰写 · 报告 · 内容创作',     cls:'writer-bg',   tools:2 },
  reader:   { name:'阅读者', icon:'📖', model:'Kimi-128K',           desc:'长文阅读 · 文献分析 · 摘要',     cls:'reader-bg',   tools:2 },
  critic:   { name:'评审',   icon:'🔍', model:'DeepSeek-R1',         desc:'质量检查 · 批判思维 · 风险评估', cls:'critic-bg',   tools:2 },
};

// ══════════════════════════════════════════════════
//  运行时状态
// ══════════════════════════════════════════════════
const wsConns  = {};
const wsStatus = {};
const chatState = {};
const pendingFiles = {};    // agentId → [{name, content, size}]
const selectedModel = {     // agentId → modelName (前端显示，实际调用由后端配置决定)
  xi:       'DeepSeek-V4-Flash',  // 私人助理：最新最快
  yiyi:     'Qwen3.7-Max',        // 情感伙伴：最新旗舰
  tianyuan: 'DeepSeek-R1',        // 创业CEO：推理决策
  shoucang:  'Kimi-K2.6',          // 知识研究员：最新旗舰
  // 陶朱子员工：固定模型，不可用户切换
  executor: 'DeepSeek-V4-Flash',  // 执行者：最快
  writer:   'Kimi-K2.6',          // 写手：中文旗舰
  reader:   'Kimi-128K',          // 阅读者：超长上下文
  critic:   'DeepSeek-R1',        // 评审：深度推理
};

let backendOnline = false;
let cmdItems = [];
let cmdFocusIdx = -1;

for (const id of Object.keys(AGENTS)) {
  wsStatus[id]   = { model:'-', tools:0, busy:false, connected:false };
  chatState[id]  = { pending:false, sessionId:null };
  pendingFiles[id] = [];
}

// ══════════════════════════════════════════════════
//  Agent 头像 HTML helper
//  优先使用 agent.avatarImg（图片），回退到 agent.icon（emoji）
// ══════════════════════════════════════════════════
function agentAvatarHtml(agent) {
  if (agent?.avatarImg) {
    return `<div class="msg-avatar ${agent.colorClass} msg-avatar-img">` +
           `<img src="${agent.avatarImg}" alt="${agent.name}" ` +
           `onerror="this.parentElement.innerHTML='${agent.icon}';this.parentElement.classList.remove('msg-avatar-img')">` +
           `</div>`;
  }
  return `<div class="msg-avatar ${agent.colorClass}">${agent.icon}</div>`;
}

// ══════════════════════════════════════════════════
//  Tab 切换
// ══════════════════════════════════════════════════
window.switchTab = function(tabId, el) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`tab-${tabId}`)?.classList.add('active');
  if (el) el.classList.add('active');
  else document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');

  if (tabId === 'overview') loadOverview();
  if (tabId === 'dashboard') loadDashboard();
  if (tabId === 'settings') membershipLoad();

  // 初始化子员工详情页
  const wrap = document.querySelector(`#tab-${tabId} .worker-detail-wrap`);
  if (wrap && !wrap.dataset.rendered) {
    const wId = wrap.dataset.worker;
    if (WORKER_DETAILS[wId]) renderWorkerDetail(wrap, wId);
    wrap.dataset.rendered = '1';
  }
};

// ══════════════════════════════════════════════════
//  陶朱团队展开/折叠
// ══════════════════════════════════════════════════
window.toggleTeam = function(e) {
  e.stopPropagation();
  const sub = document.getElementById('subGroup-tianyuan');
  const chev = document.getElementById('chevron-tianyuan');
  if (!sub) return;
  const isOpen = !sub.classList.contains('hidden');
  sub.classList.toggle('hidden', isOpen);
  if (chev) chev.classList.toggle('open', !isOpen);
};

// ══════════════════════════════════════════════════
//  新对话
// ══════════════════════════════════════════════════
window.newChat = function() {
  // 默认打开 Anima，清空会话
  switchTab('xi', document.querySelector('[data-tab=xi]'));
  clearChat('xi');
};

// ══════════════════════════════════════════════════
//  后端健康检查
// ══════════════════════════════════════════════════
async function checkBackend(forceRetry = false) {
  const dot  = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  dot.className = 'status-dot loading';
  text.textContent = '连接中…';

  let healthData = null;

  // ── 优先：通过 Tauri IPC（原生 TcpStream）直接访问后端 ──────────
  // 完全绕过 WebView2 网络栈，不受 FlClash 等系统代理影响
  try {
    const invoke = window.__TAURI__?.core?.invoke;
    if (invoke) {
      const body = await invoke('health_check');   // Rust: GET /health via TcpStream
      healthData = JSON.parse(body);
    }
  } catch (_tauriErr) {
    // Tauri IPC 不可用或后端未就绪，继续尝试 fetch 回退
  }

  // ── 回退：直接 fetch（开发模式 / 代理已关闭时有效）─────────────
  if (!healthData) {
    try {
      const _ctrl = new AbortController();
      const _tid  = setTimeout(() => _ctrl.abort(), 4000);
      const r = await fetch(`${CONFIG.api}/health`, { signal: _ctrl.signal }).finally(() => clearTimeout(_tid));
      if (r.ok) {
        healthData = await r.json().catch(() => ({}));
      }
    } catch (_fetchErr) {}
  }

  if (healthData) {
    // 存储本地 token（后端只对本地 IP 返回）
    if (healthData.local_token) {
      localStorage.setItem('anima_local_token', healthData.local_token);
      CONFIG.token = healthData.local_token;
    }
    dot.className  = 'status-dot online';
    text.textContent = '已连接';
    document.getElementById('offlineOverlay')?.classList.add('hidden');
    if (!backendOnline) {
      backendOnline = true;
      initAllWS();
      loadOverview();
      loadSidebarHistory();
      setTimeout(() => projectSwitcherLoad(), 1200); // 初始化项目切换器
    }
    return true;
  }

  dot.className  = 'status-dot error';
  text.textContent = '后端离线';
  backendOnline = false;
  if (forceRetry) toast('无法连接后端，请检查服务是否启动', 'error');
  return false;
}
window.checkBackend = checkBackend;

// ══════════════════════════════════════════════════
//  WebSocket 管理
// ══════════════════════════════════════════════════
function initAllWS() {
  for (const id of Object.keys(AGENTS)) initAgentWS(id);
}

function initAgentWS(agentId) {
  if (wsConns[agentId] && wsConns[agentId].readyState < WebSocket.CLOSING) return;
  const ws = new WebSocket(`${CONFIG.wsBase}/ws/${agentId}`);
  wsConns[agentId] = ws;
  ws.onopen = () => {
    wsStatus[agentId].connected = true;
    ws.send(JSON.stringify({ action:'status' }));
    if (document.getElementById('tab-overview')?.classList.contains('active')) loadOverview();
  };
  ws.onmessage = (e) => {
    try { handleAgentMessage(agentId, JSON.parse(e.data)); } catch(_) {}
  };
  ws.onclose = () => {
    wsStatus[agentId].connected = false;
    updateAgentUI(agentId);
    if (backendOnline) setTimeout(() => initAgentWS(agentId), 3000);
  };
  ws.onerror = () => {};
}

function wsSend(agentId, data) {
  const ws = wsConns[agentId];
  if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(data)); return true; }
  return false;
}

// ══════════════════════════════════════════════════
//  Agent 消息处理
// ══════════════════════════════════════════════════
function handleAgentMessage(agentId, msg) {
  // status 查询响应
  if (msg.type === 'response' && msg.data?.agent !== undefined) {
    Object.assign(wsStatus[agentId], { model: msg.data.model||'-', tools: msg.data.tools||0, busy: msg.data.busy||false });
    updateAgentUI(agentId);
    return;
  }
  // chat 开始
  if (msg.type === 'status' && msg.status === 'running') {
    chatState[agentId].pending   = true;
    chatState[agentId].sessionId = msg.session_id;
    wsStatus[agentId].busy       = true;
    setInputState(agentId, true);
    updateAgentUI(agentId);
    showThinking(agentId);
    return;
  }
  // chat 完成
  if (msg.type === 'response' && msg.data?.status) {
    removeThinking(agentId);
    chatState[agentId].pending = false;
    wsStatus[agentId].busy     = false;
    setInputState(agentId, false);
    updateAgentUI(agentId);
    appendAssistantMsg(agentId, msg.data);
    toast(`${AGENTS[agentId].icon} ${AGENTS[agentId].name} 已回复`, 'success');
    loadSidebarHistory();
    return;
  }
  // ── 实时工具调用步骤流 ──
  if (msg.type === 'tool_start') {
    addThinkingStep(agentId, msg.data?.tool, msg.data?.args, msg.data?.turn);
    return;
  }
  if (msg.type === 'tool_done') {
    markThinkingStep(agentId, msg.data?.tool, msg.data?.ok, msg.data?.hint);
    return;
  }

  // permission_request — API 权限需求卡片
  if (msg.type === 'permission_request') {
    removeThinking(agentId);
    chatState[agentId].pending = false;
    wsStatus[agentId].busy     = false;
    setInputState(agentId, false);
    updateAgentUI(agentId);
    showPermissionRequest(agentId, msg.data);
    return;
  }

  // error
  if (msg.type === 'error') {
    removeThinking(agentId);
    chatState[agentId].pending = false;
    wsStatus[agentId].busy     = false;
    setInputState(agentId, false);
    updateAgentUI(agentId);
    appendErrMsg(agentId, msg.message || '未知错误');
    toast(msg.message || '出错了', 'error');
  }
}

// ══════════════════════════════════════════════════
//  聊天 UI
// ══════════════════════════════════════════════════
window.sendMessage = function(agentId) {
  const inp  = document.getElementById(`input-${agentId}`);
  const text = inp?.value.trim();
  const files = pendingFiles[agentId] || [];
  if ((!text && !files.length) || chatState[agentId].pending) return;

  // 清除欢迎屏
  document.querySelector(`#messages-${agentId} .chat-welcome`)?.remove();

  // 显示用户消息
  appendUserMsg(agentId, text, files);
  inp.value = '';
  inp.style.height = 'auto';
  clearFileBar(agentId);

  // 发送
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

function appendUserMsg(agentId, text, files = []) {
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

function appendAssistantMsg(agentId, data) {
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

function appendErrMsg(agentId, text) {
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

function showThinking(agentId) {
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

/** 向思考气泡追加一个"正在执行"的工具步骤行 */
function addThinkingStep(agentId, tool, args, turn) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const stepsEl = box.querySelector('.thinking-msg .thinking-live-steps');
  if (!stepsEl) return;

  // 友好工具名映射
  const TOOL_ICONS = {
    file_read:'📄', file_write:'💾', file_edit:'✏️', file_list:'📁',
    shell_run:'⚙️', web_search:'🔍', web_fetch:'🌐', note_write:'📝',
  };
  const icon = TOOL_ICONS[tool] || '🔧';

  // 简短参数摘要（最多显示首个参数值）
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

/** 将对应工具步骤标记为完成或失败 */
function markThinkingStep(agentId, tool, ok, hint) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  // 找最后一个匹配该工具名的 running item
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
function removeThinking(agentId) {
  document.querySelector(`#messages-${agentId} .thinking-msg`)?.remove();
}

window.clearChat = function(agentId) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const agent = AGENTS[agentId];
  box.innerHTML = `
    <div class="chat-welcome">
      <div class="welcome-avatar ${agent.colorClass}">${agent.icon}</div>
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
  autoResize(inp);
  updateSendBtn(agentId);
};

window.handleInputKey = function(e, agentId) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(agentId); }
  if (e.key === 'Escape') {
    const inp = document.getElementById(`input-${agentId}`);
    if (inp) { inp.value = ''; autoResize(inp); updateSendBtn(agentId); }
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

function setInputState(agentId, disabled) {
  const inp = document.getElementById(`input-${agentId}`);
  const btn = document.getElementById(`send-${agentId}`);
  if (inp) inp.disabled = disabled;
  if (btn) btn.disabled = disabled || true; // will be managed by updateSendBtn
  if (!disabled) updateSendBtn(agentId);
}

function updateSendBtn(agentId) {
  const inp  = document.getElementById(`input-${agentId}`);
  const btn  = document.getElementById(`send-${agentId}`);
  if (!btn) return;
  const hasText  = inp?.value.trim().length > 0;
  const hasFiles = (pendingFiles[agentId]||[]).length > 0;
  const pending  = chatState[agentId]?.pending;
  btn.disabled = pending || (!hasText && !hasFiles);
}

function updateAgentUI(agentId) {
  const s = wsStatus[agentId];
  const agent = AGENTS[agentId];
  // meta
  const meta = document.getElementById(`meta-${agentId}`);
  if (meta) meta.textContent = s.connected
    ? `${agent.title} · ${s.model} · ${s.tools} 工具`
    : `${agent.title} · 未连接`;
  // dot
  const dot = document.getElementById(`dot-${agentId}`);
  if (dot) dot.className = 'agent-dot ' + (s.busy ? 'busy' : s.connected ? 'online' : 'offline');
}

function scrollBottom(agentId) {
  const el = document.getElementById(`messages-${agentId}`);
  if (el) el.scrollTop = el.scrollHeight;
}

// ══════════════════════════════════════════════════
//  模型选择器
// ══════════════════════════════════════════════════
window.toggleModelMenu = function(agentId, e) {
  e?.stopPropagation();
  const menu = document.getElementById(`modelMenu-${agentId}`);
  if (!menu) return;
  // 关闭其他
  document.querySelectorAll('.model-menu').forEach(m => { if (m !== menu) m.classList.add('hidden'); });
  menu.classList.toggle('hidden');
};

window.selectModel = function(agentId, model) {
  selectedModel[agentId] = model;
  const label = document.getElementById(`modelLabel-${agentId}`);
  if (label) label.textContent = model;
  document.getElementById(`modelMenu-${agentId}`)?.classList.add('hidden');
  // 高亮选中项
  document.querySelectorAll(`#modelMenu-${agentId} .model-option`).forEach(opt => {
    opt.classList.toggle('selected', opt.textContent.trim().startsWith(model));
  });
  toast(`${AGENTS[agentId].name} 已切换到 ${model}`);
};

// 点击外部关闭模型菜单
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
  input.value = ''; // 允许重复选同一文件
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
async function loadSidebarHistory() {
  const container = document.getElementById('historyGroups');
  if (!container) return;
  try {
    const { sessions } = await fetch(`${CONFIG.api}/sessions?limit=40`).then(r => r.json());
    renderSidebarHistory(sessions || []);
  } catch (_) {
    container.innerHTML = '<div class="history-loading">暂无记录</div>';
  }
}

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
  switchTab(agentId, document.querySelector(`[data-tab="${agentId}"]`));
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
//  总览面板
// ══════════════════════════════════════════════════
async function loadOverview() {
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

async function loadDashboard() {
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
function renderWorkerDetail(wrap, workerId) {
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

// ══════════════════════════════════════════════════
//  命令面板 (Ctrl+K)
// ══════════════════════════════════════════════════
const CMD_LIST = [
  { icon:'👩‍💼', label:'与 Anima 对话',   sub:'私人助理',     action:()=>switchTab('xi',   document.querySelector('[data-tab=xi]'))   },
  { icon:'🌸',  label:'与晞聊聊',       sub:'情感伙伴',     action:()=>switchTab('yiyi',     document.querySelector('[data-tab=yiyi]'))     },
  { icon:'🏢',  label:'向陶朱汇报',       sub:'创业CEO',      action:()=>switchTab('tianyuan', document.querySelector('[data-tab=tianyuan]')) },
  { icon:'🎓',  label:'守藏研究',         sub:'文献分析',     action:()=>switchTab('shoucang',  document.querySelector('[data-tab=shoucang]'))  },
  { icon:'🏠',  label:'总览',            sub:'工作台',       action:()=>switchTab('overview', document.querySelector('[data-tab=overview]')) },
  { icon:'📊',  label:'仪表盘',          sub:'Dashboard',    action:()=>switchTab('dashboard',document.querySelector('[data-tab=dashboard]'))},
  { icon:'🏗️', label:'陶朱团队',         sub:'子员工看板',   action:()=>{switchTab('tianyuan-team',document.querySelector('[data-tab=tianyuan-team]'));document.getElementById('subGroup-tianyuan')?.classList.remove('hidden');}},
  { icon:'✏️', label:'新对话',           sub:'打开新会话',   action:()=>newChat() },
  { icon:'↺',  label:'刷新总览',         sub:'',             action:()=>{switchTab('overview',document.querySelector('[data-tab=overview]'));loadOverview();} },
  { icon:'⚙️', label:'设置',            sub:'端口·快捷键',  action:()=>switchTab('settings', document.querySelector('[data-tab=settings]')) },
];

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
  if (e.key === 'Enter') { if (cmdFocusIdx>=0) execCmd(cmdFocusIdx); else if (cmdItems.length) execCmd(0); }
};

// ══════════════════════════════════════════════════
//  Toast
// ══════════════════════════════════════════════════
function toast(msg, type = '') {
  const c = document.getElementById('toastContainer');
  if (!c) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, 2800);
}
window.toast = toast;

// ══════════════════════════════════════════════════
//  记忆存储后端设置
// ══════════════════════════════════════════════════
let _memSelectedBackend = 'sqlite';  // 当前 UI 中选中的后端
let _memSearchTimer = null;

/** 加载并渲染后端状态 */
window.memLoadStatus = async function() {
  const statusEl = document.getElementById('memBackendStatus');
  try {
    const data = await fetch(`${CONFIG.api}/memory/backend`, CONFIG.fetchOpts()).then(r => r.json());
    _memSelectedBackend = data.type || 'sqlite';
    _memRenderBackendCards(_memSelectedBackend);

    // 填入已保存的 vault 路径
    if (data.type === 'obsidian' && data.vault_path) {
      const pathInput = document.getElementById('memObsidianPath');
      if (pathInput) pathInput.value = data.vault_path;
    }

    // 渲染状态摘要
    if (statusEl) {
      if (data.type === 'sqlite') {
        statusEl.innerHTML = `<span style="color:var(--success)">●</span> 本地存储 · ${data.entries} 条记忆 · 数据库 ${data.size_kb} KB`;
      } else {
        const vaultOk = data.ok ? `<span style="color:var(--success)">●</span>` : `<span style="color:var(--error)">●</span>`;
        statusEl.innerHTML = `${vaultOk} Obsidian Vault · ${data.md_files} 个 .md 文件 · ${data.entries} 条结构化记忆`;
      }
    }
    // 同时刷新记忆列表
    memLoadEntries();
  } catch(e) {
    if (statusEl) statusEl.textContent = '未连接后端，无法读取状态';
  }
};

/** 渲染后端选择卡片高亮 */
function _memRenderBackendCards(active) {
  ['sqlite', 'obsidian'].forEach(t => {
    const card  = document.getElementById(`memCard${t.charAt(0).toUpperCase() + t.slice(1)}`);
    const check = card?.querySelector('.mem-card-check');
    if (!card) return;
    card.classList.toggle('mem-card-active', t === active);
    if (check) check.style.opacity = t === active ? '1' : '0';
  });
  const pathRow    = document.getElementById('memObsidianPathRow');
  const migrateRow = document.getElementById('memMigrateRow');
  if (pathRow)    pathRow.style.display    = active === 'obsidian' ? '' : 'none';
  if (migrateRow) migrateRow.style.display = active !== _memSelectedBackend ? '' : 'none';
}

/** 用户点击卡片选择后端 */
window.memSelectBackend = function(type) {
  _memSelectedBackend = type;
  _memRenderBackendCards(type);
};

/** 验证 Obsidian Vault 路径 */
window.memVerifyVault = async function() {
  const path   = document.getElementById('memObsidianPath')?.value.trim();
  const result = document.getElementById('memVaultVerifyResult');
  if (!path || !result) return;
  result.textContent = '验证中…';
  try {
    const data = await fetch(`${CONFIG.api}/memory/backend`, CONFIG.fetchOpts()).then(r => r.json());
    // 临时尝试切换并立即查询状态（不持久化）
    // 简单方式：只检查路径格式，后端会在切换时验证
    if (path.length > 2) {
      result.innerHTML = `<span style="color:var(--success)">✓</span> 路径格式正确，切换时将验证目录是否存在`;
    } else {
      result.innerHTML = `<span style="color:var(--error)">✗</span> 路径无效`;
    }
  } catch(e) {
    result.textContent = '无法连接后端';
  }
};

/** 应用存储设置 */
window.memApplyBackend = async function() {
  const backend     = _memSelectedBackend;
  const vaultPath   = document.getElementById('memObsidianPath')?.value.trim() || '';
  const shouldMigrate = document.getElementById('memMigrateCheck')?.checked ?? true;

  if (backend === 'obsidian' && !vaultPath) {
    toast('请填写 Obsidian Vault 路径', 'error'); return;
  }
  try {
    const data = await fetch(`${CONFIG.api}/memory/backend`, CONFIG.fetchOpts({
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        backend:       backend,
        obsidian_path: vaultPath,
        migrate:       shouldMigrate,
      }),
    })).then(r => r.json());

    if (data.ok) {
      const migratedMsg = data.migrated > 0 ? `，已迁移 ${data.migrated} 条记忆` : '';
      toast(`✓ 已切换到${backend === 'sqlite' ? '本地存储' : 'Obsidian'}${migratedMsg}`, 'success');
      memLoadStatus();
    } else {
      toast(`切换失败：${data.error}`, 'error');
    }
  } catch(e) {
    toast(`切换失败：${e.message}`, 'error');
  }
};

/** 记忆列表 */
window.memLoadEntries = async function() {
  const agent   = document.getElementById('memAgentFilter')?.value || '';
  const listEl  = document.getElementById('memEntriesList');
  const countEl = document.getElementById('memEntryCount');
  if (!listEl) return;
  try {
    const params = agent ? `?agent=${encodeURIComponent(agent)}&limit=100` : '?limit=100';
    const entries = await fetch(`${CONFIG.api}/memory/entries${params}`, CONFIG.fetchOpts()).then(r => r.json());
    if (countEl) countEl.textContent = `${entries.length} 条`;
    if (!entries.length) {
      listEl.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:12px 0">暂无记忆。点击聊天框中的 🧠 按钮来添加第一条。</div>';
      return;
    }
    const CAT_LABEL = {user_profile:'用户画像',preference:'偏好',emotional:'情感',business:'创业',knowledge:'知识',writing_style:'写作风格',project:'项目',note:'笔记',general:'通用'};
    const importanceColor = [,'#94a3b8','#64748b','#3b82f6','#f59e0b','#ef4444'];
    listEl.innerHTML = entries.map(e => `
      <div class="mem-entry-row" data-id="${e.id}">
        <div class="mem-entry-main">
          <span class="mem-entry-cat">${CAT_LABEL[e.category] || e.category}</span>
          <span class="mem-entry-key">${escHtml(e.key)}</span>
          <span class="mem-entry-sep">→</span>
          <span class="mem-entry-val">${escHtml(e.value)}</span>
        </div>
        <div class="mem-entry-meta">
          <span style="color:${importanceColor[e.importance]||'#94a3b8'}">${'★'.repeat(e.importance)}${'☆'.repeat(5-e.importance)}</span>
          <span>${(e.updated_at||'').slice(0,10)}</span>
          <button class="mem-del-btn" onclick="memDeleteEntry('${e.id}',this)" title="删除">🗑</button>
        </div>
      </div>`).join('');
  } catch(e) {
    listEl.innerHTML = `<div style="color:var(--error);font-size:13px">${e.message}</div>`;
  }
};

/** 防抖搜索 */
window.memSearchDebounce = function(q) {
  clearTimeout(_memSearchTimer);
  _memSearchTimer = setTimeout(() => memSearchEntries(q), 300);
};

window.memSearchEntries = async function(q) {
  if (!q.trim()) { memLoadEntries(); return; }
  const listEl = document.getElementById('memEntriesList');
  if (!listEl) return;
  try {
    const entries = await fetch(
      `${CONFIG.api}/memory/search?q=${encodeURIComponent(q)}`,
      CONFIG.fetchOpts()
    ).then(r => r.json());
    const countEl = document.getElementById('memEntryCount');
    if (countEl) countEl.textContent = `找到 ${entries.length} 条`;
    if (!entries.length) {
      listEl.innerHTML = `<div style="color:var(--text-muted);font-size:13px">没有找到「${escHtml(q)}」相关的记忆</div>`;
      return;
    }
    listEl.innerHTML = entries.map(e => `
      <div class="mem-entry-row" data-id="${e.id}">
        <div class="mem-entry-main">
          <span class="mem-entry-cat">${e.category}</span>
          <span class="mem-entry-key">${escHtml(e.key)}</span>
          <span class="mem-entry-sep">→</span>
          <span class="mem-entry-val">${escHtml(e.value)}</span>
        </div>
        <div class="mem-entry-meta">
          <button class="mem-del-btn" onclick="memDeleteEntry('${e.id}',this)">🗑</button>
        </div>
      </div>`).join('');
  } catch(e) { /* ignore */ }
};

window.memDeleteEntry = async function(id, btn) {
  try {
    const data = await fetch(`${CONFIG.api}/memory/entries/${id}`,
      CONFIG.fetchOpts({ method: 'DELETE' })
    ).then(r => r.json());
    if (data.ok) {
      btn?.closest('.mem-entry-row')?.remove();
      toast('已删除', 'success');
    } else {
      toast(data.message || '删除失败', 'error');
    }
  } catch(e) { toast(e.message, 'error'); }
};

// 切换到设置 tab 时加载记忆后端状态
(function() {
  const _prevSwitch = window.switchTab;
  window.switchTab = function(tabId, el) {
    _prevSwitch(tabId, el);
    if (tabId === 'settings') {
      setTimeout(memLoadStatus, 100);
    }
  };
})();

// ══════════════════════════════════════════════════
//  端口设置
// ══════════════════════════════════════════════════
window.applyPorts = function() {
  CONFIG.wsPort   = parseInt(document.getElementById('wsPort')?.value) || 9100;
  CONFIG.dashPort = parseInt(document.getElementById('dashPort')?.value) || 9119;
  backendOnline = false;
  for (const id of Object.keys(AGENTS)) {
    wsConns[id]?.close();
    wsStatus[id] = { model:'-', tools:0, busy:false, connected:false };
    updateAgentUI(id);
  }
  checkBackend();
};

// ══════════════════════════════════════════════════
//  工具
// ══════════════════════════════════════════════════
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function formatTime(d) {
  return d.toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
}

// ══════════════════════════════════════════════════
//  全局快捷键
// ══════════════════════════════════════════════════
document.addEventListener('keydown', e => {
  if ((e.ctrlKey||e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const ov = document.getElementById('cmdOverlay');
    if (ov?.classList.contains('hidden')) openCmdPalette();
    else ov?.classList.add('hidden');
  }
});

// ══════════════════════════════════════════════════
//  知识库 UI
// ══════════════════════════════════════════════════
const KB_API = () => `${CONFIG.api}/kb`;

// 加载文档列表
window.kbLoadDocs = async function() {
  const el = document.getElementById('kbDocList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${KB_API()}/docs`);
    const { docs } = await r.json();
    if (!docs.length) {
      el.innerHTML = `
        <div class="empty-state-box">
          <div class="es-emoji">📚</div>
          <div class="es-title">知识库还是空的</div>
          <div class="es-desc">上传 PDF、Word、Markdown 或直接粘贴文本<br>Anima 会把它们变成可检索的知识</div>
          <div class="es-actions">
            <button class="btn-primary" onclick="document.getElementById('kbFile')?.click()">📎 上传文件</button>
            <button class="hdr-btn-sm" onclick="document.getElementById('kbText')?.focus()">✏️ 粘贴文本</button>
          </div>
          <div class="es-hint">支持格式：PDF · DOCX · MD · TXT · HTML</div>
        </div>`;
      return;
    }
    el.innerHTML = docs.map(d => `
      <div class="kb-doc-row">
        <span style="font-size:18px">📄</span>
        <div style="flex:1">
          <div class="kb-doc-name">${escHtml(d.source)}</div>
          <div class="kb-doc-meta">ID: ${d.doc_id} · ${d.chunks} 个块</div>
        </div>
        <button class="kb-doc-del" onclick="kbDelete('${d.doc_id}')" title="删除">🗑</button>
      </div>`).join('');
  } catch(e) {
    el.innerHTML = `<span style="color:var(--error)">加载失败: ${e.message}</span>`;
  }
};

// 删除文档
window.kbDelete = async function(docId) {
  if (!confirm(`确认删除文档 ${docId}？`)) return;
  try {
    const r = await fetch(`${KB_API()}/docs/${docId}`, { method:'DELETE' });
    const d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    toast('文档已删除', 'success');
    kbLoadDocs();
  } catch(e) { toast('删除失败', 'error'); }
};

// 上传文件
window.kbHandleFileSelect = async function(input) {
  const files = Array.from(input.files || []);
  input.value = '';
  for (const file of files) await _kbUploadFile(file);
};

window.kbHandleDrop = async function(e) {
  e.preventDefault();
  document.getElementById('kbDropZone')?.classList.remove('dragover');
  const files = Array.from(e.dataTransfer.files || []);
  for (const file of files) await _kbUploadFile(file);
};

async function _kbUploadFile(file) {
  const status = document.getElementById('kbUploadStatus');
  if (status) status.textContent = `正在入库：${file.name}…`;
  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', file.name);
    const r = await fetch(`${KB_API()}/upload`, { method:'POST', body: fd });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    if (status) status.innerHTML = `<span style="color:var(--success)">✓ ${escHtml(file.name)} — ${d.chunks} 个块已入库</span>`;
    toast(`📚 ${file.name} 入库完成`, 'success');
    kbLoadDocs();
  } catch(e) {
    if (status) status.innerHTML = `<span style="color:var(--error)">✗ ${escHtml(file.name)}: ${e.message}</span>`;
    toast(`入库失败: ${e.message}`, 'error');
  }
}

// 粘贴文本入库
window.kbIngestPaste = async function() {
  const text = document.getElementById('kbPasteArea')?.value.trim();
  const name = document.getElementById('kbPasteName')?.value.trim() || '粘贴内容';
  const status = document.getElementById('kbUploadStatus');
  if (!text) { toast('请先输入内容', 'error'); return; }
  if (status) status.textContent = '正在入库…';
  try {
    const r = await fetch(`${KB_API()}/upload`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text, name }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    if (status) status.innerHTML = `<span style="color:var(--success)">✓ "${escHtml(name)}" — ${d.chunks} 个块已入库</span>`;
    document.getElementById('kbPasteArea').value = '';
    toast(`📚 "${name}" 入库完成`, 'success');
    kbLoadDocs();
  } catch(e) {
    if (status) status.innerHTML = `<span style="color:var(--error)">✗ ${e.message}</span>`;
    toast(`入库失败: ${e.message}`, 'error');
  }
};

// 语义检索
window.kbSearch = async function() {
  const query = document.getElementById('kbSearchInput')?.value.trim();
  const res   = document.getElementById('kbSearchResults');
  if (!query || !res) return;
  res.innerHTML = '<span style="color:var(--muted)">检索中…</span>';
  try {
    const r = await fetch(`${KB_API()}/search`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ query, top_k: 5 }),
    });
    const { hits, error } = await r.json();
    if (error) throw new Error(error);
    if (!hits.length) { res.innerHTML = '<span style="color:var(--muted)">未找到相关内容</span>'; return; }
    res.innerHTML = hits.map(h => `
      <div class="kb-hit-card">
        <div class="kb-hit-score">📄 ${escHtml(h.source)} · 相关度 ${(h.score * 100).toFixed(1)}%</div>
        <div class="kb-hit-text">${escHtml(h.text.slice(0, 300))}${h.text.length > 300 ? '…' : ''}</div>
      </div>`).join('');
  } catch(e) {
    res.innerHTML = `<span style="color:var(--error)">检索失败: ${e.message}</span>`;
  }
};

// ══════════════════════════════════════════════════
//  工作流构建器
// ══════════════════════════════════════════════════
const WF_API = () => `${CONFIG.api}/workflow`;
let wfStepList = [];   // [{agent, prompt, pass_context}]
let wfCurrentId = null;

const WF_AGENTS = [
  { id:'xi',   label:'👩‍💼 Anima — 私人助理' },
  { id:'yiyi',     label:'🌸 晞 — 情感伙伴' },
  { id:'tianyuan', label:'🏢 陶朱 — CEO' },
  { id:'shoucang',  label:'🎓 守藏 — 知识研究员' },
  { id:'executor', label:'⚡ 执行者 — 任务执行' },
  { id:'writer',   label:'✍️ 写手 — 内容创作' },
  { id:'reader',   label:'📖 阅读者 — 文档阅读' },
  { id:'critic',   label:'🔍 评审 — 质量把关' },
];

function wfRender() {
  const el = document.getElementById('wfSteps');
  if (!el) return;
  if (!wfStepList.length) {
    el.innerHTML = '<div style="text-align:center;color:var(--muted);padding:20px 0;font-size:13px">点击"添加步骤"开始构建工作流</div>';
    return;
  }
  const opts = WF_AGENTS.map(a =>
    `<option value="${a.id}">${a.label}</option>`).join('');

  const connector = (i) => i > 0 ? `<div class="wf-connector"><div class="wf-connector-line"></div><span class="wf-connector-arrow">▼</span><div class="wf-connector-line"></div></div>` : '';
  const delBtn   = (i) => `<button onclick="wfRemoveStep(${i})" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:14px;margin-left:auto" title="删除">✕</button>`;
  const agentSel = (val, path) => `<select class="wf-step-agent-select" onchange="${path}=this.value">${WF_AGENTS.map(a=>`<option value="${a.id}"${val===a.id?' selected':''}>${a.label}</option>`).join('')}</select>`;

  el.innerHTML = wfStepList.map((step, i) => {
    const nodeType = step.type || 'sequential';
    let card = '';

    if (nodeType === 'parallel') {
      const branches = (step.branches || []).map((b, bi) => `
        <div class="wf-branch-item">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
            <span style="font-size:11px;color:var(--text-muted)">分支 ${bi+1}</span>
            ${agentSel(b.agent, `wfStepList[${i}].branches[${bi}].agent`)}
          </div>
          <textarea class="wf-step-prompt" rows="2" placeholder="分支 ${bi+1} 提示词…"
            oninput="wfStepList[${i}].branches[${bi}].prompt=this.value">${escHtml(b.prompt||'')}</textarea>
        </div>`).join('');
      card = `<div class="wf-step-card wf-node-parallel" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num" style="background:#f59e0b">${i+1}</div>
          <span style="font-size:12px;font-weight:700;color:#92400e">⚡ 并行节点</span>
          ${delBtn(i)}
        </div>
        <div class="wf-branches">${branches}</div>
      </div>`;
    } else if (nodeType === 'condition') {
      card = `<div class="wf-step-card wf-node-condition" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num" style="background:#8b5cf6">${i+1}</div>
          <span style="font-size:12px;font-weight:700;color:#5b21b6">🔀 条件节点</span>
          ${delBtn(i)}
        </div>
        <div class="wf-step-body">
          <div style="margin-bottom:8px">
            <label style="font-size:11px;color:var(--text-muted)">如果上步输出包含关键词：</label>
            <input style="width:100%;margin-top:4px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:var(--bg-main);color:var(--text-main)"
              value="${escHtml(step.keyword||'')}" oninput="wfStepList[${i}].keyword=this.value" placeholder="例：失败、错误、否">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div>
              <div style="font-size:11px;color:#16a34a;font-weight:600;margin-bottom:4px">✓ 是：</div>
              ${agentSel(step.true_step?.agent||'xi', `wfStepList[${i}].true_step.agent`)}
              <textarea class="wf-step-prompt" rows="2" style="margin-top:4px" placeholder="条件满足时的任务…"
                oninput="wfStepList[${i}].true_step.prompt=this.value">${escHtml(step.true_step?.prompt||'')}</textarea>
            </div>
            <div>
              <div style="font-size:11px;color:#dc2626;font-weight:600;margin-bottom:4px">✗ 否：</div>
              ${agentSel(step.false_step?.agent||'xi', `wfStepList[${i}].false_step.agent`)}
              <textarea class="wf-step-prompt" rows="2" style="margin-top:4px" placeholder="条件不满足时的任务…"
                oninput="wfStepList[${i}].false_step.prompt=this.value">${escHtml(step.false_step?.prompt||'')}</textarea>
            </div>
          </div>
        </div>
      </div>`;
    } else if (nodeType === 'loop') {
      card = `<div class="wf-step-card wf-node-loop" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num" style="background:#0ea5e9">${i+1}</div>
          <span style="font-size:12px;font-weight:700;color:#0369a1">🔁 循环节点</span>
          ${delBtn(i)}
        </div>
        <div class="wf-step-body">
          <div style="display:flex;gap:8px;margin-bottom:8px">
            <div style="flex:1">
              <label style="font-size:11px;color:var(--text-muted)">最多循环次数</label>
              <input type="number" min="1" max="10" value="${step.max_iter||3}"
                oninput="wfStepList[${i}].max_iter=+this.value"
                style="width:100%;margin-top:4px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:var(--bg-main);color:var(--text-main)">
            </div>
            <div style="flex:1">
              <label style="font-size:11px;color:var(--text-muted)">停止关键词</label>
              <input value="${escHtml(step.stop_keyword||'完成')}"
                oninput="wfStepList[${i}].stop_keyword=this.value"
                style="width:100%;margin-top:4px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:var(--bg-main);color:var(--text-main)">
            </div>
          </div>
          ${agentSel(step.step?.agent||'xi', `wfStepList[${i}].step.agent`)}
          <textarea class="wf-step-prompt" rows="2" style="margin-top:6px" placeholder="每次循环执行的任务…"
            oninput="wfStepList[${i}].step.prompt=this.value">${escHtml(step.step?.prompt||'')}</textarea>
        </div>
      </div>`;
    } else {
      // sequential
      card = `<div class="wf-step-card" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num">${i+1}</div>
          ${agentSel(step.agent||'xi', `wfStepList[${i}].agent`)}
          <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
            ${i > 0 ? `<label style="font-size:11px;display:flex;align-items:center;gap:3px;color:var(--text-muted)">
              <input type="checkbox" ${step.pass_context?'checked':''} onchange="wfStepList[${i}].pass_context=this.checked"> 接收上步
            </label>` : ''}
            <button onclick="wfRemoveStep(${i})" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px" title="删除">✕</button>
          </div>
        </div>
        <div class="wf-step-body">
          <textarea class="wf-step-prompt" placeholder="输入给该 Agent 的任务提示词…" rows="3"
            oninput="wfStepList[${i}].prompt=this.value">${escHtml(step.prompt||'')}</textarea>
        </div>
      </div>`;
    }
    return connector(i) + card;
  }).join('');
}

window.wfAddStep = function(type = 'sequential') {
  if (type === 'parallel') {
    wfStepList.push({
      type: 'parallel',
      branches: [
        { agent: 'writer',   prompt: '', pass_context: true },
        { agent: 'reader',   prompt: '', pass_context: true },
      ],
    });
  } else if (type === 'condition') {
    wfStepList.push({
      type: 'condition',
      keyword: '失败',
      true_step:  { agent: 'xi', prompt: '处理失败情况：' },
      false_step: { agent: 'xi', prompt: '继续正常流程：' },
    });
  } else if (type === 'loop') {
    wfStepList.push({
      type: 'loop',
      max_iter: 3,
      stop_keyword: '完成',
      step: { agent: 'xi', prompt: '', pass_context: true },
    });
  } else {
    wfStepList.push({ type: 'sequential', agent:'xi', prompt:'', pass_context: wfStepList.length > 0 });
  }
  wfRender();
};

window.wfRemoveStep = function(idx) {
  wfStepList.splice(idx, 1);
  wfRender();
};

window.wfNew = function() {
  wfStepList.length = 0;  // 清空数组但保持引用（wfRun 引用同一个数组）
  window._wfStepsData = wfStepList;
  wfCurrentId = null;
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = '我的工作流';
  document.getElementById('wfResults').innerHTML = '';
  document.getElementById('wfRunStatus').textContent = '等待运行…';
  wfRender();
};

// 拖拽排序
let _wfDragIdx = null;
window.wfDragStart = (e, idx) => { _wfDragIdx = idx; e.dataTransfer.effectAllowed = 'move'; };
window.wfDragOver  = (e, idx) => { e.preventDefault(); };
window.wfDrop      = (e, idx) => {
  e.preventDefault();
  if (_wfDragIdx === null || _wfDragIdx === idx) return;
  const [item] = wfStepList.splice(_wfDragIdx, 1);
  wfStepList.splice(idx, 0, item);
  _wfDragIdx = null;
  wfRender();
};

// 运行
window.wfRun = async function() {
  if (!wfStepList.length) { toast('请先添加步骤', 'error'); return; }
  // 验证：只检查 sequential 节点的 prompt（其他节点结构不同）
  const anyEmpty = wfStepList.some(s => {
    const t = s.type || 'sequential';
    if (t === 'sequential') return !s.prompt?.trim();
    if (t === 'loop') return !s.step?.prompt?.trim();
    return false;
  });
  if (anyEmpty) { toast('有步骤的提示词为空', 'error'); return; }

  const btn     = document.getElementById('wfRunBtn');
  const status  = document.getElementById('wfRunStatus');
  const results = document.getElementById('wfResults');
  if (btn) btn.disabled = true;
  if (status) status.textContent = '运行中…';
  if (results) results.innerHTML = '<div style="text-align:center;padding:20px;color:var(--muted)">⏳ 执行中，请稍候…</div>';

  try {
    const useKb = document.getElementById('wfUseKb')?.checked || false;
    const r = await fetch(`${WF_API()}/run`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ steps: wfStepList, use_kb: useKb }),
    });
    const { results: res, error } = await r.json();
    if (error) throw new Error(error);
    if (status) status.textContent = `完成 · ${res.length} 步`;
    results.innerHTML = res.map((r, i) => {
      const isErr = (r.output || '').startsWith('执行错误');
      let typeLabel = '';
      if (r.type === 'parallel')  typeLabel = '<span style="font-size:10px;background:#fef3c7;color:#92400e;padding:2px 6px;border-radius:100px;margin-left:4px">并行</span>';
      if (r.type === 'condition') typeLabel = `<span style="font-size:10px;background:#ede9fe;color:#5b21b6;padding:2px 6px;border-radius:100px;margin-left:4px">条件${r.matched?'✓':'✗'}</span>`;
      if (r.type === 'loop')      typeLabel = `<span style="font-size:10px;background:#e0f2fe;color:#0369a1;padding:2px 6px;border-radius:100px;margin-left:4px">循环×${r.iterations||'?'}</span>`;
      return `<div class="wf-result-step">
        <div class="wf-result-hdr" onclick="this.nextElementSibling.classList.toggle('open')">
          <div class="wf-step-num" style="background:${isErr?'var(--error)':'var(--accent)'}">${r.step}</div>
          <span>${escHtml(AGENTS[r.agent]?.name || r.agent || r.type)}</span>
          ${typeLabel}
          <span style="margin-left:auto;color:var(--muted);font-size:11px">⏱ ${r.elapsed}s</span>
          <span style="color:var(--muted);font-size:12px">▼</span>
        </div>
        <div class="wf-result-body${i === res.length-1 ? ' open' : ''}">${escHtml(r.output)}</div>
      </div>`;
    }).join('');
    toast('工作流执行完成 ✓', 'success');
  } catch(e) {
    if (status) status.textContent = '执行失败';
    if (results) results.innerHTML = `<span style="color:var(--error)">${e.message}</span>`;
    toast(`运行失败: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
};

// 保存
window.wfSave = async function() {
  const name = document.getElementById('wfName')?.value.trim() || '未命名';
  if (!wfStepList.length) { toast('工作流为空', 'error'); return; }
  try {
    const r = await fetch(`${WF_API()}/save`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ id: wfCurrentId, name, steps: wfStepList }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    wfCurrentId = d.id;
    toast(`"${name}" 已保存`, 'success');
    wfLoadList();
  } catch(e) { toast(`保存失败: ${e.message}`, 'error'); }
};

// 加载已保存列表
window.wfLoadList = async function() {
  const el = document.getElementById('wfSavedList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${WF_API()}/list`);
    const { workflows } = await r.json();
    const wfs = (workflows || []).filter(w => w.type === 'workflow');
    if (!wfs.length) { el.innerHTML = '<span style="color:var(--muted)">暂无保存的工作流</span>'; return; }
    el.innerHTML = wfs.map(w => `
      <div class="wf-saved-row">
        <div class="wf-saved-name">${escHtml(w.name)}</div>
        <div class="wf-saved-meta">${(w.steps||[]).length} 步</div>
        <button class="hdr-btn-sm" onclick="wfLoad(${JSON.stringify(w).replace(/"/g,'&quot;')})">载入</button>
        <button class="kb-doc-del" onclick="wfDelete('${w.id}')">🗑</button>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

window.wfLoad = function(wf) {
  wfCurrentId = wf.id;
  wfStepList  = (wf.steps || []).map(s => ({ ...s }));
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = wf.name || '工作流';
  wfRender();
  toast(`已载入"${wf.name}"`, 'success');
};

window.wfDelete = async function(id) {
  if (!confirm('确认删除此工作流？')) return;
  try {
    await fetch(`${WF_API()}/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    wfLoadList();
  } catch(e) { toast('删除失败', 'error'); }
};

// ══════════════════════════════════════════════════
//  工作流模板库（20 个内置模板）
// ══════════════════════════════════════════════════
// 免费模板 ID（每类各 1 个基础款，其余 Pro 专属）
const WF_FREE_TEMPLATES = new Set([
  'tpl_daily_news',     // 内容
  'tpl_market_research',// 调研
  'tpl_code_review',    // 代码
  'tpl_meeting_summary',// 商业
]);

const WF_TEMPLATES = [
  // ── 内容创作 ──────────────────────────────────────
  {
    id: 'tpl_daily_news',
    name: '📰 AI 新闻日报',
    desc: '搜索 AI 前沿动态，写手提炼摘要，评审把关质量',
    category: 'content', icon: '📰',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'搜索今天最重要的 5 条 AI / 科技新闻，给出标题和 2 句话摘要', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'将以下新闻整理成一份简洁的日报，适合微信群分享，风格轻松有趣', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'检查日报的准确性和可读性，给出最终版本', pass_context:true },
    ],
  },
  {
    id: 'tpl_blog_post',
    name: '✍️ 长文章创作',
    desc: '调研主题 → 写手撰稿 → 评审润色 → 输出成品',
    category: 'content', icon: '✍️',
    steps: [
      { type:'sequential', agent:'reader',  prompt:'研究以下主题，整理关键要点和写作角度：{{主题}}', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'根据上面的调研，写一篇 1500 字的深度文章，包含引言、3 个主体段落、结语', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'对文章进行润色：提升文采、修正逻辑、增加例子，输出最终版', pass_context:true },
    ],
  },
  {
    id: 'tpl_social_content',
    name: '📱 社媒内容矩阵',
    desc: '一键生成微博、小红书、朋友圈三种风格的内容',
    category: 'content', icon: '📱',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'将以下核心内容整理成 3 个关键信息点：{{内容要点}}', pass_context:false },
      { type:'parallel', branches: [
        { agent:'writer', prompt:'根据关键信息点写一条微博（140字内，时事评论风格）', pass_context:true },
        { agent:'writer', prompt:'根据关键信息点写一篇小红书笔记（300字，加 emoji，分点）', pass_context:true },
        { agent:'writer', prompt:'根据关键信息点写一条朋友圈（100字内，生活化表达）', pass_context:true },
      ]},
    ],
  },
  {
    id: 'tpl_product_review',
    name: '🔍 产品评测报告',
    desc: '阅读者收集资料，写手撰写评测，评审打分',
    category: 'content', icon: '🔍',
    steps: [
      { type:'sequential', agent:'reader',  prompt:'搜集关于 {{产品名称}} 的用户评价、专业测评、规格参数', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'撰写一篇产品评测报告：外观、性能、使用体验、性价比各维度分析', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'补充不足、给出综合评分（满分10分）和购买建议', pass_context:true },
    ],
  },

  // ── 调研分析 ──────────────────────────────────────
  {
    id: 'tpl_market_research',
    name: '📊 市场调研分析',
    desc: '陶朱主导：竞品分析 + 市场规模 + 机会洞察',
    category: 'research', icon: '📊',
    steps: [
      { type:'sequential', agent:'xi',   prompt:'收集 {{行业/产品}} 的市场数据：市场规模、主要玩家、增长趋势', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'对竞品进行 SWOT 分析，找出市场空白和差异化机会', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'整理成一份 CEO 级别的市场洞察报告，有图表建议', pass_context:true },
    ],
  },
  {
    id: 'tpl_user_research',
    name: '👥 用户访谈分析',
    desc: '整理用户反馈，提炼需求，生成产品洞察',
    category: 'research', icon: '👥',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'阅读以下用户访谈记录，提炼关键痛点和需求：{{访谈内容}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'基于用户洞察，分析这些需求的商业价值，按优先级排序', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成用户研究报告，包括用户画像、核心诉求、产品建议', pass_context:true },
    ],
  },
  {
    id: 'tpl_tech_research',
    name: '🔬 技术选型调研',
    desc: '对比技术方案，给出选型建议',
    category: 'research', icon: '🔬',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'调研 {{技术领域}} 的主流方案，收集各方案的优缺点、社区活跃度、生产案例', pass_context:false },
      { type:'sequential', agent:'reader',  prompt:'深入对比每个方案的技术细节：性能、学习曲线、生态', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'结合具体场景给出最终选型建议，说明理由', pass_context:true },
    ],
  },
  {
    id: 'tpl_weekly_summary',
    name: '📋 周工作总结',
    desc: '整理本周工作亮点，生成周报和下周计划',
    category: 'research', icon: '📋',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'整理以下工作记录，提炼本周完成事项、遇到的挑战：{{工作内容}}', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'撰写专业的周报：本周完成、关键进展、遇到的问题', pass_context:true },
      { type:'sequential', agent:'tianyuan',prompt:'基于本周情况，制定下周优先级和计划', pass_context:true },
    ],
  },

  // ── 代码开发 ──────────────────────────────────────
  {
    id: 'tpl_code_review',
    name: '💻 代码审查',
    desc: '读取代码，发现问题，生成改进建议',
    category: 'code', icon: '💻',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'阅读以下代码，理解其功能和架构：\n```\n{{代码}}\n```', pass_context:false },
      { type:'sequential', agent:'critic',   prompt:'对代码进行 Code Review：安全漏洞、性能问题、可读性、最佳实践', pass_context:true },
      { type:'sequential', agent:'executor', prompt:'对每个问题给出具体的修复代码示例', pass_context:true },
    ],
  },
  {
    id: 'tpl_bug_fix',
    name: '🐛 Bug 排查修复',
    desc: '分析错误日志，定位问题，生成修复方案',
    category: 'code', icon: '🐛',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'分析以下错误信息和日志，理解报错原因：\n{{错误信息}}', pass_context:false },
      { type:'sequential', agent:'executor', prompt:'根据错误原因，给出 3 种可能的修复方案和代码示例', pass_context:true },
      { type:'sequential', agent:'critic',   prompt:'评估每种方案的可行性，推荐最佳方案并说明理由', pass_context:true },
    ],
  },
  {
    id: 'tpl_api_design',
    name: '🔌 API 接口设计',
    desc: '需求分析 → API 设计 → 接口文档生成',
    category: 'code', icon: '🔌',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'分析以下业务需求，梳理需要的核心功能：{{业务需求}}', pass_context:false },
      { type:'sequential', agent:'executor', prompt:'设计 RESTful API 接口：路径、方法、请求/响应格式、状态码', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成 OpenAPI 格式的接口文档，包含示例', pass_context:true },
    ],
  },
  {
    id: 'tpl_test_generation',
    name: '🧪 测试用例生成',
    desc: '分析代码，自动生成单元测试和边界测试',
    category: 'code', icon: '🧪',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'理解以下函数/模块的功能和边界条件：\n{{代码}}\n', pass_context:false },
      { type:'sequential', agent:'executor', prompt:'生成全面的单元测试：正常流程、边界值、异常情况', pass_context:true },
      { type:'sequential', agent:'critic',   prompt:'检查测试覆盖率是否充分，补充遗漏的测试场景', pass_context:true },
    ],
  },

  // ── 商业决策 ──────────────────────────────────────
  {
    id: 'tpl_business_plan',
    name: '💼 商业计划书',
    desc: '陶朱主导：市场 + 产品 + 财务 + 执行计划',
    category: 'business', icon: '💼',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'基于以下创业想法，分析市场机会和商业模式：{{创业想法}}', pass_context:false },
      { type:'parallel', branches: [
        { agent:'tianyuan', prompt:'撰写市场分析和竞争策略章节', pass_context:true },
        { agent:'writer',   prompt:'撰写产品介绍和用户价值主张章节', pass_context:true },
      ]},
      { type:'sequential', agent:'tianyuan', prompt:'整合以上内容，加上执行路线图和融资需求，完成完整商业计划书', pass_context:true },
    ],
  },
  {
    id: 'tpl_investment_memo',
    name: '📈 投资分析备忘录',
    desc: '对项目/公司做深度投资价值分析',
    category: 'business', icon: '📈',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'收集关于 {{项目/公司}} 的公开信息：团队、产品、融资历史、市场', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'进行投资价值分析：市场规模、竞争壁垒、团队能力、风险点', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成投资备忘录（Investment Memo），专业风格，含推荐结论', pass_context:true },
    ],
  },
  {
    id: 'tpl_customer_email',
    name: '📧 客户沟通邮件',
    desc: '分析情况，生成专业的客户邮件',
    category: 'business', icon: '📧',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'理解以下客户沟通背景：{{背景情况}}', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'撰写专业的客户邮件：语气得体、逻辑清晰、有行动项', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'检查邮件的语气、礼貌程度、是否可能引起误解，输出最终版', pass_context:true },
    ],
  },
  {
    id: 'tpl_okr_planning',
    name: '🎯 OKR 目标规划',
    desc: '基于战略方向，制定季度 OKR',
    category: 'business', icon: '🎯',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'分析以下战略方向，确定本季度最重要的 3 个优先级：{{战略方向}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'为每个优先级制定 OKR：1 个 Objective + 3 个可量化的 Key Results', pass_context:true },
      { type:'sequential', agent:'critic',   prompt:'检查 OKR 是否符合 SMART 原则，给出改进建议', pass_context:true },
    ],
  },
  {
    id: 'tpl_meeting_summary',
    name: '📝 会议纪要整理',
    desc: '从会议记录中提炼决策、行动项、负责人',
    category: 'business', icon: '📝',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'阅读以下会议记录，理解讨论的议题：{{会议记录}}', pass_context:false },
      { type:'sequential', agent:'writer',   prompt:'整理会议纪要：关键决策、行动项（含负责人和截止日期）、待跟进事项', pass_context:true },
    ],
  },
  {
    id: 'tpl_negotiation_prep',
    name: '🤝 谈判准备',
    desc: '分析谈判对手，制定策略，准备论点',
    category: 'business', icon: '🤝',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'研究谈判对方的背景、诉求、历史行为：{{对方信息}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'制定谈判策略：目标区间、让步底线、关键论点、可能的反对意见及应对', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成谈判准备清单和开场白脚本', pass_context:true },
    ],
  },
  {
    id: 'tpl_crisis_response',
    name: '🚨 危机应对方案',
    desc: '快速生成危机处理预案和对外声明',
    category: 'business', icon: '🚨',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'分析以下危机情况的严重程度和影响范围：{{危机描述}}', pass_context:false },
      { type:'condition', keyword:'严重',
        true_step:  { agent:'tianyuan', prompt:'制定紧急应对方案：立即行动项、对外沟通策略、后续修复计划' },
        false_step: { agent:'xi',   prompt:'制定常规处理预案：内部通报、改进措施、预防复发' },
      },
      { type:'sequential', agent:'writer',   prompt:'生成对外公告或内部通报初稿', pass_context:true },
    ],
  },
  {
    id: 'tpl_personal_growth',
    name: '🌱 个人成长计划',
    desc: '晞 + 陶朱联手制定个人发展路径',
    category: 'business', icon: '🌱',
    steps: [
      { type:'sequential', agent:'yiyi',     prompt:'了解用户当前状态、困惑和对未来的期望：{{个人现状}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'基于用户的现状和目标，制定 90 天个人成长计划：技能、习惯、里程碑', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'输出一份激励人心的个人成长方案，包括每周行动指引', pass_context:true },
    ],
  },
];

let _wfTplCat = 'all';
let _membershipPro = false; // 缓存会员状态供模板库用

async function _refreshMembershipCache() {
  try {
    const r = await fetch(`${CONFIG.api}/membership/status`);
    const m = await r.json();
    _membershipPro = m.active && m.tier === 'pro';
  } catch(_) { _membershipPro = false; }
}

// 渲染模板库
function wfRenderTemplates() {
  const grid = document.getElementById('wfTemplateGrid');
  if (!grid) return;
  const filtered = _wfTplCat === 'all'
    ? WF_TEMPLATES
    : WF_TEMPLATES.filter(t => t.category === _wfTplCat);

  grid.innerHTML = filtered.map(t => {
    const isPremium = !WF_FREE_TEMPLATES.has(t.id);
    const isLocked = isPremium && !_membershipPro;
    return `
    <div class="wf-tpl-card${isLocked?' locked':''}" onclick="wfLoadTemplate('${t.id}')" data-premium="${isPremium}">
      <span class="wf-tpl-icon">${t.icon}</span>
      <div class="wf-tpl-info">
        <div class="wf-tpl-name">${escHtml(t.name)}${isPremium?'<span class="skill-premium-badge">Pro</span>':''}</div>
        <div class="wf-tpl-desc">${escHtml(t.desc)}</div>
      </div>
      <span class="wf-tpl-steps">${t.steps.length}步</span>
    </div>`;
  }).join('');
}

window.wfTplFilter = function(cat, btn) {
  _wfTplCat = cat;
  document.querySelectorAll('.wf-tpl-filter').forEach(b => b.classList.remove('active'));
  btn?.classList.add('active');
  wfRenderTemplates();
};

window.wfLoadTemplate = function(id) {
  const tpl = WF_TEMPLATES.find(t => t.id === id);
  if (!tpl) return;
  // Pro 门控
  if (!WF_FREE_TEMPLATES.has(id) && !_membershipPro) {
    toast('🔒 此模板为 Pro 专属，请在设置页激活会员', 'info');
    return;
  }
  wfStepList.length = 0;
  tpl.steps.forEach(s => wfStepList.push(JSON.parse(JSON.stringify(s)))); // 深拷贝
  window._wfStepsData = wfStepList;
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = tpl.name;
  document.getElementById('wfResults').innerHTML = '';
  document.getElementById('wfRunStatus').textContent = '模板已加载，填写 {{占位符}} 后运行';
  wfRender();
  if (typeof renderWfCanvas === 'function') renderWfCanvas(wfStepList);
  toast(`✅ 模板已加载：${tpl.name}`, 'success');
};

// 切换到工作流 tab 时初始化模板库
const _origSwitchTabWf = window.switchTab;

// ── 在 switchTab 中注入模板初始化 ──
const _wfTabInit_orig = window.switchTab;
(function() {
  const _prev = window.switchTab;
  if (_prev) {
    window.switchTab = function(tabId, el) {
      _prev(tabId, el);
      if (tabId === 'workflow') {
        setTimeout(wfRenderTemplates, 50);
      }
    };
  }
})();

// 首次加载时也渲染
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(wfRenderTemplates, 500);
});

// ══════════════════════════════════════════════════
//  定时任务 UI
// ══════════════════════════════════════════════════
const SCHED_API = () => `${CONFIG.api}/scheduler`;

window.schedTriggerTypeChange = function() {
  const t    = document.getElementById('schedTriggerType')?.value;
  const hint = document.getElementById('schedTriggerHint');
  const val  = document.getElementById('schedTriggerValue');
  if (!hint || !val) return;
  if (t === 'interval') {
    hint.textContent = '间隔：30m=每30分钟、2h=每2小时、1d=每天';
    val.placeholder = '1h / 30m / 1d';
    val.value = '1h';
  } else {
    hint.textContent = '固定时间：09:00=每天9点，或标准 cron "0 9 * * 1-5"';
    val.placeholder = '09:00';
    val.value = '09:00';
  }
};

window.schedAdd = async function() {
  const name    = document.getElementById('schedName')?.value.trim();
  const agent   = document.getElementById('schedAgent')?.value;
  const prompt  = document.getElementById('schedPrompt')?.value.trim();
  const tType   = document.getElementById('schedTriggerType')?.value;
  const tVal    = document.getElementById('schedTriggerValue')?.value.trim();
  if (!name || !prompt || !tVal) { toast('请填写所有必填字段', 'error'); return; }
  try {
    const r = await fetch(`${SCHED_API()}/tasks`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, agent, prompt, trigger_type: tType, trigger_value: tVal }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`✓ "${name}" 已创建`, 'success');
    document.getElementById('schedName').value   = '';
    document.getElementById('schedPrompt').value = '';
    schedLoadTasks();
  } catch(e) { toast(`创建失败: ${e.message}`, 'error'); }
};

window.schedLoadTasks = async function() {
  const el = document.getElementById('schedTaskList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${SCHED_API()}/tasks`);
    const { tasks } = await r.json();
    if (!tasks.length) { el.innerHTML = '<span style="color:var(--muted)">暂无任务</span>'; return; }
    el.innerHTML = tasks.map(t => {
      const triggerLabel = t.trigger_type === 'interval'
        ? `每 ${t.trigger_value}`
        : `每天 ${t.trigger_value}`;
      return `
        <div class="sched-task-row">
          <div class="sched-task-led ${t.enabled ? 'on' : 'off'}"></div>
          <div style="flex:1">
            <div style="font-weight:600;font-size:13px">${escHtml(t.name)}</div>
            <div style="font-size:11px;color:var(--muted)">${AGENTS[t.agent]?.icon||''} ${t.agent} · ${triggerLabel} · 执行 ${t.run_count} 次</div>
          </div>
          <div style="display:flex;gap:4px">
            <button class="hdr-btn-sm" onclick="schedRunNow('${t.id}')" title="立即执行">▶</button>
            <button class="hdr-btn-sm" onclick="schedToggle('${t.id}')">${t.enabled ? '暂停' : '启用'}</button>
            <button class="kb-doc-del" onclick="schedDelete('${t.id}')">🗑</button>
          </div>
        </div>`;
    }).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

window.schedToggle = async function(id) {
  try {
    await fetch(`${SCHED_API()}/tasks/${id}/toggle`, { method:'POST' });
    schedLoadTasks();
  } catch(e) { toast('操作失败', 'error'); }
};

window.schedDelete = async function(id) {
  if (!confirm('确认删除此任务？')) return;
  try {
    await fetch(`${SCHED_API()}/tasks/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    schedLoadTasks();
  } catch(e) { toast('删除失败', 'error'); }
};

window.schedRunNow = async function(id) {
  try {
    await fetch(`${SCHED_API()}/tasks/${id}/run`, { method:'POST' });
    toast('已触发执行，稍后查看日志', 'success');
    setTimeout(schedLoadLogs, 3000);
  } catch(e) { toast('触发失败', 'error'); }
};

window.schedLoadLogs = async function() {
  const el = document.getElementById('schedLogList');
  if (!el) return;
  try {
    const r = await fetch(`${SCHED_API()}/logs?limit=30`);
    const { logs } = await r.json();
    if (!logs.length) { el.innerHTML = '<span style="color:var(--muted)">暂无日志</span>'; return; }
    el.innerHTML = logs.map(l => `
      <div style="border-bottom:1px solid var(--border);padding:7px 4px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
          <span style="font-size:12px">${l.ok ? '✅' : '❌'}</span>
          <span style="font-weight:600;font-size:12px">${escHtml(l.task_name)}</span>
          <span style="font-size:11px;color:var(--muted);margin-left:auto">${l.started.slice(0,16).replace('T',' ')}</span>
        </div>
        <div style="font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
          ${escHtml((l.output||'').slice(0,120))}
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

// ══════════════════════════════════════════════════
//  文件监视器 UI
// ══════════════════════════════════════════════════
const FW_API = () => `${CONFIG.api}/watcher`;

window.fwAdd = async function() {
  const name   = document.getElementById('fwName')?.value.trim();
  const path   = document.getElementById('fwPath')?.value.trim();
  const pattern= document.getElementById('fwPattern')?.value.trim() || '*';
  const agent  = document.getElementById('fwAgent')?.value;
  const prompt = document.getElementById('fwPrompt')?.value.trim();
  const evts   = [];
  if (document.getElementById('fwEvtCreate')?.checked) evts.push('created');
  if (document.getElementById('fwEvtModify')?.checked) evts.push('modified');
  if (document.getElementById('fwEvtDelete')?.checked) evts.push('deleted');
  if (!name || !path || !prompt) { toast('请填写规则名称、路径和提示词', 'error'); return; }
  if (!evts.length) { toast('请选择至少一种触发事件', 'error'); return; }
  try {
    const r = await fetch(`${FW_API()}/rules`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, watch_path:path, pattern, events:evts, agent, prompt_template:prompt }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`✓ "${name}" 已创建`, 'success');
    fwLoadRules();
  } catch(e) { toast(`创建失败: ${e.message}`, 'error'); }
};

window.fwLoadRules = async function() {
  const el = document.getElementById('fwRuleList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${FW_API()}/rules`);
    const { rules } = await r.json();
    if (!rules.length) { el.innerHTML = '<span style="color:var(--muted)">暂无规则</span>'; return; }
    el.innerHTML = rules.map(rule => `
      <div class="sched-task-row">
        <div class="sched-task-led ${rule.enabled ? 'on' : 'off'}"></div>
        <div style="flex:1">
          <div style="font-weight:600;font-size:13px">${escHtml(rule.name)}</div>
          <div style="font-size:11px;color:var(--muted)">${escHtml(rule.watch_path)} · ${rule.pattern} · ${(rule.events||[]).join('/')} · ${rule.trigger_count||0}次触发</div>
        </div>
        <div style="display:flex;gap:4px">
          <button class="hdr-btn-sm" onclick="fwToggle('${rule.id}')">${rule.enabled?'暂停':'启用'}</button>
          <button class="kb-doc-del" onclick="fwDelete('${rule.id}')">🗑</button>
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

window.fwToggle = async function(id) {
  try {
    await fetch(`${FW_API()}/rules/${id}/toggle`, { method:'POST' });
    fwLoadRules();
  } catch(e) { toast('操作失败', 'error'); }
};

window.fwDelete = async function(id) {
  if (!confirm('确认删除此监视规则？')) return;
  try {
    await fetch(`${FW_API()}/rules/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    fwLoadRules();
  } catch(e) { toast('删除失败', 'error'); }
};

window.fwLoadEvents = async function() {
  const el = document.getElementById('fwEventList');
  if (!el) return;
  try {
    const r = await fetch(`${FW_API()}/events?limit=30`);
    const { events } = await r.json();
    if (!events.length) { el.innerHTML = '<span style="color:var(--muted)">暂无触发事件</span>'; return; }
    el.innerHTML = events.map(e => `
      <div style="border-bottom:1px solid var(--border);padding:7px 4px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
          <span>${e.ok ? '✅' : '❌'}</span>
          <span style="font-weight:600;font-size:12px">${escHtml(e.rule_name)}</span>
          <span class="model-tag" style="font-size:10px">${e.event}</span>
          <span style="font-size:11px;color:var(--muted);margin-left:auto">${e.started.slice(0,16).replace('T',' ')}</span>
        </div>
        <div style="font-size:11px;color:var(--muted)">${escHtml(e.path)}</div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

// ══════════════════════════════════════════════════
//  多 Agent 群聊 UI
// ══════════════════════════════════════════════════
const GC_AGENT_META = {
  xi:       { icon:'👩‍💼', avatarImg:'assets/xi-avatar.png', cls:'xi-bg'   },
  yiyi:     { icon:'🌸',  cls:'yiyi-bg'     },
  tianyuan: { icon:'🏢',  cls:'tianyuan-bg' },
  shoucang:  { icon:'📜',  cls:'shoucang-bg' },
  executor: { icon:'⚡',  cls:'executor-bg' },
  writer:   { icon:'✍️',  cls:'writer-bg'   },
  reader:   { icon:'📖',  cls:'reader-bg'   },
  critic:   { icon:'🔍',  cls:'critic-bg'   },
};

// ══════════════════════════════════════════════════
//  Agent 配置（名称 / 音色） — 全局存储
// ══════════════════════════════════════════════════
let agentNames  = {};   // {xi:'Anima', yiyi:'晞', ...}
let agentVoices = {};   // {xi:'zh-CN-YunxiNeural', ...}

const DEFAULT_AGENT_META = {
  xi:       { icon:'👩‍💼', avatarImg:'assets/xi-avatar.png', cls:'xi-bg'   },
  yiyi:     { icon:'🌸',  cls:'yiyi-bg'     },
  tianyuan: { icon:'🏢',  cls:'tianyuan-bg' },
  shoucang:  { icon:'📜',  cls:'shoucang-bg' },
  executor: { icon:'⚡',  cls:'executor-bg' },
  writer:   { icon:'✍️',  cls:'writer-bg'   },
  reader:   { icon:'📖',  cls:'reader-bg'   },
  critic:   { icon:'🔍',  cls:'critic-bg'   },
};

const DEFAULT_AGENT_NAMES = {
  xi:'Anima', yiyi:'晞', tianyuan:'陶朱', shoucang:'守藏',
  executor:'执行者', writer:'写手', reader:'阅读者', critic:'评审',
};

async function loadAgentConfig() {
  try {
    const r = await fetch(`${CONFIG.api}/config/agents`);
    if (!r.ok) return;
    const { voices } = await r.json();  // 只取 voices，不取 names
    agentVoices = { ...voices };
  } catch(_) {}
  agentNames = { ...DEFAULT_AGENT_NAMES };  // 始终用 DEFAULT（固定名称）
}

function agentName(id) { return agentNames[id] || DEFAULT_AGENT_NAMES[id] || id; }

function applyAgentNames() {
  // 更新侧边栏导航显示名称
  const navMap = {
    xi:       '[data-tab=xi]',
    yiyi:     '[data-tab=yiyi]',
    tianyuan: '[data-tab=tianyuan]',
    shoucang: '[data-tab=shoucang]',
  };
  for (const [id, sel] of Object.entries(navMap)) {
    const el = document.querySelector(sel);
    if (el) {
      const icon = el.querySelector('.nav-icon')?.outerHTML || '';
      const dot  = el.querySelector('.agent-dot')?.outerHTML || '';
      el.innerHTML = `${icon}${agentName(id)}${dot}`;
    }
  }
  // 更新群聊成员面板
  gcRenderMembers();
}

// ══════════════════════════════════════════════════
//  TTS 语音播放
// ══════════════════════════════════════════════════
let _ttsQueue = [];
let _ttsPlaying = false;

async function ttsSpeak(text, agentId = 'xi') {
  if (!text || text.length < 3) return;
  _ttsQueue.push({ text, agentId });
  if (!_ttsPlaying) _ttsNext();
}

async function _ttsNext() {
  if (!_ttsQueue.length) { _ttsPlaying = false; return; }
  _ttsPlaying = true;
  const { text, agentId } = _ttsQueue.shift();
  const player = document.getElementById('ttsPlayer');
  try {
    const r = await fetch(`${CONFIG.api}/tts`, {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ text: text.slice(0, 400), agent: agentId }),
    });
    if (!r.ok) { _ttsPlaying = false; _ttsNext(); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    player.src = url;
    player.onended = () => { URL.revokeObjectURL(url); _ttsNext(); };
    player.onerror = () => { _ttsPlaying = false; _ttsNext(); };
    await player.play();
  } catch(_) { _ttsPlaying = false; _ttsNext(); }
}

window.ttsStop = function() {
  _ttsQueue = [];
  _ttsPlaying = false;
  const p = document.getElementById('ttsPlayer');
  if (p) { p.pause(); p.src = ''; }
};

// ══════════════════════════════════════════════════
//  群聊 — 飞书/微信风格
// ══════════════════════════════════════════════════
// 群聊状态
const GC_STATE = {
  selectedAgents: new Set(['xi', 'shoucang']),
  messages: [],
  isRunning: false,
  recognition: null,
};

function gcRenderMembers() {
  const el = document.getElementById('gcMembers');
  if (!el) return;
  const allAgents = ['xi','yiyi','tianyuan','shoucang','executor','writer','reader','critic'];
  el.innerHTML = allAgents.map(id => {
    const meta    = DEFAULT_AGENT_META[id];
    const name    = agentName(id);
    const checked = GC_STATE.selectedAgents.has(id);
    return `
      <div class="gc-member ${checked?'':'inactive'}" onclick="gcToggleMember('${id}',this)">
        <div class="gc-member-avatar ${meta.cls}">${meta.icon}</div>
        <div class="gc-member-name">${name}</div>
        <div class="gc-member-check">✓</div>
      </div>`;
  }).join('');

  // Update group meta
  const metaEl = document.getElementById('gcGroupMeta');
  if (metaEl) metaEl.textContent = `${GC_STATE.selectedAgents.size} 位成员`;
}

window.gcToggleMember = function(id, el) {
  if (GC_STATE.selectedAgents.has(id)) {
    if (GC_STATE.selectedAgents.size <= 2) { toast('至少保留 2 个成员', 'error'); return; }
    GC_STATE.selectedAgents.delete(id);
    el.classList.add('inactive');
  } else {
    GC_STATE.selectedAgents.add(id);
    el.classList.remove('inactive');
  }
  const metaEl = document.getElementById('gcGroupMeta');
  if (metaEl) metaEl.textContent = `${GC_STATE.selectedAgents.size} 位成员`;
};

function gcAddMessage(msgData) {
  const container = document.getElementById('gcMessages');
  if (!container) return;

  // Remove welcome screen
  const welcome = container.querySelector('.gc-welcome');
  if (welcome) welcome.remove();

  const { agent, name, content, round, elapsed, isTyping } = msgData;
  const meta = DEFAULT_AGENT_META[agent] || { icon:'🤖', cls:'' };
  const displayName = name || agentName(agent);

  if (isTyping) {
    // Remove existing typing for this agent
    container.querySelector(`.gc-typing[data-agent="${agent}"]`)?.remove();
    const div = document.createElement('div');
    div.className = 'gc-typing';
    div.dataset.agent = agent;
    div.innerHTML = `
      <div class="gc-typing-avatar ${meta.cls}">${meta.icon}</div>
      <div>
        <div style="font-size:11px;color:var(--muted);margin-bottom:4px">${displayName}</div>
        <div class="gc-typing-dots">
          <div class="gc-typing-dot"></div>
          <div class="gc-typing-dot"></div>
          <div class="gc-typing-dot"></div>
        </div>
      </div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
  }

  // Remove typing indicator for this agent
  container.querySelector(`.gc-typing[data-agent="${agent}"]`)?.remove();

  const now = new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
  const msgId = `gcmsg-${Date.now()}-${Math.random().toString(36).slice(2,6)}`;

  const div = document.createElement('div');
  div.className = 'gc-msg';
  div.id = msgId;
  div.innerHTML = `
    ${meta.avatarImg
      ? `<div class="gc-msg-avatar ${meta.cls} msg-avatar-img"><img src="${meta.avatarImg}" alt="${agentId}" onerror="this.parentElement.innerHTML='${meta.icon}';this.parentElement.classList.remove('msg-avatar-img')"></div>`
      : `<div class="gc-msg-avatar ${meta.cls}">${meta.icon}</div>`
    }
    <div class="gc-msg-body">
      <div class="gc-msg-header">
        <span class="gc-msg-name">${displayName}</span>
        <span class="gc-msg-time">${now}${round ? ` · 第${round}轮` : ''}</span>
      </div>
      <div class="gc-msg-bubble">${escHtml(content)}</div>
      <div class="gc-msg-actions">
        <button class="gc-msg-action-btn" onclick="ttsSpeak(${JSON.stringify(content)}, '${agent}')">🔊 播放</button>
        <button class="gc-msg-action-btn" onclick="navigator.clipboard.writeText(${JSON.stringify(content)});toast('已复制','success')">📋 复制</button>
        ${elapsed ? `<span style="font-size:11px;color:var(--muted);padding:3px 6px">⏱ ${elapsed}s</span>` : ''}
      </div>
    </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

window.gcRun = async function() {
  const topic = document.getElementById('gcTopic')?.value.trim();
  if (!topic) { toast('请输入讨论主题', 'error'); return; }

  const agents = Array.from(GC_STATE.selectedAgents);
  if (agents.length < 2) { toast('请至少选择 2 个成员', 'error'); return; }

  const rounds = parseInt(document.getElementById('gcRounds')?.value || '1');
  const btn    = document.getElementById('gcRunBtn');
  if (btn) btn.disabled = true;
  GC_STATE.isRunning = true;

  // Show topic as divider
  const container = document.getElementById('gcMessages');
  if (container) {
    const welcome = container.querySelector('.gc-welcome');
    if (welcome) welcome.remove();
    const divEl = document.createElement('div');
    divEl.className = 'gc-divider';
    divEl.textContent = topic.length > 40 ? topic.slice(0,40)+'…' : topic;
    container.appendChild(divEl);
  }

  // Show typing indicators immediately
  for (const id of agents) {
    gcAddMessage({ agent: id, isTyping: true });
  }

  try {
    const r = await fetch(`${CONFIG.api}/groupchat/run`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ topic, agents, rounds }),
    });
    const { messages, error } = await r.json();
    if (error) throw new Error(error);

    // Remove all typing indicators
    container?.querySelectorAll('.gc-typing').forEach(el => el.remove());

    // Render messages
    const autoTts = document.getElementById('gcAutoTts')?.checked;
    for (const m of messages) {
      gcAddMessage(m);
      GC_STATE.messages.push(m);
      if (autoTts) await ttsSpeak(m.content, m.agent);
    }

    toast('讨论完成 ✓', 'success');
  } catch(e) {
    container?.querySelectorAll('.gc-typing').forEach(el => el.remove());
    gcAddMessage({ agent:'xi', name:'系统', content:`发生错误：${e.message}` });
    toast(`群聊失败: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    GC_STATE.isRunning = false;
    // Clear input
    const input = document.getElementById('gcTopic');
    if (input) input.value = '';
  }
};

window.gcKeydown = function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    gcRun();
  }
};

window.gcClearMessages = function() {
  const el = document.getElementById('gcMessages');
  if (!el) return;
  el.innerHTML = `
    <div class="gc-welcome">
      <div class="gc-welcome-icon">🤝</div>
      <div class="gc-welcome-title">欢迎来到 Anima 群聊</div>
      <div class="gc-welcome-sub">在下方输入讨论话题，让多个 Agent 一起讨论</div>
    </div>`;
  GC_STATE.messages = [];
};

window.gcExport = function() {
  if (!GC_STATE.messages.length) { toast('暂无消息可导出', 'error'); return; }
  const text = GC_STATE.messages.map(m =>
    `【${agentName(m.agent)}】${m.content}\n`
  ).join('\n');
  navigator.clipboard.writeText(text);
  toast('群聊记录已复制到剪贴板 ✓', 'success');
};

// Voice input
let _gcRecognition = null;
window.gcToggleVoice = function() {
  const btn = document.getElementById('gcVoiceBtn');
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) { toast('此浏览器不支持语音输入', 'error'); return; }

  if (_gcRecognition) {
    _gcRecognition.stop();
    _gcRecognition = null;
    if (btn) btn.classList.remove('recording');
    return;
  }
  const rec = new SpeechRecognition();
  rec.lang = 'zh-CN'; rec.interimResults = false; rec.maxAlternatives = 1;
  rec.onresult = (e) => {
    const t = e.results[0][0].transcript;
    const input = document.getElementById('gcTopic');
    if (input) input.value = (input.value ? input.value + '，' : '') + t;
  };
  rec.onend = () => {
    _gcRecognition = null;
    if (btn) btn.classList.remove('recording');
  };
  rec.onerror = () => { _gcRecognition = null; if(btn) btn.classList.remove('recording'); };
  rec.start();
  _gcRecognition = rec;
  if (btn) btn.classList.add('recording');
  toast('🎤 正在录音，说话后自动停止', 'info');
};

window.gcInsertEmoji = function() {
  const emojis = ['😊','👍','🎯','💡','🚀','⚡','🌟','📝','🤔','✅'];
  const input = document.getElementById('gcTopic');
  if (!input) return;
  input.value += emojis[Math.floor(Math.random() * emojis.length)];
  input.focus();
};

window.gcSaveSettings = function() {
  // Settings are applied in real time via checkbox
};

// ══════════════════════════════════════════════════
//  Settings — 角色命名 / 音色
// ══════════════════════════════════════════════════
const VOICE_OPTIONS = [
  { value:'zh-CN-YunxiNeural',    label:'云希（磁性男声）' },
  { value:'zh-CN-YunyangNeural',  label:'云扬（沉稳男声）' },
  { value:'zh-CN-YunjianNeural',  label:'云健（儒雅男声）' },
  { value:'zh-CN-XiaoxiaoNeural', label:'晓晓（温柔女声）' },
  { value:'zh-CN-XiaoyiNeural',   label:'晓伊（活泼女声）' },
  { value:'zh-CN-XiaohanNeural',  label:'晓涵（知性女声）' },
  { value:'zh-TW-YunJheNeural',   label:'云哲（台湾男声）' },
  { value:'en-US-AndrewNeural',   label:'Andrew（英语男声）' },
  { value:'en-US-AriaNeural',     label:'Aria（英语女声）' },
];

function renderAgentNameGrid() {
  const grid = document.getElementById('agentNameGrid');
  if (!grid) return;
  const roles = {
    xi:'日常助手', yiyi:'情感助手',
    tianyuan:'创业者', shoucang:'知识守护',
    executor:'执行者', writer:'写手',
    reader:'阅读者', critic:'评审',
  };
  const icons = DEFAULT_AGENT_META;
  grid.innerHTML = Object.entries(roles).map(([id, role]) => `
    <div class="agent-name-row">
      <span class="agent-name-icon">${icons[id].icon}</span>
      <div style="flex:1;min-width:0">
        <div class="agent-name-label">${role}</div>
        <div class="agent-name-fixed">${agentName(id)}</div>
      </div>
    </div>`).join('');
}

function renderAgentVoiceGrid() {
  const grid = document.getElementById('agentVoiceGrid');
  if (!grid) return;
  const defaultVoices = {
    xi:'zh-CN-YunxiNeural', yiyi:'zh-CN-XiaoxiaoNeural',
    tianyuan:'zh-CN-YunyangNeural', shoucang:'zh-CN-YunjianNeural',
    executor:'zh-CN-YunxiNeural', writer:'zh-CN-XiaoyiNeural',
    reader:'zh-CN-YunjianNeural', critic:'zh-CN-YunyangNeural',
  };
  const icons = DEFAULT_AGENT_META;
  const opts = VOICE_OPTIONS.map(v => `<option value="${v.value}">${v.label}</option>`).join('');
  grid.innerHTML = Object.keys(defaultVoices).map(id => `
    <div class="agent-name-row">
      <span class="agent-name-icon">${icons[id].icon}</span>
      <div style="flex:1;min-width:0">
        <div class="agent-name-label">${agentName(id)}</div>
        <select class="agent-voice-sel" id="voiceInput-${id}">${opts}</select>
      </div>
      <button class="gc-icon-btn" onclick="ttsSpeak('你好，我是${agentName(id)}','${id}')" title="试听">🔊</button>
    </div>`).join('');
  // Set current values
  for (const [id, def] of Object.entries(defaultVoices)) {
    const sel = document.getElementById(`voiceInput-${id}`);
    if (sel) sel.value = agentVoices[id] || def;
  }
}

window.saveAgentNames = async function() {
  toast('Agent 名称由系统固定，不可修改', 'info');
};

window.saveAgentVoices = async function() {
  const voices = {};
  for (const id of Object.keys(DEFAULT_AGENT_NAMES)) {
    const sel = document.getElementById(`voiceInput-${id}`);
    if (sel) voices[id] = sel.value;
  }
  try {
    const r = await fetch(`${CONFIG.api}/config/agents`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ voices }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error('保存失败');
    agentVoices = voices;
    toast('音色设置已保存 ✓', 'success');
  } catch(e) { toast(`保存失败: ${e.message}`, 'error'); }
};

window.saveUserAddress = async function() {
  // Always send all 4 keys so clearing one actually removes the stored value
  const address = {
    xi:       document.getElementById('addrXi')?.value.trim()       || '',
    yiyi:     document.getElementById('addrYiyi')?.value.trim()     || '',
    tianyuan: document.getElementById('addrTianyuan')?.value.trim() || '',
    shoucang: document.getElementById('addrShoucang')?.value.trim() || '',
  };
  try {
    const r = await fetch(`${CONFIG.api}/setup/save`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ user_address: address }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error('保存失败');
    toast('称呼设置已保存 ✓', 'success');
  } catch(e) { toast(`保存失败: ${e.message}`, 'error'); }
};

// Load existing user address into settings inputs
async function loadUserAddress() {
  try {
    const r = await fetch(`${CONFIG.api}/setup/status`);
    const d = await r.json();
    const addr = d.user_address || {};
    if (addr.xi)       { const el = document.getElementById('addrXi');       if(el) el.value = addr.xi; }
    if (addr.yiyi)     { const el = document.getElementById('addrYiyi');     if(el) el.value = addr.yiyi; }
    if (addr.tianyuan) { const el = document.getElementById('addrTianyuan'); if(el) el.value = addr.tianyuan; }
    if (addr.shoucang) { const el = document.getElementById('addrShoucang'); if(el) el.value = addr.shoucang; }
  } catch(_) {}
}

// ══════════════════════════════════════════════════
//  Onboarding 向导
// ══════════════════════════════════════════════════
let _obStep    = 0;
let _obLang    = 'zh';
const OB_TOTAL = 5;

window.showOnboarding = function() {
  _obStep = 0;
  document.getElementById('obOverlay')?.classList.remove('hidden');
  obGotoStep(0);
};

window.obSetLang = function(lang, btn) {
  _obLang = lang;
  document.querySelectorAll('.ob-lang-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
};

window.obNext = function() {
  // Validate step 2 (API keys)
  if (_obStep === 2) {
    const ds = document.getElementById('obDeepseekKey')?.value.trim();
    const ki = document.getElementById('obKimiKey')?.value.trim();
    const qw = document.getElementById('obQwenKey')?.value.trim();
    const oa = document.getElementById('obOpenaiKey')?.value.trim();
    if (!ds && !ki && !qw && !oa) {
      toast('请至少填写一个 API Key', 'error');
      return;
    }
  }
  if (_obStep < OB_TOTAL - 1) obGotoStep(_obStep + 1);
};

window.obPrev = function() {
  if (_obStep > 0) obGotoStep(_obStep - 1);
};

function obGotoStep(n) {
  _obStep = n;
  document.querySelectorAll('.ob-page').forEach((p,i) => {
    p.classList.toggle('active', i === n);
  });
  document.querySelectorAll('.ob-step').forEach((s,i) => {
    s.classList.toggle('active', i === n);
  });
}

window.obFinish = async function() {
  // Collect all data
  const api = {};
  const dk = document.getElementById('obDeepseekKey')?.value.trim();
  const kk = document.getElementById('obKimiKey')?.value.trim();
  const qk = document.getElementById('obQwenKey')?.value.trim();
  const ok = document.getElementById('obOpenaiKey')?.value.trim();
  if (dk) api.deepseek_key  = dk;
  if (kk) api.kimi_key      = kk;
  if (qk) api.qwen_key      = qk;
  if (ok) api.openai_key    = ok;

  // Agent 名称由系统固定，不由用户在 onboarding 设置
  const agent_names = { ...DEFAULT_AGENT_NAMES };

  // Collect per-agent user address (how each agent calls the user)
  const user_address = {};
  const addrXi       = document.getElementById('obAddrXi')?.value.trim();
  const addrYiyi     = document.getElementById('obAddrYiyi')?.value.trim();
  const addrTianyuan = document.getElementById('obAddrTianyuan')?.value.trim();
  const addrShoucang = document.getElementById('obAddrShoucang')?.value.trim();
  if (addrXi)       user_address.xi       = addrXi;
  if (addrYiyi)     user_address.yiyi     = addrYiyi;
  if (addrTianyuan) user_address.tianyuan = addrTianyuan;
  if (addrShoucang) user_address.shoucang = addrShoucang;

  try {
    const r = await fetch(`${CONFIG.api}/setup/save`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ api, agent_names, user_address, lang: _obLang }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error('保存失败');
    // Apply locally
    agentNames = { ...DEFAULT_AGENT_NAMES, ...agent_names };
    applyAgentNames();

    // ── 触发 FTUE 完成：守藏初始化 + 欢迎语 ──────────────────────
    let welcomeMsg = '';
    try {
      const wr = await fetch(`${CONFIG.api}/setup/complete`, { method: 'POST' });
      const wd = await wr.json();
      welcomeMsg = wd.welcome_message || '';
    } catch(_) {
      // 后端离线时降级：使用本地模板
      welcomeMsg = `嗨，很高兴认识你！我是 **Anima**，你的私人 AI 助理。\n\n我们这里有四位核心伙伴：\n\n- **Anima**（就是我）— 日常同行者，创作、探索、任务处理\n- **晞** — 情感陪伴，倾听你的心情，帮你理清思路\n- **陶朱** — 创业决策，带着一支 AI 小团队，专攻复杂任务\n- **守藏** — 知识管理者，帮你整理笔记，每天自动更新\n\n有什么想让我帮忙的吗？😊`;
    }

    // 隐藏 Onboarding 遮罩
    document.getElementById('obOverlay')?.classList.add('hidden');

    // 切换到 Anima 主聊天标签
    const xiTabBtn = document.querySelector('[data-tab="xi"]');
    switchTab('xi', xiTabBtn);

    // 注入欢迎消息到 Anima 聊天面板（支持 Markdown 渲染）
    if (welcomeMsg) {
      const box = document.getElementById('messages-xi');
      if (box) {
        // 移除空状态欢迎占位
        box.querySelector('.chat-welcome')?.remove();
        // 渲染 Markdown 欢迎气泡
        const agent = AGENTS['xi'] || { icon: '🤖', colorClass: 'xi-bg', name: agentNames.xi || 'xi' };
        const div = document.createElement('div');
        div.className = 'msg assistant ftue-welcome';
        div.innerHTML = `
          <div class="msg-avatar ${agent.colorClass}">${agent.icon}</div>
          <div class="msg-body">
            <div class="msg-bubble" style="max-width:520px">${markdownToHtml(welcomeMsg)}</div>
            <div class="msg-meta">${agent.name} · ${formatTime(new Date())}</div>
          </div>`;
        box.appendChild(div);
        scrollBottom('xi');
      }
    }

    toast('🎉 配置完成，欢迎使用 Anima！', 'success');

    // 重连 WebSocket / 检查后端
    if (!backendOnline) await checkBackend(true);
  } catch(e) {
    toast(`配置保存失败: ${e.message}`, 'error');
  }
};

// ══════════════════════════════════════════════════
//  推送通知 UI（设置页）
// ══════════════════════════════════════════════════
const NOTIF_API = () => `${CONFIG.api}/notifier`;

window.notifAdd = async function() {
  const name    = document.getElementById('notifName')?.value.trim();
  const type    = document.getElementById('notifType')?.value;
  const webhook = document.getElementById('notifWebhook')?.value.trim();
  const secret  = document.getElementById('notifSecret')?.value.trim();
  if (!name || !webhook) { toast('请填写渠道名称和 Webhook URL', 'error'); return; }
  try {
    const r = await fetch(`${NOTIF_API()}/channels`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, type, webhook, secret }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`✓ "${name}" 已添加`, 'success');
    document.getElementById('notifName').value    = '';
    document.getElementById('notifWebhook').value = '';
    document.getElementById('notifSecret').value  = '';
    notifLoadChannels();
  } catch(e) { toast(`添加失败: ${e.message}`, 'error'); }
};

async function notifLoadChannels() {
  const el = document.getElementById('notifChannelList');
  if (!el) return;
  try {
    const r = await fetch(`${NOTIF_API()}/channels`);
    const { channels } = await r.json();
    if (!channels.length) { el.innerHTML = '<span style="color:var(--muted)">暂无推送渠道</span>'; return; }
    const icons = { feishu:'🪶', dingtalk:'🔔' };
    el.innerHTML = channels.map(c => `
      <div class="sched-task-row">
        <span style="font-size:16px">${icons[c.type]||'📣'}</span>
        <div style="flex:1">
          <div style="font-weight:600;font-size:13px">${escHtml(c.name)}</div>
          <div style="font-size:11px;color:var(--muted)">${c.type} · ${escHtml(c.webhook.slice(0,40))}…</div>
        </div>
        <div style="display:flex;gap:4px">
          <button class="hdr-btn-sm" onclick="notifTest('${c.id}')">测试</button>
          <button class="kb-doc-del" onclick="notifDelete('${c.id}')">🗑</button>
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
}

window.notifTest = async function(id) {
  try {
    const r = await fetch(`${NOTIF_API()}/channels/${id}/test`, { method:'POST' });
    const { ok } = await r.json();
    toast(ok ? '测试推送成功 ✓' : '推送失败，请检查 Webhook', ok ? 'success' : 'error');
  } catch(e) { toast('测试失败', 'error'); }
};

window.notifDelete = async function(id) {
  if (!confirm('确认删除此推送渠道？')) return;
  try {
    await fetch(`${NOTIF_API()}/channels/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    notifLoadChannels();
  } catch(e) { toast('删除失败', 'error'); }
};

// Tab 切換时自动加载 (合并所有 tab 初始化)
const _origSwitchTab = window.switchTab;
window.switchTab = function(tabId, el) {
  _origSwitchTab(tabId, el);
  if (tabId === 'knowledge')   { kbLoadDocs(); vaultLoadTree(); }
  if (tabId === 'workflow')    { _refreshMembershipCache().then(()=>wfRenderTemplates()); if(typeof wfRender==='function') wfRender(); wfLoadList(); }
  if (tabId === 'scheduler')   { schedLoadTasks(); schedLoadLogs(); }
  if (tabId === 'filewatcher') { fwLoadRules(); fwLoadEvents(); }
  if (tabId === 'groupchat')   gcRenderMembers();
  if (tabId === 'reports')     { reportLoad('daily'); document.getElementById('reportDot')?.classList.add('hidden'); }
  if (tabId === 'skills')      skillsLoad();
  if (tabId === 'settings') {
    notifLoadChannels();
    renderAgentNameGrid();
    renderAgentVoiceGrid();
    apiCatalogLoad();
    loadUserAddress();
  }
};

// ══════════════════════════════════════════════════
//  初始化
// ══════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', async () => {
  // 1. 等待后端就绪（release版本后端 PyInstaller 解压约需 10 秒）
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
    await loadAgentConfig();

    // 3. 检查是否需要显示 Onboarding 向导
    try {
      const r = await fetch(`${CONFIG.api}/setup/status`);
      const { configured } = await r.json();
      if (!configured) {
        setTimeout(() => showOnboarding(), 500);
      } else {
        // 4. 已配置：检查晨间报告
        setTimeout(() => checkMorningReport(), 1500);
        // 5. 加载 API 目录状态
        setTimeout(() => apiCatalogLoad(), 2000);
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

// ════════════════════════════════════════════════════
//  晨间报告 Morning Card
// ════════════════════════════════════════════════════
async function checkMorningReport() {
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

// ════════════════════════════════════════════════════
//  Obsidian Vault 操作
// ════════════════════════════════════════════════════
let _vaultCurrentPath = '';
let _vaultEditMode = false;

async function vaultLoadTree() {
  const tree = document.getElementById('vaultTree');
  const pathBar = document.getElementById('vaultPathBar');
  if (!tree) return;
  try {
    const data = await fetch(`${CONFIG.api}/vault/tree`).then(r => r.json());
    if (pathBar) pathBar.textContent = data.vault_dir || '~/Anima-Vault';
    renderVaultTree(tree, data.tree || []);
  } catch(_) {
    tree.innerHTML = `
      <div class="es-vault-empty">
        <div style="font-size:32px;margin-bottom:8px">🗂</div>
        <div style="font-weight:600;font-size:13px;margin-bottom:4px">Vault 尚未创建</div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px">守藏首次运行 SOP 后会自动建立 Vault 记忆结构</div>
        <button class="btn-primary" style="font-size:12px;padding:6px 14px"
          onclick="fetch('${CONFIG.api}/shoucang/sop',{method:'POST'}).then(()=>{toast('守藏 SOP 已启动','success');setTimeout(vaultLoadTree,3000)})">
          🎓 立即初始化 Vault
        </button>
      </div>`;
  }
}
window.vaultLoadTree = vaultLoadTree;

function renderVaultTree(container, nodes, depth = 0) {
  container.innerHTML = nodes.map(node => renderVaultNode(node, depth)).join('');
}

function renderVaultNode(node, depth) {
  if (node.type === 'dir') {
    return `<div class="vtree-dir" style="padding-left:${depth*12}px" onclick="this.nextElementSibling?.classList.toggle('hidden')">
      📁 ${node.name}</div>
      <div class="vtree-children hidden">
        ${(node.children||[]).map(c => renderVaultNode(c, depth+1)).join('')}
      </div>`;
  }
  return `<div class="vtree-file ${node.path===_vaultCurrentPath?'active':''}"
    style="padding-left:${depth*12}px"
    onclick="vaultOpenFile('${node.path}')">
    📄 ${node.name}
  </div>`;
}

async function vaultOpenFile(path) {
  _vaultCurrentPath = path;
  const titleEl   = document.getElementById('vaultFileTitle');
  const previewEl = document.getElementById('vaultPreview');
  const editorEl  = document.getElementById('vaultEditor');
  if (titleEl) titleEl.textContent = path.split('/').pop() || path;
  try {
    const data = await fetch(`${CONFIG.api}/vault/file?path=${encodeURIComponent(path)}`).then(r => r.json());
    const content = data.content || '';
    if (editorEl) editorEl.value = content;
    if (previewEl) previewEl.innerHTML = markdownToHtml(content);
    _vaultEditMode = false;
    const editBtn = document.getElementById('vaultEditToggle');
    const saveBtn = document.getElementById('vaultSaveBtn');
    if (editBtn) editBtn.style.display = '';
    if (saveBtn) saveBtn.style.display = 'none';
    if (previewEl) previewEl.classList.remove('hidden');
    if (editorEl) editorEl.classList.add('hidden');
  } catch(_) {}
}
window.vaultOpenFile = vaultOpenFile;

window.vaultToggleEdit = function() {
  _vaultEditMode = !_vaultEditMode;
  const previewEl = document.getElementById('vaultPreview');
  const editorEl  = document.getElementById('vaultEditor');
  const editBtn   = document.getElementById('vaultEditToggle');
  const saveBtn   = document.getElementById('vaultSaveBtn');
  previewEl?.classList.toggle('hidden', _vaultEditMode);
  editorEl?.classList.toggle('hidden', !_vaultEditMode);
  if (editBtn) editBtn.textContent = _vaultEditMode ? '👁 预览' : '✏️ 编辑';
  if (saveBtn) saveBtn.style.display = _vaultEditMode ? '' : 'none';
};

window.vaultSave = async function() {
  const editorEl = document.getElementById('vaultEditor');
  if (!_vaultCurrentPath || !editorEl) return;
  try {
    await fetch(`${CONFIG.api}/vault/file`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ path: _vaultCurrentPath, content: editorEl.value })
    });
    toast('✅ 已保存', 'success');
    vaultOpenFile(_vaultCurrentPath);
  } catch(_) { toast('保存失败', 'error'); }
};

window.vaultNewFile = function() {
  const name = prompt('新笔记文件名（.md）：');
  if (!name) return;
  const path = name.endsWith('.md') ? name : name + '.md';
  _vaultCurrentPath = path;
  const editorEl  = document.getElementById('vaultEditor');
  const previewEl = document.getElementById('vaultPreview');
  const titleEl   = document.getElementById('vaultFileTitle');
  if (editorEl) { editorEl.value = `# ${name}\n\n`; editorEl.classList.remove('hidden'); }
  if (previewEl) previewEl.classList.add('hidden');
  if (titleEl) titleEl.textContent = path;
  _vaultEditMode = true;
  const saveBtn = document.getElementById('vaultSaveBtn');
  if (saveBtn) saveBtn.style.display = '';
};

window.shoucangRunSop = async function() {
  try {
    await fetch(`${CONFIG.api}/shoucang/sop`, { method: 'POST' });
    toast('🎓 守藏 SOP 已在后台启动，稍后刷新查看', 'success');
  } catch(_) { toast('启动失败', 'error'); }
};

// 简易 Markdown 渲染（避免引入外部库）
function markdownToHtml(md) {
  return md
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/\*(.+?)\*/g, '<i>$1</i>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<)(.+)$/gm, '$1')
    .trim();
}

// ════════════════════════════════════════════════════
//  API 目录 (Settings 设置页)
// ════════════════════════════════════════════════════
let _apiCatalog = [];
async function apiCatalogLoad() {
  const grid = document.getElementById('apiCatalogGrid');
  if (!grid) return;
  try {
    const data = await fetch(`${CONFIG.api}/config/api-catalog`).then(r => r.json());
    _apiCatalog = data.apis || [];
    renderApiCatalog(_apiCatalog);
  } catch(_) {}
}
window.apiCatalogLoad = apiCatalogLoad;

function renderApiCatalog(apis) {
  const grid = document.getElementById('apiCatalogGrid');
  if (!grid) return;
  const categories = {
    llm:    { label:'🧠 大语言模型', items:[] },
    search: { label:'🔍 搜索 & 网络', items:[] },
    tools:  { label:'🛠 效率工具',    items:[] },
    storage:{ label:'📦 存储',        items:[] },
  };
  apis.forEach(a => { (categories[a.category]||categories.tools).items.push(a); });
  grid.innerHTML = Object.values(categories).map(cat => cat.items.length ? `
    <div class="api-cat-label">${cat.label}</div>
    ${cat.items.map(a => `
      <div class="api-card ${a.configured?'configured':''}">
        <div class="api-card-left">
          <div class="api-card-icon">${a.icon}</div>
          <div class="api-card-info">
            <div class="api-card-name">${a.name}${a.required?'<span class="api-required">必需</span>':''}</div>
            <div class="api-card-desc">${a.desc}</div>
            ${a.configured ? `<div class="api-card-key">${a.masked_key}</div>` : ''}
          </div>
        </div>
        <div class="api-card-right">
          <div class="api-status-badge ${a.configured?'ok':'missing'}">${a.configured?'✓ 已配置':'⚠ 未配置'}</div>
          <div style="display:flex;gap:6px;margin-top:8px">
            <input class="api-key-input" type="password" id="apiKey_${a.id}"
              placeholder="粘贴 ${a.name} Key…"
              value="${a.configured ? '••••••••' : ''}">
          </div>
          <div style="display:flex;gap:6px;margin-top:6px">
            ${a.signup_url ? `<a class="api-signup-link" href="${a.signup_url}" target="_blank">获取 →</a>` : ''}
            ${a.configured ? `<button class="hdr-btn-sm" onclick="apiTest('${a.id}')">测试</button>` : ''}
          </div>
        </div>
      </div>`).join('')}
  ` : '').join('');
}

window.apiSaveAll = async function() {
  const updates = {};
  _apiCatalog.forEach(a => {
    const inp = document.getElementById(`apiKey_${a.id}`);
    if (inp && inp.value && !inp.value.startsWith('•')) {
      updates[a.config_key] = inp.value;
    }
  });
  if (!Object.keys(updates).length) { toast('没有新的 Key 需要保存', 'info'); return; }
  try {
    await fetch(`${CONFIG.api}/config/api-save`, {
      method: 'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(updates)
    });
    toast('✅ API Key 已保存', 'success');
    apiCatalogLoad();
  } catch(_) { toast('保存失败', 'error'); }
};

window.apiTest = async function(apiId) {
  toast('⏳ 测试连接…', 'info');
  try {
    const r = await fetch(`${CONFIG.api}/config/api-test/${apiId}`, { method:'POST' });
    const { ok, error } = await r.json();
    if (ok) toast(`✅ ${apiId} 连接正常`, 'success');
    else toast(`❌ ${apiId} 测试失败: ${error||'未知'}`, 'error');
  } catch(e) { toast(`测试失败: ${e.message}`, 'error'); }
};

// ════════════════════════════════════════════════════
//  会员系统 (Membership)
// ════════════════════════════════════════════════════
async function membershipLoad() {
  try {
    const r = await fetch(`${CONFIG.api}/membership/status`);
    const m = await r.json();
    const tierEl   = document.getElementById('membershipTier');
    const detailEl = document.getElementById('membershipDetail');
    const actRow   = document.getElementById('membershipActivateRow');
    const proRow   = document.getElementById('membershipActiveRow');
    const expEl    = document.getElementById('membershipExpiry');
    if (!tierEl) return;
    if (m.active && m.tier === 'pro') {
      tierEl.textContent = 'Anima Pro';
      detailEl.textContent = '全部 30 个 Skill + 预置工作流模板库已解锁';
      actRow.style.display = 'none';
      proRow.style.display = '';
      expEl.textContent = `有效期至 ${m.expires}（剩余 ${m.days_left} 天）`;
    } else {
      tierEl.textContent = 'Free';
      detailEl.textContent = m.error
        ? `8 个基础 Skill 可用 · ${m.error}`
        : '8 个基础 Skill 可用 · 激活 Pro 解锁全部 30 个';
      actRow.style.display = '';
      proRow.style.display = 'none';
    }
  } catch (_) {}
}

window.membershipActivate = async function() {
  const inp = document.getElementById('membershipCodeInput');
  const errEl = document.getElementById('membershipError');
  const code = (inp?.value || '').trim();
  if (!code) { errEl.textContent = '请输入激活码'; errEl.style.display = ''; return; }
  errEl.style.display = 'none';
  try {
    const r = await fetch(`${CONFIG.api}/membership/activate`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ code })
    });
    const res = await r.json();
    if (res.ok) {
      toast(`🎉 ${res.message}`, 'success');
      membershipLoad();
      skillsLoad();   // 刷新 Skill 墙解锁状态
    } else {
      errEl.textContent = res.error || '激活失败';
      errEl.style.display = '';
    }
  } catch (e) {
    errEl.textContent = '网络错误: ' + e.message;
    errEl.style.display = '';
  }
};

window.membershipDeactivate = async function() {
  if (!confirm('确定要取消激活？将退回免费版，Pro Skill 将被锁定。')) return;
  try {
    await fetch(`${CONFIG.api}/membership/deactivate`, { method: 'POST' });
    toast('已退回免费版', 'info');
    membershipLoad();
    skillsLoad();
  } catch (_) { toast('操作失败', 'error'); }
};

// ════════════════════════════════════════════════════
//  权限请求卡片 (PermissionRequest)
// ════════════════════════════════════════════════════
function showPermissionRequest(agentId, data) {
  const { api_name, reason, signup_url, alternatives, related } = data;
  // 在对话里插入一条特殊消息
  const msgs = document.getElementById(`messages-${agentId}`);
  if (!msgs) return;
  const div = document.createElement('div');
  div.className = 'perm-request-bubble';
  div.innerHTML = `
    <div class="perm-req-hdr">
      <span class="perm-req-icon">🔑</span>
      <span class="perm-req-title">${AGENTS[agentId]?.name||agentId} 需要 ${api_name}</span>
    </div>
    <div class="perm-req-reason">${reason}</div>
    ${alternatives?.length ? `<div class="perm-req-alts">或者可以用：${alternatives.map(a=>`<span class="perm-alt-chip">${a}</span>`).join('')}</div>` : ''}
    <div class="perm-req-actions">
      <button class="perm-go-btn" onclick="switchTab('settings',document.querySelector('[data-tab=settings]'));apiCatalogLoad()">⚙️ 去配置 →</button>
      ${signup_url ? `<a class="perm-signup-link" href="${signup_url}" target="_blank">获取 ${api_name} →</a>` : ''}
    </div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;

  // 同时在设置页权限卡片区显示
  const permArea = document.getElementById('permRequestArea');
  if (permArea) {
    const card = document.createElement('div');
    card.className = 'perm-request-card';
    card.innerHTML = `
      <div class="perm-req-hdr">
        <span class="perm-req-icon">⚠️</span>
        <b>${AGENTS[agentId]?.name||agentId}</b> 请求权限：<b>${api_name}</b>
        <button style="margin-left:auto;border:none;background:none;cursor:pointer;font-size:16px" onclick="this.closest('.perm-request-card').remove()">✕</button>
      </div>
      <div class="perm-req-reason">${reason}</div>
      <button class="perm-go-btn" onclick="apiCatalogLoad()">配置 ${api_name}</button>
    `;
    permArea.prepend(card);
  }
}

// ════════════════════════════════════════════════════
//  记忆学习 — "Anima 记住了" 反馈循环
// ════════════════════════════════════════════════════

/** 从聊天界面快捷触发记忆学习弹窗 */
window.showLearnDialog = function(agentId) {
  // 如果已有弹窗，移除
  document.getElementById('learnMemoryDialog')?.remove();
  const dialog = document.createElement('div');
  dialog.id = 'learnMemoryDialog';
  dialog.style.cssText = `position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.45);z-index:9999`;
  dialog.innerHTML = `
    <div style="background:var(--bg-card);border-radius:16px;padding:28px 32px;width:380px;max-width:90vw;box-shadow:0 8px 40px rgba(0,0,0,.25)">
      <div style="font-size:18px;font-weight:700;margin-bottom:4px">🧠 让 Anima 记住这件事</div>
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:18px">记忆会写入，让 Anima 在以后的对话中认识你</div>
      <label style="font-size:12px;color:var(--text-muted)">这是关于什么的？</label>
      <input id="learnKey" placeholder="例：我的编程语言偏好" style="width:100%;margin:6px 0 14px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-main);color:var(--text-main);font-size:13px;box-sizing:border-box">
      <label style="font-size:12px;color:var(--text-muted)">具体是什么？</label>
      <textarea id="learnValue" rows="3" placeholder="例：我主要用 Python 和 TypeScript，不喜欢 Java" style="width:100%;margin:6px 0 18px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-main);color:var(--text-main);font-size:13px;resize:vertical;box-sizing:border-box"></textarea>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button onclick="document.getElementById('learnMemoryDialog').remove()" style="padding:8px 18px;border:1px solid var(--border);border-radius:8px;background:none;color:var(--text-muted);cursor:pointer">取消</button>
        <button onclick="submitLearnMemory('${agentId}')" style="padding:8px 20px;border:none;border-radius:8px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer">让 Anima 记住 ✓</button>
      </div>
    </div>`;
  document.body.appendChild(dialog);
  setTimeout(() => document.getElementById('learnKey')?.focus(), 50);
};

window.submitLearnMemory = async function(agentId) {
  const key   = document.getElementById('learnKey')?.value.trim();
  const value = document.getElementById('learnValue')?.value.trim();
  if (!key || !value) { toast('请填写关键词和内容', 'error'); return; }
  try {
    const r = await fetch(`${CONFIG.api}/memory/learn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value, agent: agentId || 'xi' }),
    });
    const d = await r.json();
    document.getElementById('learnMemoryDialog')?.remove();
    if (d.ok) {
      toast(`🧠 Anima 记住了：${key}`, 'success');
      // 在当前聊天面板插入一条确认消息
      const effectiveAgent = agentId || 'xi';
      const box = document.getElementById(`messages-${effectiveAgent}`);
      if (box) {
        const agent = AGENTS[effectiveAgent] || { icon: '🤖', colorClass: 'xi-bg', name: agentNames[effectiveAgent] || 'Anima' };
        const div = document.createElement('div');
        div.className = 'msg assistant memory-confirm';
        div.innerHTML = `
          <div class="msg-avatar ${agent.colorClass}">${agent.icon}</div>
          <div class="msg-body">
            <div class="msg-bubble" style="background:linear-gradient(135deg,#e0f2fe,#ede9fe);border:1px solid #93c5fd;max-width:380px">
              🧠 <b>记住了</b> — <i>${escHtml(key)}</i><br>
              <span style="font-size:12px;color:var(--text-muted)">${escHtml(value.substring(0,80))}${value.length>80?'…':''}</span>
            </div>
            <div class="msg-meta">${agent.name} · ${formatTime(new Date())}</div>
          </div>`;
        box.appendChild(div);
        scrollBottom(effectiveAgent);
      }
    } else {
      toast(`保存失败: ${d.error || '未知错误'}`, 'error');
    }
  } catch(e) {
    toast(`网络错误: ${e.message}`, 'error');
  }
};

// ════════════════════════════════════════════════════
//  项目上下文管理
// ════════════════════════════════════════════════════
let _activeProject = null;

async function projectSwitcherLoad() {
  try {
    const data = await fetch(`${CONFIG.api}/projects`).then(r => r.json());
    _activeProject = data.active || null;
    const label = document.getElementById('activeProjectLabel');
    if (label) label.textContent = _activeProject || '无项目';
    const list  = document.getElementById('projectList');
    if (!list) return;
    const projects = data.projects || [];
    if (!projects.length) {
      list.innerHTML = '<div style="padding:8px 12px;font-size:12px;color:var(--text-muted)">暂无项目</div>';
      return;
    }
    list.innerHTML = projects.map(p => `
      <div class="ps-item ${p.is_active ? 'ps-active' : ''}" onclick="projectActivate('${escHtml(p.name)}')">
        <span class="ps-dot ${p.is_active ? 'active' : ''}"></span>
        <span class="ps-name">${escHtml(p.name)}</span>
        <span class="ps-files">${p.files} 文件</span>
      </div>`).join('');
  } catch(_) {}
}
window.projectSwitcherLoad = projectSwitcherLoad;

window.projectSwitcherToggle = function() {
  const menu = document.getElementById('projectSwitcherMenu');
  if (!menu) return;
  const isHidden = menu.classList.contains('hidden');
  menu.classList.toggle('hidden');
  if (isHidden) projectSwitcherLoad();
};

window.projectActivate = async function(name) {
  try {
    await fetch(`${CONFIG.api}/projects/${encodeURIComponent(name)}/activate`, { method: 'POST' });
    _activeProject = name;
    const label = document.getElementById('activeProjectLabel');
    if (label) label.textContent = name;
    document.getElementById('projectSwitcherMenu')?.classList.add('hidden');
    toast(`📁 已切换到项目：${name}`, 'success');
    projectSwitcherLoad();
  } catch(e) { toast(`切换失败: ${e.message}`, 'error'); }
};

window.projectDeactivate = async function() {
  try {
    await fetch(`${CONFIG.api}/projects/deactivate`, { method: 'POST' });
    _activeProject = null;
    const label = document.getElementById('activeProjectLabel');
    if (label) label.textContent = '无项目';
    document.getElementById('projectSwitcherMenu')?.classList.add('hidden');
    toast('已清除活跃项目', 'info');
  } catch(e) { toast(`失败: ${e.message}`, 'error'); }
};

window.projectCreate = async function() {
  const name = prompt('新项目名称（英文或中文，无特殊字符）：');
  if (!name || !name.trim()) return;
  const desc = prompt('项目简介（可留空）：') || '';
  try {
    const r = await fetch(`${CONFIG.api}/projects`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), description: desc }),
    });
    const d = await r.json();
    if (d.ok) {
      toast(`✅ 项目 "${name}" 创建成功！`, 'success');
      await projectActivate(name.trim());
    } else {
      toast(`创建失败: ${d.error}`, 'error');
    }
  } catch(e) { toast(`网络错误: ${e.message}`, 'error'); }
};

// 在后端连接成功后加载项目
const _origCheckBackend = window.checkBackend;  // will be set after this block runs

// ════════════════════════════════════════════════════
//  工作流 AI 辅助
// ════════════════════════════════════════════════════
window.wfAiAssist = function() {
  const panel = document.getElementById('wfAiPanel');
  if (panel) panel.style.display = panel.style.display === 'none' ? '' : 'none';
};

window.wfAiGenerate = async function() {
  const desc   = document.getElementById('wfAiDesc')?.value.trim();
  const status = document.getElementById('wfAiStatus');
  if (!desc) return;
  if (status) status.textContent = '⏳ Anima 正在思考…';

  // 构造提示词，让 Anima 以 JSON 格式返回工作流步骤
  const systemPrompt = `用户描述了一个工作流目标，请你返回一个 JSON 数组，每项格式为：
{"agent":"xi|yiyi|tianyuan|shoucang|executor|writer|reader|critic","prompt":"给该 Agent 的指令","pass_context":true}
只返回 JSON 数组，不要解释。`;

  try {
    // 直接通过 Anima WS 让 Anima 生成工作流
    const ws = wsConns['xi'];
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (status) status.textContent = '❌ Anima 未连接';
      return;
    }

    const sid = `wf-ai-${Date.now()}`;
    ws.send(JSON.stringify({
      action: 'chat',
      message: `${systemPrompt}\n\n用户目标：${desc}`,
      session_id: sid,
    }));

    // 监听一次性响应
    const handler = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'response' && msg.data?.summary) {
          ws.removeEventListener('message', handler);
          // 尝试解析 JSON
          const json = msg.data.summary.match(/\[[\s\S]*\]/)?.[0];
          if (json) {
            const steps = JSON.parse(json);
            wfLoadFromSteps(steps);
            if (status) status.textContent = `✅ 已生成 ${steps.length} 个步骤`;
            document.getElementById('wfAiPanel').style.display = 'none';
          } else {
            if (status) status.textContent = '❌ 无法解析工作流，请重试';
          }
        }
      } catch(_) {}
    };
    ws.addEventListener('message', handler);
    setTimeout(() => ws.removeEventListener('message', handler), 30000);
  } catch(e) {
    if (status) status.textContent = `❌ 错误: ${e.message}`;
  }
};

// 从步骤数组加载工作流到可视化画布
function wfLoadFromSteps(steps) {
  wfStepList.length = 0;
  steps.forEach(s => wfStepList.push(s));
  window._wfStepsData = wfStepList;
  renderWfCanvas(wfStepList);
}

// 渲染可视化工作流画布
function renderWfCanvas(steps) {
  const canvas = document.getElementById('wfCanvas');
  if (!canvas) return;
  const agentInfo = {
    xi:       { icon:'👩‍💼', name:'Anima' },
    yiyi:     { icon:'🌸',  name:'晞'   },
    tianyuan: { icon:'🏢',  name:'陶朱'   },
    shoucang: { icon:'📜', name:'守藏'  },
    executor: { icon:'⚡',  name:'执行者' },
    writer:   { icon:'✍️',  name:'写手'   },
    reader:   { icon:'📖',  name:'阅读者' },
    critic:   { icon:'🔍',  name:'评审'   },
  };

  if (!steps.length) {
    canvas.innerHTML = `
      <div class="es-workflow-empty">
        <div style="font-size:40px;margin-bottom:10px">⚡</div>
        <div style="font-weight:700;font-size:15px;margin-bottom:6px">设计你的第一个工作流</div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:14px;line-height:1.6">
          从右侧 <b>模板库</b> 选择模板快速开始<br>或点击下方按钮手动添加步骤
        </div>
        <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
          <button class="btn-primary" style="font-size:12px;padding:7px 16px" onclick="wfAddStep('sequential')">➕ 添加顺序步骤</button>
          <button class="hdr-btn-sm" onclick="wfAiAssist()">🤖 AI 辅助生成</button>
        </div>
      </div>`;
    return;
  }
  canvas.innerHTML = `<div class="wf-flow">` +
    steps.map((s, i) => {
      const a = agentInfo[s.agent] || { icon:'🤖', name: s.agent };
      return `
      <div class="wf-node" data-idx="${i}">
        <div class="wf-node-hdr">
          <span class="wf-node-step">步骤 ${i+1}</span>
          <div class="wf-node-agent">
            <span>${a.icon}</span>
            <select class="wf-node-sel" onchange="wfUpdateStep(${i},'agent',this.value)">
              ${Object.entries(agentInfo).map(([id,info])=>
                `<option value="${id}" ${s.agent===id?'selected':''}>${info.icon} ${info.name}</option>`
              ).join('')}
            </select>
          </div>
          <button class="wf-node-del" onclick="wfRemoveStep(${i})">✕</button>
        </div>
        <textarea class="wf-node-prompt" rows="2" placeholder="给 ${a.name} 的指令…"
          onchange="wfUpdateStep(${i},'prompt',this.value)">${s.prompt||''}</textarea>
        <label class="wf-node-ctx">
          <input type="checkbox" ${s.pass_context!==false?'checked':''} onchange="wfUpdateStep(${i},'pass_context',this.checked)">
          传递上下文
        </label>
      </div>
      ${i < steps.length-1 ? '<div class="wf-arrow">↓</div>' : ''}`;
    }).join('') + `</div>`;
}

window.wfUpdateStep = function(idx, field, value) {
  if (wfStepList[idx]) wfStepList[idx][field] = value;
};

window.wfRemoveStep = function(idx) {
  wfStepList.splice(idx, 1);
  renderWfCanvas(wfStepList);
};

// ════════════════════════════════════════════════════
//  wfAddStep / wfRemoveStep / wfNew — 画布联动补丁
//  （修正重复定义，保留类型参数 + 更新可视化画布）
// ════════════════════════════════════════════════════
// 保存 wfAddStep 原始实现（定义于上方，支持 type 参数）
const _wfAddStepBase = window.wfAddStep;

// 重新定义：在类型感知逻辑基础上追加画布刷新
window.wfAddStep = function(type = 'sequential') {
  _wfAddStepBase(type);          // 保留 parallel/condition/loop 逻辑
  window._wfStepsData = wfStepList;
  if (typeof renderWfCanvas === 'function') renderWfCanvas(wfStepList);
};

// wfRemoveStep 已在上方(line ~3500)定义为 canvas-aware 版本，无需再包装

window.wfNew = function() {
  wfStepList.length = 0;          // clear in place so wfRun refs same array
  window._wfStepsData = wfStepList;
  if (typeof renderWfCanvas === 'function') renderWfCanvas(wfStepList);
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = '我的工作流';
  const st = document.getElementById('wfRunStatus');
  const rs = document.getElementById('wfResults');
  if (st) st.textContent = '等待运行…';
  if (rs) rs.innerHTML = '';
};

// (tab 切換增强已合并到上方 _origSwitchTab override)
