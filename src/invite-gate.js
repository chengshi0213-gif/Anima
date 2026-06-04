/**
 * invite-gate.js — 结缘码门
 * 在主界面加载前拦截：未激活的设备必须输入有效邀请码才能进入。
 * 已激活设备（或后端离线 / 未配置 Supabase）自动放行，不挡老用户。
 *
 * 后端接口（routes/invite.py）：
 *   GET  /invite/check     → { activated: bool }
 *   POST /invite/verify    → { ok, reason }     预校验，不消耗
 *   POST /invite/activate  → { ok, reason, lingxi }
 */
import { CONFIG, toast } from './state.js';

let _gateResolve = null;

function _err(msg) {
  const el = document.getElementById('inviteErr');
  if (el) el.textContent = msg || '';
}

function _hint(msg, ok) {
  const el = document.getElementById('inviteHint');
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = ok ? 'var(--accent, #7c9cff)' : 'var(--muted, #888)';
}

// reason → 中文文案
const _REASON_TEXT = {
  valid:            '✓ 这枚结缘码有效，可以进入',
  not_found:        '没有找到这枚结缘码，请检查输入',
  used:             '这枚结缘码已经被使用过了',
  expired:          '这枚结缘码已过期',
  empty_code:       '请输入结缘码',
  already_activated:'这台设备已经结缘，直接进入即可',
  not_configured:   '',   // 后端未配置 Supabase — 静默放行
};

// 启动门控：返回 Promise，激活通过后 resolve
window.runInviteGate = function () {
  return new Promise(async (resolve) => {
    // 1. 后端检查设备是否已激活
    let activated = true;   // 默认放行（后端离线/未配置不挡人）
    try {
      const r = await fetch(`${CONFIG.api}/invite/check`);
      const d = await r.json();
      activated = !!d.activated;
    } catch (_) {
      resolve();   // 后端离线 → 不阻塞
      return;
    }
    if (activated) { resolve(); return; }

    // 2. 未激活 → 显示结缘码门
    const overlay = document.getElementById('inviteOverlay');
    if (!overlay) { resolve(); return; }   // 容错：没有 DOM 也不挡人
    _gateResolve = resolve;
    _err(''); _hint('每一枚结缘码，都是一次相遇的邀请。');
    overlay.classList.remove('hidden');
    setTimeout(() => document.getElementById('inviteCodeInput')?.focus(), 80);
  });
};

function _finish() {
  document.getElementById('inviteOverlay')?.classList.add('hidden');
  const done = _gateResolve;
  _gateResolve = null;
  done && done();
}

