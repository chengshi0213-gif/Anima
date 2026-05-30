/**
 * auth.js — 本地密码登录门控
 * 在主界面加载前拦截：首次设置密码 / 返回登录 / 忘记密码重置。
 * 纯本地校验，离线可用。后端离线时自动跳过（不把用户锁在门外）。
 */
import { CONFIG } from './state.js';

let _authResolve = null;

function _show(mode) {
  ['login', 'setup', 'reset'].forEach(m => {
    document.getElementById(`authMode-${m}`)?.classList.toggle('hidden', m !== mode);
  });
  // 自动聚焦首个输入框
  const first = document.querySelector(`#authMode-${mode} input`);
  setTimeout(() => first?.focus(), 60);
}

function _err(id, msg) {
  const el = document.getElementById(id);
  if (el) el.textContent = msg || '';
}

// 启动门控：返回 Promise，认证通过后 resolve
window.runAuthGate = function () {
  return new Promise(async (resolve) => {
    let status;
    try {
      const r = await fetch(`${CONFIG.api}/auth/status`);
      status = await r.json();
    } catch (_) {
      resolve(); // 后端离线 → 不阻塞
      return;
    }
    const overlay = document.getElementById('authOverlay');
    if (!overlay) { resolve(); return; }
    _authResolve = resolve;
    _show(status.password_set ? 'login' : 'setup');
    overlay.classList.remove('hidden');
  });
};

function _finish() {
  document.getElementById('authOverlay')?.classList.add('hidden');
  const done = _authResolve;
  _authResolve = null;
  done && done();
}

// ── 登录 ──────────────────────────────────────────────
window.authLogin = async function () {
  const pwd = document.getElementById('authLoginPwd')?.value || '';
  if (!pwd) { _err('authLoginErr', '请输入密码'); return; }
  _err('authLoginErr', '');
  try {
    const r = await fetch(`${CONFIG.api}/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd }),
    });
    const d = await r.json();
    if (d.ok) { _finish(); return; }
    _err('authLoginErr', d.error || '密码错误');
  } catch (e) {
    _err('authLoginErr', '后端无响应');
  }
};

// ── 首次设置 ──────────────────────────────────────────
window.authSetup = async function () {
  const pwd = document.getElementById('authSetupPwd')?.value || '';
  const cf = document.getElementById('authSetupConfirm')?.value || '';
  if (pwd.length < 4) { _err('authSetupErr', '密码至少 4 位'); return; }
  if (pwd !== cf) { _err('authSetupErr', '两次输入不一致'); return; }
  _err('authSetupErr', '');

  const birth = {
    date: document.getElementById('authBirthDate')?.value || '',
    time: document.getElementById('authBirthTime')?.value || '',
    place: document.getElementById('authBirthPlace')?.value.trim() || '',
    gender: document.getElementById('authBirthGender')?.value || '',
    calendar: document.getElementById('authBirthCal')?.value || 'solar',
  };
  try {
    const r = await fetch(`${CONFIG.api}/auth/setup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd, confirm: cf, birth }),
    });
    const d = await r.json();
    if (d.ok) { _finish(); return; }
    _err('authSetupErr', d.error || '设置失败');
  } catch (e) {
    _err('authSetupErr', '后端无响应');
  }
};

// ── 忘记密码 / 重置 ───────────────────────────────────
window.authShowReset = function () { _err('authResetErr', ''); _show('reset'); };
window.authBackToLogin = function () { _err('authLoginErr', ''); _show('login'); };

window.authReset = async function () {
  const code = document.getElementById('authResetCode')?.value.trim() || '';
  const pwd = document.getElementById('authResetPwd')?.value || '';
  if (!code) { _err('authResetErr', '请输入激活码'); return; }
  if (pwd.length < 4) { _err('authResetErr', '新密码至少 4 位'); return; }
  _err('authResetErr', '');
  try {
    const r = await fetch(`${CONFIG.api}/auth/reset`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, password: pwd }),
    });
    const d = await r.json();
    if (d.ok) {
      // 重置成功后直接登录
      _finish();
      return;
    }
    _err('authResetErr', d.error || '激活码无效');
  } catch (e) {
    _err('authResetErr', '后端无响应');
  }
};
