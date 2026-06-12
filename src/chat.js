/**
 * Anima — chat.js
 * Tab 切换、聊天 UI、模型选择器、文件上传、侧边栏历史
 */
import { CONFIG, AGENTS, WORKER_DETAILS, DELEGATE_CAPS, wsStatus, chatState, pendingFiles, selectedModel, runtime, escHtml, markdownToHtml, formatTime, toast, agentAvatarHtml, scrollBottom } from './state.js';
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

  // 若选了 Skill，在消息前拼入 system_prompt 指令
  const skillPrompt = inp.dataset.skillPrompt || '';
  const skillName   = inp.dataset.skillName   || '';
  const fullMessage = skillPrompt
    ? `[启用 Skill：${skillName}]\n${skillPrompt}\n\n---\n${text}`
    : text;
  // 清除 skill 状态
  delete inp.dataset.skillId;
  delete inp.dataset.skillPrompt;
  delete inp.dataset.skillName;

  document.querySelector(`#messages-${agentId} .chat-welcome`)?.remove();
  appendUserMsg(agentId, text, files);   // 用户看到干净消息，不含 system_prompt
  inp.value = '';
  inp.style.height = 'auto';
  clearFileBar(agentId);

  const sent = wsSend(agentId, {
    action: 'chat',
    message: fullMessage,               // 实际发送含 skill 指令
    model: selectedModel[agentId],
    session_id: chatState[agentId].sessionId,
    files: files.map(f => ({ name: f.name, content: f.content, type: f.type })),
  });
  if (!sent) appendErrMsg(agentId, 'WebSocket 未连接，请等待自动重连');
  updateSendBtn(agentId);
};

window.stopMessage = function(agentId) {
  import('./ws.js').then(m => {
    const send = m.sendWS || m.wsSend;
    if (send) send(agentId, { action: 'cancel' });
  });
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
      <div class="msg-bubble">${markdownToHtml(data.summary || '（完成）')}</div>
      ${toolHtml}
      <div class="msg-meta">${agent.name} · ${formatTime(new Date())} · ${selectedModel[agentId]}</div>
    </div>`;
  box.appendChild(div);
  scrollBottom(agentId);
}
window.appendAssistantMsg = appendAssistantMsg;

// ── 流式缓冲区（per-agent）：文字积累 + debounce timer ────────────────────
const _streamBuf = {};

export function appendAssistantDelta(agentId, content) {
  if (!content) return;
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  document.querySelector(`#messages-${agentId} .chat-welcome`)?.remove();

  let div = box.querySelector('.streaming-msg');
  if (!div) {
    removeThinking(agentId);
    const agent = AGENTS[agentId];
    div = document.createElement('div');
    div.className = 'msg assistant streaming-msg';
    div.innerHTML = `
      ${agentAvatarHtml(agent)}
      <div class="msg-body">
        <div class="msg-bubble"></div>
        <div class="msg-meta">${agent.name} · ${formatTime(new Date())} · ${selectedModel[agentId]}</div>
      </div>`;
    box.appendChild(div);
    _streamBuf[agentId] = { text: '', timer: null };
  }

  const buf = (_streamBuf[agentId] = _streamBuf[agentId] || { text: '', timer: null });
  buf.text += content;

  // 每 150ms 渲染一次 Markdown，避免每个 token 都重写 DOM（体感：~6fps 的逐字感）
  if (!buf.timer) {
    buf.timer = setTimeout(() => {
      const bubble = box.querySelector('.streaming-msg .msg-bubble');
      if (bubble) {
        bubble.innerHTML = markdownToHtml(buf.text)
          + '<span class="msg-cursor" aria-hidden="true"></span>';
      }
      buf.timer = null;
    }, 150);
  }

  scrollBottom(agentId);
}
window.appendAssistantDelta = appendAssistantDelta;