// ── 输入框失焦时预校验（即时反馈，不消耗码）──────────────────
window.inviteVerify = async function () {
  const code = (document.getElementById('inviteCodeInput')?.value || '').trim();
  if (!code) { _hint('每一枚结缘码，都是一次相遇的邀请。'); return; }
  try {
    const r = await fetch(`${CONFIG.api}/invite/verify`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
    const d = await r.json();
    const txt = _REASON_TEXT[d.reason] ?? '';
    if (d.ok) _hint(txt, true);
    else if (txt) _hint(txt);
  } catch (_) { /* 预校验失败静默 */ }
};

// ── 提交激活 ──────────────────────────────────────────
window.inviteActivate = async function () {
  const code = (document.getElementById('inviteCodeInput')?.value || '').trim();
  if (!code) { _err('请输入结缘码'); return; }
  _err('');

  const btn = document.getElementById('inviteSubmitBtn');
  if (btn) { btn.disabled = true; btn.textContent = '正在结缘…'; }

  try {
    const r = await fetch(`${CONFIG.api}/invite/activate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
    const d = await r.json();
    if (d.ok || d.reason === 'already_activated') {
      _hint('结缘成功，欢迎来到 Anima ✨', true);
      // 被邀请人灵犀奖励由后端 activate 记录；本地入账在任务 D 接入 economy。
      setTimeout(_finish, 600);
      return;
    }
    _err(_REASON_TEXT[d.reason] || '结缘码无效，请重试');
  } catch (e) {
    _err('后端无响应，请稍后重试');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '结缘并进入 →'; }
  }
};

// ══════════════════════════════════════════════════
//  设置页「我的邀请码」面板
// ══════════════════════════════════════════════════

function _codeRow(c) {
  let tag, tagColor;
  if (c.is_used)      { tag = '已被使用'; tagColor = 'var(--muted,#888)'; }
  else if (c.expired) { tag = '已过期';   tagColor = '#e07a9c'; }
  else                { tag = '可赠送';   tagColor = 'var(--accent,#7c9cff)'; }
  const dim = (c.is_used || c.expired) ? 'opacity:.55;' : '';
  const copyBtn = (!c.is_used && !c.expired)
    ? `<button class="settings-btn" style="padding:4px 10px;font-size:12px" onclick="inviteCopy('${c.code}',this)">复制</button>`
    : '';
  return `<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-main);${dim}">
      <code style="font-size:14px;letter-spacing:1px;flex:1;font-family:monospace">${c.code}</code>
      <span style="font-size:12px;color:${tagColor}">${tag}</span>
      ${copyBtn}
    </div>`;
}

window.inviteLoadPanel = async function () {
  const list  = document.getElementById('inviteCodesList');
  const qrow  = document.getElementById('inviteQuotaRow');
  const genBtn = document.getElementById('inviteGenBtn');
  if (!list) return;
  try {
    const r = await fetch(`${CONFIG.api}/invite/my`);
    const d = await r.json();
    if (!d.ok) {
      list.innerHTML = `<div style="color:var(--muted);font-size:13px">${d.reason === 'not_configured' ? '邀请系统未配置' : '加载失败'}</div>`;
      return;
    }
    const q = d.quota || { total: 3, generated: 0, remaining: 3 };
    if (qrow) {
      qrow.innerHTML = `
        <div class="num-tile glass" style="flex:1"><div class="nt-label">配额</div><div class="nt-value">${q.total}</div></div>
        <div class="num-tile glass" style="flex:1"><div class="nt-label">已生成</div><div class="nt-value">${q.generated}</div></div>
        <div class="num-tile glass" style="flex:1"><div class="nt-label">剩余可生成</div><div class="nt-value">${q.remaining}</div></div>`;
    }
    const codes = d.codes || [];
    list.innerHTML = codes.length
      ? codes.map(_codeRow).join('')
      : '<div style="color:var(--muted);font-size:13px">还没有生成结缘码，点下方按钮生成第一枚。</div>';
    if (genBtn) {
      genBtn.disabled = q.remaining <= 0;
      genBtn.textContent = q.remaining > 0 ? `✨ 生成一枚结缘码（剩 ${q.remaining}）` : '配额已用完';
    }
  } catch (e) {
    list.innerHTML = '<div style="color:var(--muted);font-size:13px">后端无响应</div>';
  }
};

window.inviteGenerate = async function () {
  const btn  = document.getElementById('inviteGenBtn');
  const hint = document.getElementById('inviteGenHint');
  if (btn) btn.disabled = true;
  if (hint) hint.textContent = '正在生成…';
  try {
    const r = await fetch(`${CONFIG.api}/invite/generate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ n: 1 }),
    });
    const d = await r.json();
    if (d.ok && d.codes?.length) {
      if (hint) hint.textContent = `已生成 ${d.codes[0]}，可复制赠送好友。`;
    } else {
      const msg = d.reason === 'quota_exhausted' ? '配额已用完' : '生成失败，请重试';
      if (hint) hint.textContent = msg;
    }
  } catch (e) {
    if (hint) hint.textContent = '后端无响应';
  } finally {
    await window.inviteLoadPanel?.();
  }
};

// 邀请人对账：补发"邀请成功 +30"灵犀。静默执行，有新增则刷新经济面板。
window.inviteReconcile = async function () {
  try {
    const r = await fetch(`${CONFIG.api}/invite/reconcile`, { method: 'POST' });
    const d = await r.json();
    if (d.ok && d.granted_count > 0) {
      if (typeof toast === 'function') {
        toast(`🪔 ${d.granted_count} 位好友因你结缘 · +${d.newly_granted_lingxi} 灵犀`, 'success');
      }
      window.achLoad?.();   // 刷新成就/灵犀面板（若已加载）
    }
    return d;
  } catch (_) { return null; }
};

window.inviteCopy = async function (code, btn) {
  try {
    await navigator.clipboard.writeText(code);
    if (btn) { const t = btn.textContent; btn.textContent = '已复制 ✓'; setTimeout(() => btn.textContent = t, 1400); }
  } catch (_) {
    // 退化：选中文本
    if (typeof toast === 'function') toast?.('复制失败，请手动选择', 'error');
  }
};

