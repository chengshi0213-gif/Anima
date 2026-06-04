/**
 * Anima — settings.js
 * Memory backend, knowledge base, agent config, settings, onboarding,
 * notifications, vault, API catalog, membership, permissions, project context, memory learning
 */
import { CONFIG, AGENTS, agentNames, agentVoices, setAgentNames, setAgentVoices, agentName, runtime, escHtml, formatTime, toast, scrollBottom } from './state.js';
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
// ── 数据目录（自定义存储位置）──
window.dataHomeLoad = async function() {
  const cur = document.getElementById('dataHomeCurrent');
  try {
    const d = await fetch(`${CONFIG.api}/config/data-home`).then(r => r.json());
    if (cur) cur.textContent = d.anima_home + (d.is_default ? '（默认）' : '');
  } catch (e) {
    if (cur) cur.textContent = '读取失败';
  }
};

window.dataHomeApply = async function() {
  const path = document.getElementById('dataHomeInput')?.value.trim() || '';
  const migrate = document.getElementById('dataHomeMigrate')?.checked ?? true;
  const btn = document.getElementById('dataHomeApplyBtn');
  const res = document.getElementById('dataHomeResult');
  if (!path) { toast('请填写新目录路径', 'error'); return; }
  if (!confirm(`确定把数据目录改到：\n${path}\n\n${migrate ? '现有数据会复制过去，' : ''}更改后需要重启 Anima 生效。`)) return;
  if (btn) { btn.disabled = true; btn.textContent = migrate ? '⏳ 迁移中…' : '⏳ 保存中…'; }
  if (res) res.textContent = '';
  try {
    const d = await fetch(`${CONFIG.api}/config/data-home`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, migrate }),
    }).then(r => r.json());
    if (d.ok) {
      const m = d.moved?.length ? `（已迁移：${d.moved.join('、')}）` : '';
      toast(`✅ ${d.message}`, 'success');
      if (res) res.innerHTML = `✅ 新目录：<code>${d.path}</code> ${m}<br><b>请重启 Anima 生效。</b>`;
      dataHomeLoad();
    } else {
      toast(d.error || '更改失败', 'error');
      if (res) res.textContent = '✗ ' + (d.error || '更改失败');
    }
  } catch (e) {
    toast(`更改失败: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✓ 更改目录'; }
  }
};

window.dataHomeReset = async function() {
  if (!confirm('恢复到默认目录（系统盘 ~/.anima）？\n不会删除你已迁移的数据，仅改回指向。重启后生效。')) return;
  try {
    const d = await fetch(`${CONFIG.api}/config/data-home/reset`, { method: 'POST' }).then(r => r.json());
    if (d.ok) { toast(`✅ ${d.message}`, 'success'); dataHomeLoad(); }
  } catch (e) { toast(`失败: ${e.message}`, 'error'); }
};

// ── Transfer Memory：从别的 AI 导入记忆 ──
window.memTransferImport = async function() {
  const text = document.getElementById('tmText')?.value.trim() || '';
  const source = document.getElementById('tmSource')?.value.trim() || '';
  const btn = document.getElementById('tmImportBtn');
  const res = document.getElementById('tmResult');
  if (text.length < 8) { toast('内容太短，粘点东西再导入', 'error'); return; }
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 守藏提炼中…'; }
  if (res) res.textContent = '';
  try {
    const d = await fetch(`${CONFIG.api}/memory/import`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, source }),
    }).then(r => r.json());
    if (d.ok) {
      const tip = d.mode === 'raw'
        ? `已存为 ${d.imported} 条（未接模型，整段归档；接入模型后可自动提炼）`
        : `✅ 提炼并存入 ${d.imported} 条关于你的记忆`;
      toast(tip, 'success');
      if (res) res.textContent = tip;
      const ta = document.getElementById('tmText'); if (ta) ta.value = '';
      if (typeof window.memLoadEntries === 'function') window.memLoadEntries();
    } else {
      toast(d.error || '导入失败', 'error');
    }
  } catch (e) {
    toast(`导入失败: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✨ 提炼并导入'; }
  }
};

window.memTransferFile = function(ev) {
  const f = ev.target.files?.[0];
  if (!f) return;
  if (f.size > 2 * 1024 * 1024) { toast('文件过大（上限 2MB）', 'error'); ev.target.value = ''; return; }
  const reader = new FileReader();
  reader.onload = () => {
    const ta = document.getElementById('tmText');
    if (ta) ta.value = String(reader.result || '').slice(0, 24000);
    const src = document.getElementById('tmSource');
    if (src && !src.value) src.value = f.name.replace(/\.(txt|md|json)$/i, '');
    const hint = document.getElementById('tmHint');
    if (hint) hint.textContent = `已载入 ${f.name}`;
  };
  reader.readAsText(f);
  ev.target.value = '';
};

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