// 流式完成：升级到位（upgrade-in-place），不销毁重建气泡，零闪烁
export function finalizeStreamingMsg(agentId, data) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;

  // 刷新待渲染的 debounce timer
  const buf = _streamBuf[agentId];
  if (buf?.timer) clearTimeout(buf.timer);
  delete _streamBuf[agentId];

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

  const div = box.querySelector('.streaming-msg');

  if (div) {
    // 升级到位：渲染最终 Markdown，移除光标，插入工具步骤
    const bubble = div.querySelector('.msg-bubble');
    if (bubble) {
      bubble.innerHTML = markdownToHtml(data.summary || '（完成）');
    }
    const meta = div.querySelector('.msg-meta');
    if (meta) {
      meta.textContent = `${agent.name} · ${formatTime(new Date())} · ${selectedModel[agentId]}`;
    }
    if (toolHtml && meta) {
      const toolWrap = document.createElement('div');
      toolWrap.innerHTML = toolHtml;
      meta.before(toolWrap.firstElementChild);
    }
    // 去掉 streaming-msg 类：光标 CSS 动画消失，气泡呼吸光环停止
    div.classList.remove('streaming-msg');
  } else {
    // 无流式内容（纯工具调用无文字输出）：降级为全量渲染
    const newDiv = document.createElement('div');
    newDiv.className = 'msg assistant';
    newDiv.innerHTML = `
      ${agentAvatarHtml(agent)}
      <div class="msg-body">
        <div class="msg-bubble">${markdownToHtml(data.summary || '（完成）')}</div>
        ${toolHtml}
        <div class="msg-meta">${agent.name} · ${formatTime(new Date())} · ${selectedModel[agentId]}</div>
      </div>`;
    box.appendChild(newDiv);
  }

  scrollBottom(agentId);
}
window.finalizeStreamingMsg = finalizeStreamingMsg;

export function removeStreamingMsg(agentId) {
  // 同时清理缓冲区
  const buf = _streamBuf[agentId];
  if (buf?.timer) clearTimeout(buf.timer);
  delete _streamBuf[agentId];
  document.querySelector(`#messages-${agentId} .streaming-msg`)?.remove();
}
window.removeStreamingMsg = removeStreamingMsg;

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

// ══════════════════════════════════════════════════
//  ConfirmCard —— M14 危险操作确认卡
//  后端 confirm_request{confirm_id,kind,tool,detail,risk} → 本卡 →
//  confirm_response{confirm_id,approved,scope}。默认策略全 off，平时不出现。
// ══════════════════════════════════════════════════
const CONFIRM_KIND = {
  shell:                   { icon: '⚙️', label: '执行 Shell 命令' },
  write_outside_workspace: { icon: '💾', label: '写入工作区以外' },
  git_push:                { icon: '🚀', label: '推送到远程仓库' },
  mcp_destructive:         { icon: '⚠️', label: '破坏性外部操作' },
};

export function showConfirmRequest(agentId, data = {}) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const { confirm_id, kind, tool, detail, risk } = data;
  if (!confirm_id) return;
  const meta = CONFIRM_KIND[kind] || { icon: '⚠️', label: kind || '危险操作' };
  const riskTag = risk === 'high' ? '高风险' : '需确认';

  const div = document.createElement('div');
  div.className = 'confirm-card';
  div.dataset.risk = risk || 'medium';
  div.dataset.confirmId = confirm_id;
  div.innerHTML = `
    <div class="confirm-hdr">
      <span class="cc-icon">${meta.icon}</span>
      <span>${escHtml(meta.label)}</span>
      <span class="cc-risk-tag">${riskTag}</span>
    </div>
    <div class="confirm-body">
      <div class="confirm-tool">${AGENTS[agentId]?.name || agentId} 想调用 <b>${escHtml(tool || '')}</b></div>
      ${detail ? `<div class="confirm-detail">${escHtml(detail)}</div>` : ''}
    </div>
    <div class="confirm-actions">
      <button class="confirm-btn cc-allow cc-primary" onclick="resolveConfirm('${agentId}','${confirm_id}',true,'once',this)">允许一次</button>
      <button class="confirm-btn cc-allow" onclick="resolveConfirm('${agentId}','${confirm_id}',true,'session',this)">本会话允许</button>
      <button class="confirm-btn cc-allow" onclick="resolveConfirm('${agentId}','${confirm_id}',true,'always',this)">永久允许</button>
      <button class="confirm-btn cc-deny" onclick="resolveConfirm('${agentId}','${confirm_id}',false,'once',this)">拒绝</button>
    </div>
    <div class="confirm-result"></div>`;
  box.appendChild(div);
  scrollBottom(agentId);
}
window.showConfirmRequest = showConfirmRequest;

