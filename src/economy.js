/**
 * Anima — economy.js
 * 成就 · 灵犀经济（养成，不赌场）。复用 Skill 墙的段位视觉（sk-card / lvl-*）。
 */
import { CONFIG, toast } from './state.js';

// 后端 tier(bronze/silver/gold/diamond/legend) → 前端 lvl-* 段位 class + 名号
const _ACH_TIER = {
  bronze:  { lvl: 'bronze',  name: '良品', icon: '◆' },
  silver:  { lvl: 'silver',  name: '精品', icon: '◆' },
  gold:    { lvl: 'gold',    name: '珍品', icon: '★' },
  diamond: { lvl: 'diamond', name: '史诗', icon: '◆' },
  legend:  { lvl: 'legend',  name: '传说', icon: '✦' },
};
// 分类配色（与 Skill 墙 _catColor 同调）
const _CAT_COL = {
  '里程碑': ['#d4a24e', '#f0c674'], '探索': ['#5b8def', '#7fb0ff'],
  '创造': ['#9b6dde', '#c2a0f5'], '成长': ['#3fb97f', '#74e0a8'],
  '陪伴': ['#e07a9c', '#f5b0c8'],
};

let _ACH = null;

export async function achLoad() {
  const wall = document.getElementById('achWall');
  const statsRow = document.getElementById('achStatsRow');
  if (wall) wall.innerHTML = '<div style="color:var(--muted);font-size:13px">加载中…</div>';
  try {
    const data = await fetch(`${CONFIG.api}/economy/status`).then(r => r.json());
    _ACH = data;
    const { lingxi = 0, achievements = [], summary = {} } = data;
    // ── 灵犀 + 进度 bento ──
    if (statsRow) {
      const claimable = summary.claimable || 0;
      statsRow.innerHTML = `
        <div class="num-tile glass lingxi-tile"><div class="nt-label">灵犀</div><div class="nt-value">${lingxi}<span class="lingxi-spark">✦</span></div><div class="nt-sub">心力 · 羁绊的具象</div></div>
        <div class="num-tile glass"><div class="nt-label">已点亮成就</div><div class="nt-value">${summary.done || 0}<span style="font-size:18px;color:var(--muted)"> / ${summary.total || 0}</span></div><div class="nt-sub">真实相处所得</div></div>
        <div class="num-tile glass${claimable ? ' nt-glow' : ''}"><div class="nt-label">可领取</div><div class="nt-value">${claimable}<span class="lingxi-spark">✦</span></div><div class="nt-sub">${claimable ? '点亮后尚未领取' : '已全部领取'}</div></div>
        <div class="num-tile glass"><div class="nt-label">已解锁</div><div class="nt-value">${(data.unlocks || []).length}</div><div class="nt-sub">技能 / 世界皮肤</div></div>`;
    }
    // 一键领取按钮
    const claimAllBtn = document.getElementById('achClaimAllBtn');
    if (claimAllBtn) claimAllBtn.style.display = (summary.claimable > 0) ? '' : 'none';
    // ── 成就墙（复用 sk-card 段位卡）──
    if (wall) {
      wall.innerHTML = achievements.map(a => {
        const t = _ACH_TIER[a.tier] || _ACH_TIER.bronze;
        const [c1, c2] = _CAT_COL[a.cat] || ['#888', '#aaa'];
        const prog = a.done ? 100 : Math.max(4, a.progress || 0);
        const lit = a.done ? '' : ' ach-dim';
        let foot;
        if (a.claimed) foot = `<span class="ach-claimed">✓ 已领取 +${a.reward}✦</span>`;
        else if (a.done) foot = `<button class="ach-claim-btn" onclick="achClaim('${a.id}')">🎁 领取 +${a.reward}✦</button>`;
        else foot = `<span class="ach-progress-txt">${a.cur}/${a.need} · 点亮得 ${a.reward}✦</span>`;
        return `<div class="sk-card lvl-${t.lvl}${lit}" data-id="${a.id}" style="--cat:${c1};--cat2:${c2};--p:${prog}">
          <div class="sk-bar"></div>
          <div class="sk-tier">${t.icon} ${t.name}</div>
          <div class="sk-top">
            <div class="sk-gem-wrap"><div class="sk-gem">${a.icon}</div></div>
            <div class="sk-id">
              <div class="sk-name">${a.name}${a.done ? '<span class="sk-up">✦ 已点亮</span>' : ''}</div>
              <div class="sk-rank-tag">${a.cat}</div>
            </div>
          </div>
          <div class="sk-desc">${a.desc}</div>
          <div class="sk-foot ach-foot">${foot}</div>
        </div>`;
      }).join('');
      // 高阶闪粒
      wall.querySelectorAll('.sk-card.lvl-legend:not(.ach-dim), .sk-card.lvl-diamond:not(.ach-dim)').forEach(card => {
        const n = card.classList.contains('lvl-legend') ? 4 : 2;
        for (let i = 0; i < n; i++) {
          const sp = document.createElement('i'); sp.className = 'sk-spark';
          sp.style.left = (10 + Math.random() * 80) + '%';
          sp.style.top = (12 + Math.random() * 64) + '%';
          sp.style.animationDelay = (Math.random() * 1.8) + 's';
          card.appendChild(sp);
        }
      });
    }
  } catch (e) {
    if (wall) wall.innerHTML = `<div style="color:var(--error);font-size:13px">加载失败: ${e.message}</div>`;
  }
}

export async function achClaim(id) {
  try {
    const r = await fetch(`${CONFIG.api}/economy/claim`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }).then(r => r.json());
    if (r.ok) { toast(`🎁 +${r.reward} 灵犀 · 当前 ${r.lingxi}✦`, 'success'); achLoad(); }
    else toast(r.error || '领取失败', 'error');
  } catch (e) { toast(`领取失败: ${e.message}`, 'error'); }
}

export async function achClaimAll() {
  if (!_ACH) return;
  const pend = (_ACH.achievements || []).filter(a => a.done && !a.claimed);
  if (!pend.length) { toast('没有可领取的成就', 'info'); return; }
  let total = 0;
  for (const a of pend) {
    try {
      const r = await fetch(`${CONFIG.api}/economy/claim`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: a.id }),
      }).then(r => r.json());
      if (r.ok) total += r.reward;
    } catch (e) { /* skip */ }
  }
  if (total) toast(`🎁 共领取 +${total} 灵犀`, 'success');
  achLoad();
}

window.achLoad = achLoad;
window.achClaim = achClaim;
window.achClaimAll = achClaimAll;
