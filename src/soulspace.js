/**
 * soulspace.js — M6 灵魂空间
 * 密码门（复用 /auth/login 二次验证）+ 三室：
 *   我的命盘 · 她记得的我 · 我们的时刻
 */
import { CONFIG, escHtml, toast, markdownToHtml } from './state.js?v=1.2.1';

let _unlocked = false;

function _setErr(id, msg) {
  const el = document.getElementById(id);
  if (el) el.textContent = msg || '';
}

function _fmtDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso.replace(' ', 'T'));
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// ══════════════════════════════════════════════════
//  密码门
// ══════════════════════════════════════════════════
window.soulUnlock = async function () {
  const pwdEl = document.getElementById('soulGatePwd');
  const pwd = pwdEl?.value || '';
  if (!pwd) { _setErr('soulGateErr', '请输入密码'); return; }
  _setErr('soulGateErr', '');
  try {
    const r = await fetch(`${CONFIG.api}/auth/login`, CONFIG.fetchOpts({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd }),
    }));
    const d = await r.json();
    if (d.ok) {
      _unlocked = true;
      if (pwdEl) pwdEl.value = '';
      document.getElementById('soulGate')?.classList.add('hidden');
      document.getElementById('soulContent')?.classList.remove('hidden');
      window.soulShowRoom('chart');
      return;
    }
    _setErr('soulGateErr', d.error || '密码错误');
  } catch (e) {
    _setErr('soulGateErr', '后端无响应，请检查 Anima 是否已启动');
  }
};

