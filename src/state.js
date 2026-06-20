/**
 * Anima — state.js
 * 共享配置、常量、运行时状态、工具函数
 */

// ══════════════════════════════════════════════════
//  配置 & 常量
// ══════════════════════════════════════════════════
export const CONFIG = {
  wsPort: 9100,
  dashPort: 9119,
  token: localStorage.getItem('anima_local_token') || '',
  get api()   { return `http://localhost:${this.wsPort}`; },
  get wsBase(){ return `ws://localhost:${this.wsPort}`; },
  fetchOpts(extra = {}) {
    const headers = { ...(extra.headers || {}) };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    return { ...extra, headers };
  },
};

export const AGENTS = {
  xi:       { id:'xi',   name:'Anima', icon:'👩‍💼', avatarImg:'assets/anima-avatar.png', title:'可依靠的她',  colorClass:'xi-bg'   },
  executor: { id:'executor', name:'执行者', icon:'⚡',  title:'任务执行',   colorClass:'executor-bg' },
  writer:   { id:'writer',   name:'写手',   icon:'✍️',  title:'内容创作',   colorClass:'writer-bg'   },
  reader:   { id:'reader',   name:'阅读者', icon:'📖',  title:'文档阅读',   colorClass:'reader-bg'   },
  critic:   { id:'critic',   name:'评审',   icon:'🔍',  title:'质量把关',   colorClass:'critic-bg'   },
};

export const WORKER_DETAILS = {
  executor: { name:'执行者', icon:'⚡', model:'DeepSeek-V4-Flash', desc:'代码执行 · 任务拆解 · 自动化',    cls:'executor-bg', tools:6 },
  writer:   { name:'写手',   icon:'✍️', model:'Kimi-K2.6',          desc:'文案撰写 · 报告 · 内容创作',     cls:'writer-bg',   tools:2 },
  reader:   { name:'阅读者', icon:'📖', model:'Kimi-128K',           desc:'长文阅读 · 文献分析 · 摘要',     cls:'reader-bg',   tools:2 },
  critic:   { name:'评审',   icon:'🔍', model:'DeepSeek-R1',         desc:'质量检查 · 批判思维 · 风险评估', cls:'critic-bg',   tools:2 },
};

// M-P2：delegate 时前端展示用的"能力"映射（角色 → 名称/图标/主题色）。
// 不切独立头像/气泡——只在「她」自己的消息流里显示她正在调用的能力角标，
// 弱化"一群 AI"观感，同时保留能力角标与主题色（与各 *-bg 配色呼应）。
export const DELEGATE_CAPS = {
  executor:        { name:'执行者',   icon:'⚡',  cls:'executor-bg'   },
  writer:          { name:'写手',     icon:'✍️',  cls:'writer-bg'     },
  reader:          { name:'阅读者',   icon:'📖',  cls:'reader-bg'     },
  critic:          { name:'评审',     icon:'🔍',  cls:'critic-bg'     },
  researcher:      { name:'研究员',   icon:'🌐',  cls:'researcher-bg' },
  analyst:         { name:'分析师',   icon:'📊',  cls:'analyst-bg'    },
  product_manager: { name:'产品经理', icon:'🗂️',  cls:'pm-bg'         },
};

// ══════════════════════════════════════════════════
//  运行时状态（可变共享）
// ══════════════════════════════════════════════════
export const wsConns  = {};
export const wsStatus = {};
export const chatState = {};
export const pendingFiles = {};
export const selectedModel = {
  xi:       'DeepSeek-V4-Pro',
  executor: 'DeepSeek-V4-Flash',
  writer:   'Kimi-K2.6',
  reader:   'Kimi-128K',
  critic:   'DeepSeek-R1',
};

export const runtime = {
  backendOnline: false,
  cmdItems: [],
  cmdFocusIdx: -1,
};

// 初始化每个 Agent 的状态
for (const id of Object.keys(AGENTS)) {
  wsStatus[id]   = { model:'-', tools:0, busy:false, connected:false };
  chatState[id]  = { pending:false, sessionId:null };
  pendingFiles[id] = [];
}

// Agent 配置（名称/音色）
export const DEFAULT_AGENT_NAMES = {
  xi:'Anima',
  executor:'执行者', writer:'写手', reader:'阅读者', critic:'评审',
};

export const DEFAULT_AGENT_META = {
  xi:       { icon:'👩‍💼', avatarImg:'assets/anima-avatar.png', cls:'xi-bg'   },
  executor: { icon:'⚡',  cls:'executor-bg' },
  writer:   { icon:'✍️',  cls:'writer-bg'   },
  reader:   { icon:'📖',  cls:'reader-bg'   },
  critic:   { icon:'🔍',  cls:'critic-bg'   },
};

export let agentNames  = { ...DEFAULT_AGENT_NAMES };
export let agentVoices = {};

export function setAgentNames(v)  { agentNames  = v; }
export function setAgentVoices(v) { agentVoices = v; }

export function agentName(id) { return agentNames[id] || DEFAULT_AGENT_NAMES[id] || id; }

// ══════════════════════════════════════════════════
//  工具函数
// ══════════════════════════════════════════════════
export function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

export function formatTime(d) {
  return d.toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
}

export function toast(msg, type = '') {
  const c = document.getElementById('toastContainer');
  if (!c) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, 2800);
}
window.toast = toast;

export function agentAvatarHtml(agent) {
  if (agent?.avatarImg) {
    return `<div class="msg-avatar ${agent.colorClass} msg-avatar-img">` +
           `<img src="${agent.avatarImg}" alt="${agent.name}" ` +
           `onerror="this.parentElement.innerHTML='${agent.icon}';this.parentElement.classList.remove('msg-avatar-img')">` +
           `</div>`;
  }
  return `<div class="msg-avatar ${agent.colorClass}">${agent.icon}</div>`;
}

export function markdownToHtml(md) {
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

export function scrollBottom(agentId) {
  const el = document.getElementById(`messages-${agentId}`);
  if (el) el.scrollTop = el.scrollHeight;
}