window.resolveConfirm = function(agentId, confirmId, approved, scope, btn) {
  const card = btn?.closest('.confirm-card')
            || document.querySelector(`#messages-${agentId} .confirm-card[data-confirm-id="${confirmId}"]`);
  // 防重复点击：先锁住所有按钮
  card?.querySelectorAll('.confirm-btn').forEach(b => { b.disabled = true; });

  const sent = wsSend(agentId, {
    action: 'confirm_response', confirm_id: confirmId,
    approved, scope,
  });
  if (!sent) {
    card?.querySelectorAll('.confirm-btn').forEach(b => { b.disabled = false; });
    toast('未连接后端，确认未送达', 'error');
    return;
  }

  if (card) {
    card.classList.add('cc-resolved');
    const res = card.querySelector('.confirm-result');
    if (res) {
      const scopeTxt = scope === 'session' ? '（本会话）' : scope === 'always' ? '（永久）' : '';
      res.className = 'confirm-result ' + (approved ? 'cc-approved' : 'cc-denied');
      res.textContent = approved ? `✓ 已允许${scopeTxt}` : '✕ 已拒绝';
    }
  }
};

// ── C2: ask_user 问题卡片 ────────────────────────
export function showAskUserCard(agentId, msg) {
  const box = document.getElementById(`messages-${agentId}`);
  if (!box) return;
  const question = msg.question || '（问题）';
  const choices = msg.choices || [];

  const div = document.createElement('div');
  div.className = 'ask-user-card';
  const choicesBtns = choices.length
    ? choices.map(c => `<button class="au-choice-btn" onclick="answerAskUser('${agentId}',this,'${escHtml(c)}')">${escHtml(c)}</button>`).join('')
    : '';
  div.innerHTML = `
    <div class="au-hdr">💬 Anima 想问你</div>
    <div class="au-question">${escHtml(question)}</div>
    ${choicesBtns ? `<div class="au-choices">${choicesBtns}</div>` : ''}
    <div class="au-input-row">
      <input class="au-input" type="text" placeholder="输入回答…" onkeydown="if(event.key==='Enter')answerAskUser('${agentId}',this)">
      <button class="au-send-btn" onclick="answerAskUser('${agentId}',this.previousElementSibling)">发送</button>
    </div>
    <div class="au-result"></div>`;
  box.appendChild(div);
  scrollBottom(agentId);
  div.querySelector('.au-input')?.focus();
}
window.showAskUserCard = showAskUserCard;