//  Agent 配置（名称 / 音色） — 全局存储
// ══════════════════════════════════════════════════
// agentNames and agentVoices are imported from state.js

const DEFAULT_AGENT_META = {
  xi:       { icon:'🪔', avatarImg:'assets/xi-avatar.png', cls:'xi-bg'   },
  executor: { icon:'⚡',  cls:'executor-bg' },
  writer:   { icon:'✍️',  cls:'writer-bg'   },
  reader:   { icon:'📖',  cls:'reader-bg'   },
  critic:   { icon:'🔍',  cls:'critic-bg'   },
};

const DEFAULT_AGENT_NAMES = {
  xi:'Anima',
  executor:'执行者', writer:'写手', reader:'阅读者', critic:'评审',
};

async function loadAgentConfig() {
  try {
    const r = await fetch(`${CONFIG.api}/config/agents`);
    if (!r.ok) return;
    const { voices } = await r.json();
    setAgentVoices({ ...voices });
  } catch(_) {}
  setAgentNames({ ...DEFAULT_AGENT_NAMES });
}
window.loadAgentConfig = loadAgentConfig;

function applyAgentNames() {
  // 更新侧边栏导航显示名称
  const navMap = {
    xi:       '[data-tab=xi]',
  };
  for (const [id, sel] of Object.entries(navMap)) {
    const el = document.querySelector(sel);
    if (el) {
      const icon = el.querySelector('.nav-icon')?.outerHTML || '';
      const dot  = el.querySelector('.agent-dot')?.outerHTML || '';
      el.innerHTML = `${icon}${agentName(id)}${dot}`;
    }
  }
  // 更新群聊成员面板（跨模块，安全调用）
  window.gcRenderMembers?.();
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
    xi:'日常助手',
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
    xi:'zh-CN-XiaoxiaoNeural',
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
    setAgentVoices(voices);
    toast('音色设置已保存 ✓', 'success');
  } catch(e) { toast(`保存失败: ${e.message}`, 'error'); }
};

window.saveUserAddress = async function() {
  const address = {
    xi:       document.getElementById('addrXi')?.value.trim()       || '',
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
  } catch(_) {}
}


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
  // 限定 #obOverlay 内：authOverlay 也用了 .ob-page/.ob-step，全局查询会错位
  document.querySelectorAll('#obOverlay .ob-page').forEach((p,i) => {
    p.classList.toggle('active', i === n);
  });
  document.querySelectorAll('#obOverlay .ob-steps .ob-step').forEach((s,i) => {
    s.classList.toggle('active', i === n);
  });
}

