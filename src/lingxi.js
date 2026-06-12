/**
 * Anima — lingxi.js
 * 今日灵犀：读取守藏每日 SOP 写入的 Vault Daily Note，逐段淡入展示。
 */
import { CONFIG } from './state.js?v=1.2.1';

function todayStr() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

// 去掉标题行，按空行分段
function parseLingxi(raw) {
  const lines = raw.replace(/\r\n/g, '\n').split('\n')
    .filter(line => !/^#{1,3}\s/.test(line.trim()));
  return lines.join('\n')
    .split(/\n\s*\n/)
    .map(p => p.trim())
    .filter(Boolean);
}

window.lingxiLoad = async function () {
  const dateEl = document.getElementById('lingxiDate');
  const bodyEl = document.getElementById('lingxiContent');
  if (!bodyEl) return;

  const today = todayStr();
  if (dateEl) dateEl.textContent = today;
  bodyEl.innerHTML = '<div class="lingxi-loading">翻开今天这一页…</div>';

  try {
    const tree = await fetch(`${CONFIG.api}/vault/tree`, CONFIG.fetchOpts()).then(r => r.json());
    const vaultDir = tree.vault_dir || '';
    const path = `${vaultDir}/Daily Notes/${today}.md`;
    const data = await fetch(`${CONFIG.api}/vault/file?path=${encodeURIComponent(path)}`, CONFIG.fetchOpts()).then(r => r.json());

    if (data.error || !data.content || !data.content.trim()) {
      bodyEl.innerHTML = '<div class="lingxi-empty">今天的这一页还没写呢，晚点再来看看。</div>';
      return;
    }

    const paras = parseLingxi(data.content);
    if (!paras.length) {
      bodyEl.innerHTML = '<div class="lingxi-empty">今天的这一页还没写呢，晚点再来看看。</div>';
      return;
    }

    bodyEl.innerHTML = paras.map(p => {
      const isSign = /^—\s*Anima/.test(p);
      return `<p class="${isSign ? 'lingxi-sign' : ''}">${escapeHtml(p)}</p>`;
    }).join('');

    // 逐段淡入
    bodyEl.querySelectorAll('p').forEach((p, i) => {
      setTimeout(() => p.classList.add('show'), 200 + i * 320);
    });
  } catch (e) {
    bodyEl.innerHTML = '<div class="lingxi-empty">这一页暂时翻不开，稍后再试。</div>';
  }
};

// switchTab 包装：进入「今日灵犀」时加载并播放淡入
(function () {
  const _prev = window.switchTab;
  window.switchTab = function (tabId, el) {
    const r = _prev(tabId, el);
    if (tabId === 'lingxi') window.lingxiLoad();
    return r;
  };
})();
