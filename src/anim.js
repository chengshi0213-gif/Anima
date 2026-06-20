/**
 * Anima — anim.js
 * GSAP 编排层（接入 gsap-core / timeline / scrolltrigger / flip skill 思路）
 * 设计原则（Emil）：动效服务功能 · 只动 transform/opacity · <300ms · 尊重 reduced-motion
 * 纯增强：gsap 不存在或用户偏好减弱动效时，全部静默降级，不影响功能。
 */

const g = window.gsap;
const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const ON = !!g && !reduce;

if (g) {
  try {
    g.registerPlugin(
      window.ScrollTrigger, window.Flip,
      window.MotionPathPlugin, window.DrawSVGPlugin,
    );
    // 全局默认：Emil 风格强 ease-out
    g.defaults({ ease: 'power3.out', duration: 0.5 });
  } catch (_) {}
}

// 读当前模式的节奏倍率（--t-scale），不同模式可有不同动效速度
function pace() {
  const v = parseFloat(getComputedStyle(document.body).getPropertyValue('--t-scale'));
  return Number.isFinite(v) && v > 0 ? v : 1;
}

// ── 数字滚动：把 #overviewBody .big 从 0 滚到目标值（保留 ¥ 前缀/小数）──
function countUp(el) {
  const raw = el.textContent.trim();
  const m = raw.match(/^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/);
  if (!m) return;
  const prefix = m[1], suffix = m[3];
  const target = parseFloat(m[2].replace(/,/g, ''));
  if (!Number.isFinite(target)) return;
  const decimals = (m[2].split('.')[1] || '').length;
  const obj = { v: 0 };
  g.to(obj, {
    v: target, duration: 0.9 * pace(), ease: 'power2.out',
    onUpdate() { el.textContent = prefix + obj.v.toFixed(decimals) + suffix; },
  });
}

// ── 概览进场：卡片 stagger 上浮 + 数字滚动（gsap-core stagger）──
function animateOverview() {
  if (!ON) return;
  const body = document.getElementById('overviewBody');
  if (!body) return;
  const cards = body.querySelectorAll(':scope > .card, :scope > .agent-card');
  if (cards.length) {
    g.from(cards, {
      opacity: 0, y: 16, duration: 0.5 * pace(),
      stagger: 0.05,                 // Emil：30-80ms 之间
      clearProps: 'opacity,transform',
      onComplete() { body.querySelectorAll('.big').forEach(countUp); },
    });
  } else {
    body.querySelectorAll('.big').forEach(countUp);
  }
}

// ── 切到人格：聊天头像弹入 + 输入区抬升（per-agent 节奏）──
function animateAgentPanel(tabId) {
  if (!ON) return;
  const panel = document.getElementById(`tab-${tabId}`);
  if (!panel) return;
  const avatar = panel.querySelector('.agent-avatar-lg');
  const composer = panel.querySelector('[id^="composer-"]');
  const tl = g.timeline();
  if (avatar) tl.from(avatar, { scale: 0.85, opacity: 0, duration: 0.4 * pace(), ease: 'back.out(1.6)', clearProps: 'all' }, 0);
  if (composer) tl.from(composer, { y: 14, opacity: 0, duration: 0.45 * pace(), clearProps: 'all' }, 0.05);
}

// ── 浮层弹入：从 0.95 + 透明 缩放进入（Emil：绝不从 scale(0)）──
function popOverlay(overlay) {
  if (!ON || !overlay) return;
  const card = overlay.querySelector('.cmd-palette, .morning-card, .onboarding-card, .modal, [class*="-card"]') || overlay.firstElementChild;
  if (!card) return;
  g.fromTo(card,
    { scale: 0.95, opacity: 0, y: 8 },
    { scale: 1, opacity: 1, y: 0, duration: 0.32, ease: 'power3.out', clearProps: 'transform,opacity' });
}