// ══════════════════════════════════════════════════
//  邮箱管家配置（设置页 · 仅管理员）
// ══════════════════════════════════════════════════
function _mlGet(id) { return document.getElementById(id); }

window.mailerLoad = async function () {
  try {
    const r = await fetch(`${CONFIG.api}/invite/mailer`);
    const d = await r.json();
    if (!d.available || !d.config) return;
    const c = d.config;
    _mlGet('mlImapHost') && (_mlGet('mlImapHost').value = c.imap_host || '');
    _mlGet('mlImapPort') && (_mlGet('mlImapPort').value = c.imap_port || 993);
    _mlGet('mlSmtpHost') && (_mlGet('mlSmtpHost').value = c.smtp_host || '');
    _mlGet('mlSmtpPort') && (_mlGet('mlSmtpPort').value = c.smtp_port || 465);
    _mlGet('mlEmail')    && (_mlGet('mlEmail').value    = c.email || '');
    _mlGet('mlSubject')  && (_mlGet('mlSubject').value  = c.subject_filter || '结缘');
    _mlGet('mlInterval') && (_mlGet('mlInterval').value = c.poll_interval_min || 10);
    _mlGet('mlPassword') && (_mlGet('mlPassword').placeholder = c.has_password ? '已设置（留空不改）' : '授权码');
    _mlGet('mlEnabled')  && (_mlGet('mlEnabled').checked = !!c.enabled);
    const hint = _mlGet('mailerHint');
    if (hint && d.status) {
      hint.textContent = d.status.running
        ? `运行中 · 已累计发码 ${d.status.sent_total || 0} 枚` + (d.status.last_result ? ` · ${d.status.last_result}` : '')
        : '未运行';
    }
  } catch (_) {}
};

function _mlCollect() {
  return {
    imap_host: _mlGet('mlImapHost')?.value.trim(),
    imap_port: parseInt(_mlGet('mlImapPort')?.value) || 993,
    smtp_host: _mlGet('mlSmtpHost')?.value.trim(),
    smtp_port: parseInt(_mlGet('mlSmtpPort')?.value) || 465,
    email: _mlGet('mlEmail')?.value.trim(),
    password: _mlGet('mlPassword')?.value,   // 空=不改
    subject_filter: _mlGet('mlSubject')?.value.trim(),
    poll_interval_min: parseInt(_mlGet('mlInterval')?.value) || 10,
    enabled: !!_mlGet('mlEnabled')?.checked,
  };
}

window.mailerTest = async function () {
  const hint = _mlGet('mailerHint');
  if (hint) hint.textContent = '正在测试连接…';
  try {
    const r = await fetch(`${CONFIG.api}/invite/mailer/test`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_mlCollect()),
    });
    const d = await r.json();
    if (hint) { hint.textContent = d.ok ? '✓ IMAP + SMTP 登录成功' : `✗ ${d.error || '连接失败'}`; hint.style.color = d.ok ? 'var(--accent,#7c9cff)' : '#e07a9c'; }
  } catch (_) { if (hint) hint.textContent = '后端无响应'; }
};

window.mailerSave = async function () {
  const hint = _mlGet('mailerHint');
  try {
    const r = await fetch(`${CONFIG.api}/invite/mailer`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_mlCollect()),
    });
    const d = await r.json();
    if (d.ok) {
      const running = d.status?.running;
      if (hint) { hint.textContent = `已保存 · ${running ? '管家已启动' : '管家已停止'}`; hint.style.color = 'var(--accent,#7c9cff)'; }
      if (typeof toast === 'function') toast('邮箱管家配置已保存', 'success');
      window.mailerLoad?.();
    } else if (hint) { hint.textContent = d.error || '保存失败'; }
  } catch (_) { if (hint) hint.textContent = '后端无响应'; }
};

window.mailerPollNow = async function () {
  const hint = _mlGet('mailerHint');
  if (hint) hint.textContent = '正在收取…';
  try {
    const r = await fetch(`${CONFIG.api}/invite/mailer/poll`, { method: 'POST' });
    const d = await r.json();
    if (hint) hint.textContent = d.ok ? `收取完成：发现 ${d.found ?? 0} 封，新发 ${d.sent ?? 0} 枚码` : (d.error || '收取失败');
  } catch (_) { if (hint) hint.textContent = '后端无响应'; }
};