window.obFinish = async function() {
  // Collect all data
  const api = {};
  const dk = document.getElementById('obDeepseekKey')?.value.trim();
  const kk = document.getElementById('obKimiKey')?.value.trim();
  const qk = document.getElementById('obQwenKey')?.value.trim();
  const gk = document.getElementById('obGlmKey')?.value.trim();
  const mk = document.getElementById('obMimoKey')?.value.trim();
  const ok = document.getElementById('obOpenaiKey')?.value.trim();
  if (dk) api.deepseek_key  = dk;
  if (kk) api.kimi_key      = kk;
  if (qk) api.qwen_key      = qk;
  if (gk) api.glm_key       = gk;
  if (mk) api.mimo_key      = mk;
  if (ok) api.openai_key    = ok;

  // Agent 名称由系统固定，不由用户在 onboarding 设置
  const agent_names = { ...DEFAULT_AGENT_NAMES };

  // Collect per-agent user address (how each agent calls the user)
  const user_address = {};
  const addrXi       = document.getElementById('obAddrXi')?.value.trim();
  if (addrXi)       user_address.xi       = addrXi;

  try {
    const r = await fetch(`${CONFIG.api}/setup/save`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ api, agent_names, user_address, lang: _obLang }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error('保存失败');

    // ⚡ 保存成功即放行：先进门，再做装饰。任何装饰报错都不该把用户挡在外面。
    document.getElementById('obOverlay')?.classList.add('hidden');
    const xiTabBtn = document.querySelector('[data-tab="xi"]');
    try { switchTab('xi', xiTabBtn); } catch (_) {}

    // Apply locally（容错）
    try {
      setAgentNames({ ...DEFAULT_AGENT_NAMES, ...agent_names });
      applyAgentNames();
    } catch (_) {}

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
    if (!runtime.backendOnline) await window.checkBackend?.(true);
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

// ══════════════════════════════════════════════════
//  飞书双向机器人
// ════════════════════════════════════════════════════
const FEISHU_API = () => `${CONFIG.api}/integrations/feishu`;

function _feishuRenderStatus(status) {
  const el = document.getElementById('feishuStatus');
  if (!el || !status) return;
  if (status.running)      { el.textContent = '● 已连接，正在收消息'; el.style.color = 'var(--success, #2ecc71)'; }
  else if (status.error)   { el.textContent = '● 未连接：' + status.error; el.style.color = 'var(--error, #e74c3c)'; }
  else if (status.enabled) { el.textContent = '○ 已启用但未连接'; el.style.color = 'var(--muted)'; }
  else                     { el.textContent = '○ 未启用'; el.style.color = 'var(--muted)'; }
}

async function feishuLoad() {
  const idEl = document.getElementById('feishuAppId');
  if (!idEl) return;
  try {
    const { config, status } = await fetch(FEISHU_API(), CONFIG.fetchOpts()).then(r => r.json());
    idEl.value = config.app_id || '';
    const secEl = document.getElementById('feishuSecret');
    if (secEl) secEl.placeholder = config.has_secret ? 'App Secret 已保存（留空不改）' : 'App Secret';
    const ag = document.getElementById('feishuAgent'); if (ag) ag.value = config.default_agent || 'xi';
    const en = document.getElementById('feishuEnabled'); if (en) en.checked = !!config.enabled;
    _feishuRenderStatus(status);
  } catch (e) { /* 后端未起时静默 */ }
}

window.feishuSave = async function() {
  const app_id  = document.getElementById('feishuAppId')?.value.trim();
  const secret  = document.getElementById('feishuSecret')?.value;          // 留空=不改
  const agent   = document.getElementById('feishuAgent')?.value || 'xi';
  const enabled = document.getElementById('feishuEnabled')?.checked || false;
  if (!app_id) { toast('请填写 App ID', 'error'); return; }
  if (enabled && !secret) {
    // 启用但本次没填密钥——依赖已存的；若从未存过则提示
    const cur = await fetch(FEISHU_API(), CONFIG.fetchOpts()).then(r => r.json()).catch(()=>null);
    if (cur && !cur.config.has_secret) { toast('首次启用请填写 App Secret', 'error'); return; }
  }
  try {
    const body = { app_id, default_agent: agent, enabled, strip_at: true };
    if (secret) body.app_secret = secret;
    const d = await fetch(FEISHU_API(), CONFIG.fetchOpts({
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })).then(r => r.json());
    const secEl = document.getElementById('feishuSecret'); if (secEl) secEl.value = '';
    _feishuRenderStatus(d.status);
    if (enabled && d.apply && d.apply.ok === false) {
      toast('已保存，但连接失败：' + (d.apply.error || ''), 'error');
    } else {
      toast(enabled ? '已保存并连接 ✓' : '已保存（未启用）', 'success');
    }
  } catch (e) { toast('保存失败: ' + e.message, 'error'); }
};

window.feishuTest = async function() {
  const app_id = document.getElementById('feishuAppId')?.value.trim();
  const secret = document.getElementById('feishuSecret')?.value;
  const el = document.getElementById('feishuStatus');
  if (el) { el.textContent = '校验中…'; el.style.color = 'var(--muted)'; }
  try {
    const body = {}; if (app_id) body.app_id = app_id; if (secret) body.app_secret = secret;
    const d = await fetch(`${FEISHU_API()}/test`, CONFIG.fetchOpts({
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })).then(r => r.json());
    if (d.ok) { toast('凭证有效 ✓', 'success'); if (el){ el.textContent='● 凭证有效'; el.style.color='var(--success,#2ecc71)'; } }
    else      { toast('凭证无效：' + (d.error || ''), 'error'); if (el){ el.textContent='● ' + (d.error||'无效'); el.style.color='var(--error,#e74c3c)'; } }
  } catch (e) { toast('校验失败: ' + e.message, 'error'); }
};

// ── 桌面操作（computer use）─────────────────────────────
const COMPUTER_API = () => `${CONFIG.api}/integrations/computer`;
let _computerPoll = null;

function _computerRenderStatus(cfg) {
  const el = document.getElementById('computerStatus');
  if (!el || !cfg) return;
  if (!cfg.available)   { el.textContent = '● 依赖缺失：请 pip install pyautogui'; el.style.color = 'var(--error,#e74c3c)'; return; }
  if (!cfg.enabled || cfg.mode === 'off') { el.textContent = '○ 已关闭'; el.style.color = 'var(--muted)'; return; }
  const label = { readonly:'只读', confirm:'逐步确认', auto:'完全自动' }[cfg.mode] || cfg.mode;
  el.textContent = '● 已启用 · ' + label;
  el.style.color = cfg.mode === 'auto' ? 'var(--error,#e74c3c)' : 'var(--success,#2ecc71)';
}

async function computerLoad() {
  const en = document.getElementById('computerEnabled');
  if (!en) return;
  try {
    const { config, pending } = await fetch(COMPUTER_API(), CONFIG.fetchOpts()).then(r => r.json());
    en.checked = !!config.enabled;
    const md = document.getElementById('computerMode');
    if (md) md.value = (config.mode && config.mode !== 'off') ? config.mode : 'confirm';
    _computerRenderStatus(config);
    _computerRenderPending(pending);
    // confirm 模式下轮询待确认动作
    _computerStartPoll(config);
  } catch (e) { /* 后端未起时静默 */ }
}

function _computerStartPoll(config) {
  if (_computerPoll) { clearInterval(_computerPoll); _computerPoll = null; }
  if (config && config.enabled && config.mode === 'confirm') {
    _computerPoll = setInterval(async () => {
      try {
        const { pending } = await fetch(COMPUTER_API(), CONFIG.fetchOpts()).then(r => r.json());
        _computerRenderPending(pending);
      } catch (e) {}
    }, 1500);
  }
}

function _computerRenderPending(pending) {
  const box = document.getElementById('computerPending');
  if (!box) return;
  if (!pending || !pending.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = 'flex';
  box.innerHTML = '<div style="font-size:12px;color:var(--accent);font-weight:600">人格请求执行桌面动作，请确认：</div>' +
    pending.map(p => `
      <div style="display:flex;align-items:center;gap:8px;font-size:13px">
        <span style="flex:1;color:var(--text)">${_esc(p.summary)}</span>
        <button class="hdr-btn-sm" onclick="computerResolve('${p.id}',true)">允许</button>
        <button class="hdr-btn-sm" onclick="computerResolve('${p.id}',false)">拒绝</button>
      </div>`).join('');
}

function _esc(s) { return String(s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

window.computerResolve = async function(id, approved) {
  try {
    const { pending } = await fetch(`${COMPUTER_API()}/resolve`, CONFIG.fetchOpts({
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, approved }),
    })).then(r => r.json());
    _computerRenderPending(pending);
  } catch (e) { toast('确认失败: ' + e.message, 'error'); }
};

window.computerSave = async function() {
  const enabled = document.getElementById('computerEnabled')?.checked || false;
  const mode    = document.getElementById('computerMode')?.value || 'confirm';
  if (enabled && mode === 'auto') {
    if (!confirm('「完全自动」模式下，人格会在本机内自由点击鼠标键盘，不再逐个征求你同意。\n急停方法：把鼠标猛甩到屏幕左上角。\n\n确定开启吗？')) return;
  }
  try {
    const body = { enabled, mode: enabled ? mode : 'off' };
    const d = await fetch(COMPUTER_API(), CONFIG.fetchOpts({
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })).then(r => r.json());
    _computerRenderStatus(d.config);
    _computerStartPoll(d.config);
    toast(enabled ? '已保存桌面操作设置 ✓' : '已关闭桌面操作', 'success');
  } catch (e) { toast('保存失败: ' + e.message, 'error'); }
};

// ── 企业微信 / 公众号 ───────────────────────────────────
const WECHAT_API = () => `${CONFIG.api}/integrations/wechat`;

window.wechatToggleProvider = function() {
  const prov = document.getElementById('wechatProvider')?.value || 'wecom';
  const we = document.getElementById('wechatWecomFields');
  const mp = document.getElementById('wechatMpFields');
  if (we) we.style.display = prov === 'wecom' ? 'flex' : 'none';
  if (mp) mp.style.display = prov === 'mp' ? 'flex' : 'none';
};

function _wechatRenderStatus(status) {
  const el = document.getElementById('wechatStatus');
  if (!el || !status) return;
  if (status.error)          { el.textContent = '● ' + status.error; el.style.color = 'var(--error,#e74c3c)'; }
  else if (status.enabled && status.configured) { el.textContent = '● 已启用 · 回调待接收'; el.style.color = 'var(--success,#2ecc71)'; }
  else if (status.enabled)   { el.textContent = '○ 已启用但配置不全'; el.style.color = 'var(--muted)'; }
  else                       { el.textContent = '○ 未启用'; el.style.color = 'var(--muted)'; }
}

async function wechatLoad() {
  const tk = document.getElementById('wechatToken');
  if (!tk) return;
  try {
    const { config, status } = await fetch(WECHAT_API(), CONFIG.fetchOpts()).then(r => r.json());
    const prov = document.getElementById('wechatProvider'); if (prov) prov.value = config.provider || 'wecom';
    window.wechatToggleProvider();
    tk.value = config.token || '';
    const setPh = (id, has, txt) => { const e = document.getElementById(id); if (e) e.placeholder = has ? (txt + '（已存，留空不改）') : txt; };
    setPh('wechatAesKey', config.has_aes_key, 'EncodingAESKey（43 位）');
    setPh('wechatCorpSecret', config.has_corp_secret, '应用 Secret');
    setPh('wechatAppSecret', config.has_app_secret, 'AppSecret');
    const ci = document.getElementById('wechatCorpId'); if (ci) ci.value = config.corp_id || '';
    const ai = document.getElementById('wechatAgentId'); if (ai) ai.value = config.agent_id || '';
    const ap = document.getElementById('wechatAppId'); if (ap) ap.value = config.app_id || '';
    const ag = document.getElementById('wechatAgent'); if (ag) ag.value = config.default_agent || 'xi';
    const en = document.getElementById('wechatEnabled'); if (en) en.checked = !!config.enabled;
    _wechatRenderStatus(status);
  } catch (e) { /* 后端未起时静默 */ }
}

window.wechatSave = async function() {
  const prov = document.getElementById('wechatProvider')?.value || 'wecom';
  const body = {
    provider: prov,
    token: document.getElementById('wechatToken')?.value.trim() || '',
    default_agent: document.getElementById('wechatAgent')?.value || 'xi',
    enabled: document.getElementById('wechatEnabled')?.checked || false,
  };
  const aes = document.getElementById('wechatAesKey')?.value;       if (aes) body.aes_key = aes;
  if (prov === 'wecom') {
    body.corp_id = document.getElementById('wechatCorpId')?.value.trim() || '';
    body.agent_id = document.getElementById('wechatAgentId')?.value.trim() || '';
    const cs = document.getElementById('wechatCorpSecret')?.value; if (cs) body.corp_secret = cs;
  } else {
    body.app_id = document.getElementById('wechatAppId')?.value.trim() || '';
    const as = document.getElementById('wechatAppSecret')?.value;   if (as) body.app_secret = as;
  }
  if (!body.token) { toast('请填写 Token', 'error'); return; }
  try {
    const d = await fetch(WECHAT_API(), CONFIG.fetchOpts({
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })).then(r => r.json());
    // 清空已填的密钥框
    ['wechatAesKey','wechatCorpSecret','wechatAppSecret'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
    _wechatRenderStatus(d.status);
    if (body.enabled && d.status && !d.status.configured) toast('已保存，但配置还不完整', 'error');
    else toast(body.enabled ? '已保存并启用 ✓ 回微信后台保存回调即可接通' : '已保存（未启用）', 'success');
  } catch (e) { toast('保存失败: ' + e.message, 'error'); }
};

// Tab 切換时自动加载 (合并所有 tab 初始化)
const _origSwitchTab = window.switchTab;
window.switchTab = function(tabId, el) {
  _origSwitchTab(tabId, el);
  if (tabId === 'knowledge')   { kbLoadDocs(); vaultLoadTree(); }
  if (tabId === 'workflow')    { (window._refreshMembershipCache?.() || Promise.resolve()).then(()=>window.wfRenderTemplates?.()); if(typeof window.wfRender==='function') window.wfRender(); window.wfLoadList?.(); }
  if (tabId === 'scheduler')   { schedLoadTasks(); schedLoadLogs(); }
  if (tabId === 'filewatcher') { fwLoadRules(); fwLoadEvents(); }
  if (tabId === 'groupchat')   window.gcRenderMembers?.();
  if (tabId === 'reports')     { reportLoad('daily'); document.getElementById('reportDot')?.classList.add('hidden'); }
  if (tabId === 'skills')      skillsLoad();
  if (tabId === 'achievements') window.achLoad?.();
  if (tabId === 'settings') {
    notifLoadChannels();
    feishuLoad();
    computerLoad();
    wechatLoad();
    renderAgentNameGrid();
    renderAgentVoiceGrid();
    apiCatalogLoad();
    loadUserAddress();
    window.dataHomeLoad?.();
  }
};

// ══════════════════════════════════════════════════

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