window.answerAskUser = function(agentId, el, choiceText) {
  const card = el?.closest('.ask-user-card');
  const answer = choiceText || card?.querySelector('.au-input')?.value?.trim() || '';
  if (!answer) { toast('请输入回答', 'error'); return; }
  const sent = wsSend(agentId, { action: 'user_answer', answer });
  if (!sent) { toast('未连接后端', 'error'); return; }
  if (card) {
    card.classList.add('au-answered');
    card.querySelectorAll('.au-choice-btn, .au-send-btn').forEach(b => { b.disabled = true; });
    const input = card.querySelector('.au-input');
    if (input) input.disabled = true;
    const res = card.querySelector('.au-result');
    if (res) { res.textContent = `✓ 已回答：${answer}`; res.className = 'au-result au-done'; }
  }
};

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
      <div class="thinking-live-steps" style="display:none"></div>
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
  stepsEl.style.display = 'flex';

  const item = document.createElement('div');
  item.className = 'thinking-step-item running';
  item.dataset.tool = tool;

  // M-P2：delegate 不展示子员工独立身份，而是显示"她正在调用 XX 能力"
  // 角标（沿用该能力的主题色），任务派给谁对用户透明但不割裂"她"的统一身份。
  if (tool === 'delegate') {
    const cap = DELEGATE_CAPS[args?.role] || { name: args?.role || '子员工', icon:'🤝', cls:'' };
    const taskPreview = args?.task ? String(args.task).slice(0, 36) : '';
    item.classList.add('delegate-step');
    item.innerHTML = `
      <span class="ts-icon">${cap.icon}</span>
      <span class="ts-name">她正在调用<span class="delegate-badge ${cap.cls}">${escHtml(cap.name)}</span>能力</span>
      ${taskPreview ? `<span class="ts-arg">${escHtml(taskPreview)}</span>` : ''}
      <span class="ts-spin">⟳</span>`;
    stepsEl.appendChild(item);
    scrollBottom(agentId);
    return;
  }

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

  item.innerHTML = `
    <span class="ts-icon">${icon}</span>
    <span class="ts-name">${escHtml(tool)}</span>
    ${argSummary ? `<span class="ts-arg">${escHtml(argSummary)}</span>` : ''}
    <span class="ts-spin">⟳</span>`;
  stepsEl.appendChild(item);
  scrollBottom(agentId);
}
window.addThinkingStep = addThinkingStep;

export function markThinkingStep(agentId, tool, ok, hint, data) {
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
  if (ok && data) {
    let detail = '';
    if (data.file) {
      const short = String(data.file).split(/[/\\]/).slice(-2).join('/');
      detail = short;
    } else if (data.files_committed) {
      detail = `${data.files_committed} 个文件`;
    } else if (data.task_status) {
      detail = data.task_status;
    }
    if (detail) {
      const tag = document.createElement('span');
      tag.className = 'ts-file-tag';
      tag.textContent = detail;
      item.appendChild(tag);
    }
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
  const stopBtn = document.getElementById(`stop-${agentId}`);
  if (inp) inp.disabled = disabled;
  if (agentId === 'xi') {
    if (btn) btn.style.display = disabled ? 'none' : 'flex';
    if (stopBtn) stopBtn.style.display = disabled ? 'flex' : 'none';
  }
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

// 事件委托：历史列表点击（只注册一次，innerHTML 刷新后仍有效）
document.addEventListener('click', (e) => {
  // 点击删除按钮（或其内部 SVG）
  const delBtn = e.target.closest('[data-delete-id]');
  if (delBtn) {
    e.stopPropagation();
    window.deleteSession(delBtn.dataset.deleteId);
    return;
  }
  // 点击历史条目打开会话
  const item = e.target.closest('.history-item[data-session-id]');
  if (item && !e.target.closest('[data-delete-id]')) {
    window.openSession(item.dataset.sessionId, item.dataset.agent);
  }
});

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
      html += `<div class="history-item" data-session-id="${s.session_id}" data-agent="${s.agent}">
        <span class="history-item-text">${escHtml(sum)}</span>
        <button class="history-delete-btn" data-delete-id="${s.session_id}" title="删除">
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="1" y1="1" x2="11" y2="11"/><line x1="11" y1="1" x2="1" y2="11"/></svg>
        </button>
      </div>`;
    }
    html += '</div>';
  }
  container.innerHTML = html;
}

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

window.deleteSession = async function(sessionId) {
  // 乐观更新：立即淡出条目，给即时视觉反馈
  const el = document.querySelector(`.history-item[data-session-id="${sessionId}"]`);
  if (el) { el.style.opacity = '0.3'; el.style.pointerEvents = 'none'; }
  try {
    const resp = await fetch(`${CONFIG.api}/sessions/${sessionId}`, CONFIG.fetchOpts({ method: 'DELETE' }));
    if (!resp.ok) toast('删除失败（' + resp.status + '）', 'error');
  } catch(_) {
    toast('删除失败：后端未响应', 'error');
  }
  await loadSidebarHistory();
};

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