// 监听浮层 .hidden 移除 → 弹入（解耦，无需改各自打开函数）
function watchOverlay(id) {
  const ov = document.getElementById(id);
  if (!ov) return;
  let last = ov.classList.contains('hidden');
  new MutationObserver(() => {
    const now = ov.classList.contains('hidden');
    if (last && !now) popOverlay(ov);   // 从隐藏→显示
    last = now;
  }).observe(ov, { attributes: true, attributeFilter: ['class'] });
}

// ── 消息操作层：hover 复制按钮 + GSAP 微弹入场（不改 chat.js，纯 DOM 增强）──
function initMsgActions() {
  // 注入 .msg-actions 到一条消息（idempotent）
  function addCopyBtn(msgEl) {
    if (msgEl.querySelector('.msg-actions')) return;
    const body = msgEl.querySelector('.msg-body');
    if (!body) return;
    const bubble = body.querySelector('.msg-bubble');
    if (!bubble) return;

    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    actions.innerHTML = '<button class="msg-action-btn" data-action="copy" title="复制消息" aria-label="复制消息">⎘</button>';

    const meta = body.querySelector('.msg-meta');
    meta ? body.insertBefore(actions, meta) : body.appendChild(actions);

    actions.addEventListener('click', e => {
      const btn = e.target.closest('[data-action="copy"]');
      if (!btn) return;
      const text = (bubble.innerText || bubble.textContent || '').trim();
      navigator.clipboard.writeText(text).then(() => {
        btn.classList.add('copied');
        btn.textContent = '✓';
        window.toast?.('已复制');
        setTimeout(() => { btn.classList.remove('copied'); btn.textContent = '⎘'; }, 1500);
      }).catch(() => {});
    });
  }

  // GSAP 微弹入场：back.out(1.15) 比纯 ease-out 多一点生命感
  function enterMsg(msgEl) {
    if (!ON) return;
    msgEl.style.animation = 'none';      // 禁 CSS keyframe，由 GSAP 接管
    g.set(msgEl, { opacity: 0, y: 10 }); // 等价 CSS animation "from" 态
    g.to(msgEl, {
      opacity: 1, y: 0,
      duration: 0.38 * pace(),
      ease: 'back.out(1.15)',
      clearProps: 'transform,opacity',
    });
  }

  // 已有消息仅注入按钮（不重新入场）
  document.querySelectorAll('.msg').forEach(addCopyBtn);

  // 监听新消息：注入按钮 + 入场动画
  document.querySelectorAll('[id^="messages-"]').forEach(box => {
    new MutationObserver(muts => {
      muts.forEach(m => {
        m.addedNodes.forEach(node => {
          if (node.nodeType !== 1) return;
          const msgs = node.classList?.contains('msg')
            ? [node]
            : [...(node.querySelectorAll?.('.msg') ?? [])];
          msgs.forEach(msg => { addCopyBtn(msg); enterMsg(msg); });
        });
      });
    }).observe(box, { childList: true });
  });
}

// ══ 接线：包装既有 window.* 函数，纯增强 ══
function wire() {
  // 概览加载完成后做进场
  const origLoad = window.loadOverview;
  if (typeof origLoad === 'function') {
    window.loadOverview = async function (...a) {
      const r = await origLoad.apply(this, a);
      requestAnimationFrame(animateOverview);
      return r;
    };
  }
  // 切到人格时做面板进场
  const origSwitch = window.switchTab;
  if (typeof origSwitch === 'function') {
    const AGENT_TABS = new Set(['xi']);
    window.switchTab = function (tabId, el) {
      const r = origSwitch.call(this, tabId, el);
      if (AGENT_TABS.has(tabId)) requestAnimationFrame(() => animateAgentPanel(tabId));
      return r;
    };
  }
  // 浮层弹入
  ['cmdOverlay', 'morningOverlay', 'onboardingOverlay'].forEach(watchOverlay);

  // 消息操作层（复制按钮 + GSAP 入场）
  initMsgActions();
}

// main.js 在所有模块之后 import 本文件；此时 window.* 已就绪
wire();

// 暴露给将来手动调用（如刷新概览）
window.Anim = { animateOverview, animateAgentPanel, popOverlay, countUp, initMsgActions };
