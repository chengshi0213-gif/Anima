/**
 * Anima — ws.js
 * WebSocket 管理、后端健康检查、Agent 消息处理
 */
import { CONFIG, AGENTS, wsConns, wsStatus, chatState, runtime, toast } from './state.js';

// ══════════════════════════════════════════════════
//  后端健康检查
// ══════════════════════════════════════════════════
export async function checkBackend(forceRetry = false) {
  const dot  = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  dot.className = 'status-dot loading';
  text.textContent = '连接中…';

  let healthData = null;

  // ── 优先：通过 Tauri IPC（原生 TcpStream）直接访问后端 ──
  try {
    const invoke = window.__TAURI__?.core?.invoke;
    if (invoke) {
      const body = await invoke('health_check');
      healthData = JSON.parse(body);
    }
  } catch (_tauriErr) {}

  // ── 回退：直接 fetch ──
  if (!healthData) {
    try {
      const _ctrl = new AbortController();
      const _tid  = setTimeout(() => _ctrl.abort(), 4000);
      const r = await fetch(`${CONFIG.api}/health`, { signal: _ctrl.signal }).finally(() => clearTimeout(_tid));
      if (r.ok) healthData = await r.json().catch(() => ({}));
    } catch (_fetchErr) {}
  }

  if (healthData) {
    if (healthData.local_token) {
      localStorage.setItem('anima_local_token', healthData.local_token);
      CONFIG.token = healthData.local_token;
    }
    dot.className  = 'status-dot online';
    text.textContent = '已连接';
    document.getElementById('offlineOverlay')?.classList.add('hidden');
    if (!runtime.backendOnline) {
      runtime.backendOnline = true;
      initAllWS();
      window.loadOverview?.();
      window.loadSidebarHistory?.();
      setTimeout(() => window.projectSwitcherLoad?.(), 1200);
    }
    return true;
  }

  dot.className  = 'status-dot error';
  text.textContent = '后端离线';
  runtime.backendOnline = false;
  if (forceRetry) toast('无法连接后端，请检查服务是否启动', 'error');
  return false;
}
window.checkBackend = checkBackend;

// ══════════════════════════════════════════════════
//  WebSocket 管理
// ══════════════════════════════════════════════════
export function initAllWS() {
  for (const id of Object.keys(AGENTS)) initAgentWS(id);
}

export function initAgentWS(agentId) {
  if (wsConns[agentId] && wsConns[agentId].readyState < WebSocket.CLOSING) return;
  const ws = new WebSocket(`${CONFIG.wsBase}/ws/${agentId}`);
  wsConns[agentId] = ws;
  ws.onopen = () => {
    wsStatus[agentId].connected = true;
    ws.send(JSON.stringify({ action:'status' }));
    if (document.getElementById('tab-overview')?.classList.contains('active')) window.loadOverview?.();
  };
  ws.onmessage = (e) => {
    try { handleAgentMessage(agentId, JSON.parse(e.data)); } catch(_) {}
  };
  ws.onclose = () => {
    wsStatus[agentId].connected = false;
    window.updateAgentUI?.(agentId);
    if (runtime.backendOnline) setTimeout(() => initAgentWS(agentId), 3000);
  };
  ws.onerror = () => {};
}

export function wsSend(agentId, data) {
  const ws = wsConns[agentId];
  if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(data)); return true; }
  return false;
}
window.wsSend = wsSend;

// ══════════════════════════════════════════════════
//  Agent 消息处理
// ══════════════════════════════════════════════════
function handleAgentMessage(agentId, msg) {
  if (msg.type === 'response' && msg.data?.agent !== undefined) {
    Object.assign(wsStatus[agentId], { model: msg.data.model||'-', tools: msg.data.tools||0, busy: msg.data.busy||false });
    window.updateAgentUI?.(agentId);
    return;
  }
  if (msg.type === 'status' && msg.status === 'running') {
    chatState[agentId].pending   = true;
    chatState[agentId].sessionId = msg.session_id;
    wsStatus[agentId].busy       = true;
    window.setInputState?.(agentId, true);
    window.updateAgentUI?.(agentId);
    window.showThinking?.(agentId);
    return;
  }
  if (msg.type === 'assistant_delta') {
    window.appendAssistantDelta?.(agentId, msg.data?.content || '');
    return;
  }
  if (msg.type === 'response' && msg.data?.status) {
    window.removeThinking?.(agentId);
    // upgrade-in-place：流式气泡不销毁，直接渲染最终内容（零闪烁）
    window.finalizeStreamingMsg?.(agentId, msg.data);
    chatState[agentId].pending = false;
    wsStatus[agentId].busy     = false;
    window.setInputState?.(agentId, false);
    window.updateAgentUI?.(agentId);
    toast(`${AGENTS[agentId].icon} ${AGENTS[agentId].name} 已回复`, 'success');
    window.loadSidebarHistory?.();
    return;
  }
  if (msg.type === 'tool_start') {
    window.addThinkingStep?.(agentId, msg.data?.tool, msg.data?.args, msg.data?.turn);
    return;
  }
  if (msg.type === 'tool_done') {
    window.markThinkingStep?.(agentId, msg.data?.tool, msg.data?.ok, msg.data?.hint, msg.data);
    return;
  }
  if (msg.type === 'confirm_request') {
    // M14 内核3：危险操作确认。后端默认策略全 off，故平时不触发；
    // 用户在 config 开 ask 后，这里渲染 ConfirmCard 让其决定放行/拒绝。
    window.showConfirmRequest?.(agentId, msg.data);
    return;
  }
  if (msg.type === 'permission_request') {
    window.removeThinking?.(agentId);
    window.removeStreamingMsg?.(agentId);
    chatState[agentId].pending = false;
    wsStatus[agentId].busy     = false;
    window.setInputState?.(agentId, false);
    window.updateAgentUI?.(agentId);
    window.showPermissionRequest?.(agentId, msg.data);
    return;
  }
  if (msg.type === 'error') {
    window.removeThinking?.(agentId);
    window.removeStreamingMsg?.(agentId);
    chatState[agentId].pending = false;
    wsStatus[agentId].busy     = false;
    window.setInputState?.(agentId, false);
    window.updateAgentUI?.(agentId);
    window.appendErrMsg?.(agentId, msg.message || '未知错误');
    toast(msg.message || '出错了', 'error');
  }
}