// ══════════════════════════════════════════════════
//  / Skill 快捷唤起面板
// ══════════════════════════════════════════════════

let _skillCache = null;

async function _getSkills() {
  if (_skillCache) return _skillCache;
  try {
    const d = await fetch(`${CONFIG.api}/skills`, CONFIG.fetchOpts()).then(r => r.json());
    _skillCache = (d.skills || []).filter(s => s.name && !s.locked);
  } catch(_) { _skillCache = []; }
  return _skillCache;
}

function _getPanel() { return document.getElementById('skill-slash-panel'); }

function _closePanel() {
  const p = _getPanel();
  if (p) { p.classList.remove('visible'); p.innerHTML = ''; }
}

async function _openPanel(agentId, query) {
  let panel = _getPanel();
  if (!panel) return;

  const skills = await _getSkills();
  const q = query.toLowerCase();
  const filtered = q
    ? skills.filter(s => s.name.toLowerCase().includes(q) || (s.category||'').toLowerCase().includes(q) || (s.tags||[]).some(t => t.toLowerCase().includes(q)))
    : skills;

  if (!filtered.length) { _closePanel(); return; }

  panel.innerHTML = filtered.slice(0, 12).map((s, i) =>
    `<div class="skill-slash-item${i===0?' active':''}" data-id="${s.id}" data-name="${escHtml(s.name)}" onclick="skillSlashSelect('${agentId}','${s.id}')">
      <span class="ssi-icon">${s.icon||'✦'}</span>
      <div class="ssi-body">
        <div class="ssi-name">${escHtml(s.name)}</div>
        <div class="ssi-desc">${escHtml((s.description||'').slice(0,48))}…</div>
      </div>
      <span class="ssi-cat">${escHtml(s.category||'')}</span>
    </div>`
  ).join('');
  panel.classList.add('visible');
}

// 键盘导航
function _panelNav(e) {
  const panel = _getPanel();
  if (!panel || !panel.classList.contains('visible')) return false;
  const items = [...panel.querySelectorAll('.skill-slash-item')];
  const cur = items.findIndex(el => el.classList.contains('active'));
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    items[cur]?.classList.remove('active');
    items[Math.min(cur+1, items.length-1)]?.classList.add('active');
    return true;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    items[cur]?.classList.remove('active');
    items[Math.max(cur-1, 0)]?.classList.add('active');
    return true;
  }
  if (e.key === 'Enter') {
    const active = panel.querySelector('.skill-slash-item.active');
    if (active) { e.preventDefault(); active.click(); return true; }
  }
  if (e.key === 'Escape') { _closePanel(); return true; }
  return false;
}

// 输入监听
function _onComposerInput(agentId) {
  const inp = document.getElementById(`input-${agentId}`);
  if (!inp) return;
  const val = inp.value;
  if (val.startsWith('/')) {
    _openPanel(agentId, val.slice(1).trim());
  } else {
    _closePanel();
  }
}

// 选中 skill
window.skillSlashSelect = function(agentId, skillId) {
  _skillCache = _skillCache || [];
  const skill = _skillCache.find(s => s.id === skillId);
  if (!skill) { _closePanel(); return; }
  const inp = document.getElementById(`input-${agentId}`);
  if (inp) {
    // 填入 "@skill 名称 " 作为提示词前缀，用户可以继续输入任务
    inp.value = `[${skill.name}] `;
    inp.focus();
    window.autoResize(inp);
    updateSendBtn(agentId);
    // 把 skill 的 system_prompt 存起来，发送时附加
    inp.dataset.skillId = skillId;
    inp.dataset.skillPrompt = skill.system_prompt || '';
    inp.dataset.skillName = skill.name;
  }
  _closePanel();
  toast(`✦ 已选择 Skill：${skill.name}`, 'success');
};

// 挂载：在 textarea oninput 里额外调用
window._slashPanelInput = _onComposerInput;
window._slashPanelKey   = _panelNav;
window._closeSlashPanel = _closePanel;
