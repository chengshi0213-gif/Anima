/**
 * companion.js — 双层架构：陪伴模式（默认极简）↔ 工作台（进阶全功能）
 * 陪伴模式：全屏当前人格 + 底部人格坞切换 + 语音输入；工作台 = 现有侧栏全功能。
 */
(function () {
  const PERSONAS = [
    { id: 'xi', name: 'Anima', icon: '👩‍💼', avatarImg: '/assets/anima-avatar.png', col: '#C99A2E', tag: '私人助理 · 把一天收拢成秩序' },
  ];
  const PMAP = {}; PERSONAS.forEach(p => PMAP[p.id] = p);
  const PSET = new Set(PERSONAS.map(p => p.id));
  function updateCenter(p) {
    const m = PMAP[p]; if (!m) return;
    const n = document.getElementById('coName'), t = document.getElementById('coTag');
    if (n) n.textContent = m.name; if (t) t.textContent = m.tag;
  }

  function buildDock() {
    const dock = document.getElementById('companionDock');
    if (!dock || dock._built) return; dock._built = true;
    dock.innerHTML =
      `<div class="cd-personas">${PERSONAS.map(p =>
        `<button class="cd-av" data-p="${p.id}" style="--c:${p.col}" title="${p.name}" onclick="dockSwitch('${p.id}')">
           <span class="cd-ic">${p.avatarImg ? `<img src="${p.avatarImg}" alt="${p.name}">` : p.icon}</span><span class="cd-name">${p.name}</span>
         </button>`).join('')}</div>
       <div class="cd-sep"></div>
       <button class="cd-adv" onclick="setAppMode('workspace')" title="进入工作台（进阶全功能）">⊞ 进阶</button>`;
  }

  function updateDock(p) {
    document.querySelectorAll('#companionDock .cd-av').forEach(a => a.classList.toggle('on', a.dataset.p === p));
  }
  window.updateCompanionDock = updateDock;

  window.dockSwitch = function (p) {
    window.switchTab(p, document.querySelector('[data-tab="' + p + '"]'));
    updateDock(p); updateCenter(p); window.Soul && window.Soul.setPersona(p);
  };

  window.setAppMode = function (m) {
    const comp = m === 'companion';
    document.body.classList.toggle('mode-companion', comp);
    try { localStorage.setItem('anima_mode', m); } catch (_) {}
    if (comp) {
      buildDock();
      const cur = document.querySelector('.nav-item.active')?.dataset.tab;
      const persona = PSET.has(cur) ? cur : 'xi';
      window.switchTab(persona, document.querySelector('[data-tab="' + persona + '"]'));
      updateDock(persona); updateCenter(persona); window.Soul && window.Soul.setPersona(persona);
    }
  };

  // 语音输入（第一版：Web Speech；不可用则提示本地 Whisper 规划中）
  function activeAgent() {
    const el = document.querySelector('.tab-panel.active');
    return el ? el.id.replace('tab-', '') : 'xi';
  }
  let _sr = null;
  function _stopListen() {
    const mic = document.getElementById('companionMic'), orb = document.getElementById('companionOrb');
    mic && mic.classList.remove('rec'); orb && orb.classList.remove('rec');
    window.Soul && window.Soul.stopMic();
    if (_sr) { try { _sr.stop(); } catch (_) {} _sr = null; }
  }
  window.voiceInput = function () {
    const mic = document.getElementById('companionMic'), orb = document.getElementById('companionOrb');
    if (mic && mic.classList.contains('rec')) { _stopListen(); return; }   // 再点=停止
    mic && mic.classList.add('rec'); orb && orb.classList.add('rec');
    window.Soul && window.Soul.startMicReactive();                          // 声纹反馈：真麦克风音量驱动灵体
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { window.toast && window.toast('已聆听（转写用本地 Whisper，规划中）', 'info'); return; }
    try { _sr = new SR(); } catch (_) { _sr = null; return; }
    _sr.lang = 'zh-CN'; _sr.interimResults = false; _sr.maxAlternatives = 1;
    _sr.onresult = function (e) {
      const t = e.results[0][0].transcript;
      const inp = document.getElementById('input-' + activeAgent());
      if (inp) { inp.value = (inp.value ? inp.value + ' ' : '') + t; inp.dispatchEvent(new Event('input')); inp.focus(); }
    };
    _sr.onerror = function () { window.toast && window.toast('转写失败（可能需联网，本地 Whisper 规划中）', 'error'); };
    _sr.onend = function () { _stopListen(); };
    try { _sr.start(); } catch (_) { _stopListen(); }
  };

  function init() {
    const saved = (function () { try { return localStorage.getItem('anima_mode'); } catch (_) { return null; } })();
    window.setAppMode(saved === 'workspace' ? 'workspace' : 'companion');  // 默认陪伴
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