// ══════════════════════════════════════════════════
//  三室切换
// ══════════════════════════════════════════════════
window.soulShowRoom = function (roomId, el) {
  document.querySelectorAll('.soul-room').forEach(r => r.classList.remove('active'));
  document.querySelectorAll('.soul-room-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`soulRoom-${roomId}`)?.classList.add('active');
  if (el) el.classList.add('active');
  else document.querySelector(`.soul-room-tab[data-room="${roomId}"]`)?.classList.add('active');

  if (roomId === 'chart')   window.soulLoadChart();
  if (roomId === 'profile') window.soulLoadProfile();
  if (roomId === 'moments') window.soulLoadMoments();
};

// ══════════════════════════════════════════════════
//  室一：我的命盘
// ══════════════════════════════════════════════════
window.soulLoadToday = async function () {
  const el = document.getElementById('soulToday');
  if (!el) return;
  try {
    const data = await fetch(`${CONFIG.api}/divination/today`, CONFIG.fetchOpts()).then(r => r.json());
    if (data.ok && data.fortune && window.Mingli) {
      window.Mingli.mountToday(el, data.fortune, { night: document.body.classList.contains('dark') });
    }
  } catch (e) { /* 今日运势失败不阻塞命盘室 */ }
};

window.soulLoadChart = async function () {
  window.soulLoadToday();
  const birthEl = document.getElementById('soulBirthInfo');
  if (birthEl) {
    birthEl.innerHTML = '加载中…';
    try {
      const { birth } = await fetch(`${CONFIG.api}/auth/birth`, CONFIG.fetchOpts()).then(r => r.json());
      if (birth?.date) {
        const CAL    = { solar: '公历', lunar: '农历' };
        const GENDER = { male: '男', female: '女' };
        birthEl.innerHTML = `
          <div class="soul-birth-row"><span>出生日期</span><b>${escHtml(birth.date)}</b></div>
          <div class="soul-birth-row"><span>出生时辰</span><b>${escHtml(birth.time || '未提供')}</b></div>
          <div class="soul-birth-row"><span>历法</span><b>${CAL[birth.calendar] || '公历'}</b></div>
          <div class="soul-birth-row"><span>性别</span><b>${GENDER[birth.gender] || '未填'}</b></div>
          <div class="soul-birth-row"><span>出生地</span><b>${escHtml(birth.place || '未提供')}</b></div>
        `;
      } else {
        birthEl.innerHTML = '<div class="soul-empty">还没有存档出生信息，去「设置」补全后即可排盘。</div>';
      }
    } catch (e) {
      birthEl.innerHTML = `<div class="soul-empty">${escHtml(e.message)}</div>`;
    }
  }
  await window.soulLoadChartHistory();
};

window.soulPaipan = async function () {
  const btn = document.getElementById('soulPaipanBtn');
  const resultEl = document.getElementById('soulChartResult');
  if (btn) { btn.disabled = true; btn.textContent = '排盘中…'; }
  try {
    const data = await fetch(`${CONFIG.api}/divination/paipan`, CONFIG.fetchOpts({ method: 'POST' })).then(r => r.json());
    if (data.ok) {
      if (resultEl) {
        // 优先渲染可导航卡面（点卡片→详情）；后端旧版无 chart 时降级回 markdown
        if (data.chart && window.Mingli && window.Mingli.mountSurface) {
          window.Mingli.mountSurface(resultEl, { chart: data.chart }, { night: document.body.classList.contains('dark') });
        } else if (data.chart && window.Mingli) {
          window.Mingli.mountPoster(resultEl, data.chart, { night: document.body.classList.contains('dark') });
        } else {
          resultEl.innerHTML = `<div class="soul-chart-md msg-bubble">${markdownToHtml(data.record.markdown)}</div>`;
        }
      }
      toast('排好了，已存入历史', 'success');
      window.soulLoadChartHistory();
    } else {
      toast(data.error || '排盘失败', 'error');
    }
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔮 重新排一次'; }
  }
};

window.soulLoadChartHistory = async function () {
  const histEl = document.getElementById('soulChartHistory');
  if (!histEl) return;
  histEl.innerHTML = '加载中…';
  try {
    const { records } = await fetch(`${CONFIG.api}/divination/history?limit=20`, CONFIG.fetchOpts()).then(r => r.json());
    if (!records?.length) {
      histEl.innerHTML = '<div class="soul-empty">还没有排盘记录，点上面「重新排一次」试试。</div>';
      return;
    }
    histEl.innerHTML = records.map(r => `
      <details class="soul-history-item" data-id="${r.id}">
        <summary>
          <span>${_fmtDateTime(r.created_at)}</span>
          <button class="mem-del-btn" onclick="event.preventDefault();soulDeleteChartHistory('${r.id}',this)" title="删除这条记录">🗑</button>
        </summary>
        <div class="soul-chart-md msg-bubble">${markdownToHtml(r.markdown)}</div>
      </details>`).join('');
  } catch (e) {
    histEl.innerHTML = `<div class="soul-empty">${escHtml(e.message)}</div>`;
  }
};

window.soulDeleteChartHistory = async function (id, btn) {
  try {
    const data = await fetch(`${CONFIG.api}/divination/history/${id}`, CONFIG.fetchOpts({ method: 'DELETE' })).then(r => r.json());
    if (data.ok) {
      btn.closest('.soul-history-item')?.remove();
      toast('已删除', 'success');
    } else {
      toast(data.message || '删除失败', 'error');
    }
  } catch (e) { toast(e.message, 'error'); }
};

// ══════════════════════════════════════════════════
//  室二：她记得的我（L2 画像，MVP：查看 + 删除）
// ══════════════════════════════════════════════════
const L2_SOURCE_SEP = '｜来源：';

window.soulLoadProfile = async function () {
  const el = document.getElementById('soulProfileList');
  if (!el) return;
  el.innerHTML = '加载中…';
  try {
    const entries = await fetch(`${CONFIG.api}/memory/entries?agent=xi&limit=200`, CONFIG.fetchOpts()).then(r => r.json());
    const byId = new Map(entries.map(e => [e.id, e]));
    const l2 = entries.filter(e => e.category === 'L2');
    if (!l2.length) {
      el.innerHTML = '<div class="soul-empty">她还没有沉淀出关于你的画像 —— 再聊聊，慢慢就有了。</div>';
      return;
    }
    el.innerHTML = l2.map(e => {
      const [text, srcStr] = (e.value || '').split(L2_SOURCE_SEP);
      const sources = (srcStr || '').split(',').map(s => s.trim()).filter(Boolean)
        .map(id => byId.get(id)).filter(Boolean);
      const sourcesHtml = sources.length
        ? `<div class="soul-l2-sources">来源：${sources.map(s => `<span class="soul-l2-source-tag" title="${escHtml(s.value)}">${escHtml(s.key)}</span>`).join('')}</div>`
        : '';
      return `
        <div class="soul-l2-row" data-id="${e.id}">
          <div class="soul-l2-main">
            <div class="soul-l2-key">${escHtml(e.key)}</div>
            <div class="soul-l2-text">${escHtml(text)}</div>
            ${sourcesHtml}
          </div>
          <button class="mem-del-btn" onclick="soulDeleteL2('${e.id}',this)" title="删除这条画像">🗑</button>
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="soul-empty">${escHtml(e.message)}</div>`;
  }
};

window.soulDeleteL2 = async function (id, btn) {
  try {
    const data = await fetch(`${CONFIG.api}/memory/entries/${id}`, CONFIG.fetchOpts({ method: 'DELETE' })).then(r => r.json());
    if (data.ok) {
      btn.closest('.soul-l2-row')?.remove();
      toast('已删除，下周会重新生成', 'success');
    } else {
      toast(data.message || '删除失败', 'error');
    }
  } catch (e) { toast(e.message, 'error'); }
};

// ══════════════════════════════════════════════════
//  室三：我们的时刻（D 层关系记忆，时间线）
// ══════════════════════════════════════════════════
window.soulLoadMoments = async function () {
  const el = document.getElementById('soulMomentsList');
  if (!el) return;
  el.innerHTML = '加载中…';
  try {
    const entries = await fetch(`${CONFIG.api}/memory/entries?agent=xi&limit=200`, CONFIG.fetchOpts()).then(r => r.json());
    const moments = entries.filter(e => e.category === 'D')
      .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    if (!moments.length) {
      el.innerHTML = '<div class="soul-empty">还没有共同的时刻被记下 —— 它们会在相处里慢慢出现。</div>';
      return;
    }
    let lastDate = '';
    el.innerHTML = moments.map(e => {
      const date = (e.created_at || '').slice(0, 10);
      const dateHtml = date !== lastDate ? `<div class="soul-moment-date">${date}</div>` : '';
      lastDate = date;
      return `${dateHtml}
        <div class="soul-moment-row" data-id="${e.id}">
          <div class="soul-moment-dot"></div>
          <div class="soul-moment-main">
            <div class="soul-moment-key">${escHtml(e.key)}</div>
            <div class="soul-moment-text">${escHtml(e.value)}</div>
          </div>
          <button class="mem-del-btn" onclick="soulDeleteMoment('${e.id}',this)" title="删除">🗑</button>
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="soul-empty">${escHtml(e.message)}</div>`;
  }
};

window.soulDeleteMoment = async function (id, btn) {
  try {
    const data = await fetch(`${CONFIG.api}/memory/entries/${id}`, CONFIG.fetchOpts({ method: 'DELETE' })).then(r => r.json());
    if (data.ok) {
      btn.closest('.soul-moment-row')?.remove();
      toast('已删除', 'success');
    } else {
      toast(data.message || '删除失败', 'error');
    }
  } catch (e) { toast(e.message, 'error'); }
};

// ══════════════════════════════════════════════════
//  switchTab 钩子：进入灵魂空间时按解锁状态显示门或内容
// ══════════════════════════════════════════════════
(function () {
  const _prevSwitch = window.switchTab;
  window.switchTab = function (tabId, el) {
    _prevSwitch(tabId, el);
    if (tabId !== 'soulspace') return;
    const gate = document.getElementById('soulGate');
    const content = document.getElementById('soulContent');
    if (_unlocked) {
      gate?.classList.add('hidden');
      content?.classList.remove('hidden');
      window.soulShowRoom('chart');
    } else {
      gate?.classList.remove('hidden');
      content?.classList.add('hidden');
      setTimeout(() => document.getElementById('soulGatePwd')?.focus(), 60);
    }
  };
})();