// ══════════════════════════════════════════════════
//  注册数据看板（设置页 · 仅管理员）
// ══════════════════════════════════════════════════
function _shortTok(t) {
  if (!t) return '—';
  if (t === 'admin') return 'admin';
  return t.length > 12 ? t.slice(0, 8) + '…' + t.slice(-3) : t;
}

window.inviteStatsLoad = async function () {
  const body = document.getElementById('inviteStatsBody');
  if (!body) return;
  body.innerHTML = '<div style="color:var(--muted);font-size:13px">加载中…</div>';
  try {
    const d = await fetch(`${CONFIG.api}/invite/stats`).then(r => r.json());
    if (!d.ok) { body.innerHTML = `<div style="color:var(--muted);font-size:13px">${d.reason === 'not_configured' ? '邀请系统未配置' : '加载失败'}</div>`; return; }

    // 顶部数字
    const tiles = `<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
      <div class="num-tile glass" style="flex:1;min-width:120px"><div class="nt-label">总激活</div><div class="nt-value">${d.total_activations || 0}</div></div>
      <div class="num-tile glass" style="flex:1;min-width:120px"><div class="nt-label">已发码</div><div class="nt-value">${d.total_codes || 0}</div></div>
      <div class="num-tile glass" style="flex:1;min-width:120px"><div class="nt-label">已使用</div><div class="nt-value">${d.used_codes || 0}</div></div>
      <div class="num-tile glass" style="flex:1;min-width:120px"><div class="nt-label">待使用</div><div class="nt-value">${d.unused_codes || 0}</div></div>
    </div>`;

    // 近 30 天柱状图（纯 div）
    const days = d.by_day || [];
    const maxC = Math.max(1, ...days.map(x => x.count));
    const bars = days.map(x => {
      const h = Math.round((x.count / maxC) * 100);
      const title = `${x.date}：${x.count} 激活`;
      return `<div title="${title}" style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%">
        <div style="width:70%;height:${Math.max(2, h)}%;background:linear-gradient(180deg,var(--accent,#7c9cff),#5b8def);border-radius:3px 3px 0 0;min-height:2px"></div>
      </div>`;
    }).join('');
    const chart = `<div style="margin-bottom:6px;font-size:13px;color:var(--muted)">近 30 天激活曲线</div>
      <div style="display:flex;align-items:flex-end;gap:2px;height:90px;padding:4px;border:1px solid var(--border);border-radius:8px;background:var(--bg-main);margin-bottom:16px">${bars || '<div style="color:var(--muted);font-size:12px;margin:auto">暂无数据</div>'}</div>`;

    // 邀请人排名
    const top = d.top_inviters || [];
    const rank = top.length
      ? `<div style="margin-bottom:6px;font-size:13px;color:var(--muted)">邀请人排名</div>
         <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:16px">${top.map((t, i) =>
           `<div style="display:flex;align-items:center;gap:10px;padding:6px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg-main)">
              <span style="font-size:14px;width:22px;text-align:center">${['🥇','🥈','🥉'][i] || (i + 1)}</span>
              <code style="flex:1;font-size:12px;font-family:monospace">${_shortTok(t.user_token)}</code>
              <span style="font-size:13px;color:var(--accent,#7c9cff)">${t.count} 人</span>
            </div>`).join('')}</div>`
      : '<div style="color:var(--muted);font-size:13px;margin-bottom:16px">还没有用户成功邀请他人</div>';

    // 最近激活
    const recent = (d.recent || []).slice(0, 8);
    const recentHtml = recent.length
      ? `<div style="margin-bottom:6px;font-size:13px;color:var(--muted)">最近激活</div>
         <div style="display:flex;flex-direction:column;gap:4px">${recent.map(a =>
           `<div style="display:flex;gap:10px;font-size:12px;color:var(--muted);padding:4px 8px">
              <span style="font-family:monospace">${(a.activated_at || '').slice(0, 16).replace('T', ' ')}</span>
              <code>${a.invite_code || ''}</code>
              <span style="margin-left:auto">引荐人 ${_shortTok(a.referrer)}</span>
            </div>`).join('')}</div>`
      : '';

    body.innerHTML = tiles + chart + rank + recentHtml;
  } catch (e) {
    body.innerHTML = '<div style="color:var(--muted);font-size:13px">后端无响应</div>';
  }
};
