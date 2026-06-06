/* ============================================================
 * Anima 全局错误边界 (error-boundary.js)
 * ------------------------------------------------------------
 * 必须在所有其它脚本之前加载（普通 <script>，非 module）。
 * 职责：
 *   1. 捕获全局 JS 错误 / 资源加载错误 / 未处理的 Promise rejection
 *   2. 不让任何一个报错静默失败，给用户友好提示
 *   3. 维护内存错误队列 window.__animaErrors，供"导出诊断包"使用
 *   4. 自身绝不抛错（所有逻辑包在 try/catch 里）
 * ============================================================ */
(function () {
  'use strict';

  var MAX_QUEUE = 100;          // 错误队列上限，防止内存无限增长
  var DEDUP_WINDOW_MS = 3000;   // 同一错误在此窗口内不重复提示
  var queue = [];
  var lastShown = {};           // 指纹 -> 时间戳，用于去重

  // 对外暴露错误队列（诊断导出读取此处）
  window.__animaErrors = queue;

  function nowIso() {
    try { return new Date().toISOString(); } catch (e) { return '' + Date.now(); }
  }

  // 把一条错误记录进队列
  function record(kind, message, detail) {
    try {
      queue.push({
        time: nowIso(),
        kind: kind,                       // 'error' | 'promise' | 'resource' | 'manual'
        message: String(message || '未知错误'),
        detail: detail || null,
        ua: navigator.userAgent,
        url: location.href
      });
      if (queue.length > MAX_QUEUE) queue.splice(0, queue.length - MAX_QUEUE);
    } catch (e) { /* 记录失败也不能抛 */ }
  }

  // 友好提示（优先用全站 toast，没有就用内置横幅）
  function notify(userMsg) {
    try {
      if (typeof window.toast === 'function') {
        window.toast(userMsg, 'error');
        return;
      }
      banner(userMsg);
    } catch (e) { /* 提示失败静默 */ }
  }

  // 内置兜底横幅（toast 尚未就绪时，例如启动早期崩溃）
  function banner(msg) {
    try {
      var id = '__anima_err_banner';
      var el = document.getElementById(id);
      if (!el) {
        el = document.createElement('div');
        el.id = id;
        el.style.cssText = [
          'position:fixed', 'left:50%', 'top:18px', 'transform:translateX(-50%)',
          'z-index:99999', 'max-width:80vw', 'padding:10px 16px',
          'background:#3a1212', 'color:#ffd9d9', 'border:1px solid #7a2a2a',
          'border-radius:10px', 'font-size:13px', 'line-height:1.5',
          'box-shadow:0 8px 28px rgba(0,0,0,.45)', 'font-family:system-ui,sans-serif',
          'cursor:pointer'
        ].join(';');
        el.addEventListener('click', function () { el.remove(); });
        (document.body || document.documentElement).appendChild(el);
      }
      el.textContent = msg + '（点击关闭）';
      clearTimeout(el.__t);
      el.__t = setTimeout(function () { try { el.remove(); } catch (e) {} }, 6000);
    } catch (e) { /* 横幅也失败就只能静默 */ }
  }

  // 去重判断：相同指纹在窗口内只提示一次
  function shouldShow(fingerprint) {
    var t = Date.now();
    if (lastShown[fingerprint] && (t - lastShown[fingerprint]) < DEDUP_WINDOW_MS) {
      return false;
    }
    lastShown[fingerprint] = t;
    return true;
  }

  // —— 1. JS 运行时错误 + 资源加载错误 ——
  // 用捕获阶段监听，能同时拿到 <img>/<script> 等资源加载失败事件
  window.addEventListener('error', function (e) {
    try {
      // 资源加载错误：e.target 是元素且无 message
      if (e && e.target && e.target !== window && (e.target.src || e.target.href)) {
        var res = e.target.src || e.target.href;
        record('resource', '资源加载失败: ' + res, { tag: e.target.tagName });
        // 资源错误不打扰用户（多为非关键静态资源），仅记录
        return;
      }
      var msg = (e && e.message) || '脚本运行出错';
      var detail = {
        source: e && e.filename,
        line: e && e.lineno,
        col: e && e.colno,
        stack: e && e.error && e.error.stack ? String(e.error.stack) : null
      };
      record('error', msg, detail);
      if (shouldShow('e:' + msg)) {
        notify('出了点小状况，已记录。若反复出现可在设置里导出诊断包反馈');
      }
    } catch (err) { /* 处理器自身不抛 */ }
  }, true);

  // —— 2. 未处理的 Promise rejection ——
  window.addEventListener('unhandledrejection', function (e) {
    try {
      var reason = e && e.reason;
      var msg = reason && reason.message ? reason.message
              : (typeof reason === 'string' ? reason : '异步操作未完成');
      var detail = {
        stack: reason && reason.stack ? String(reason.stack) : null
      };
      record('promise', msg, detail);
      // 网络类错误给更贴切的话术
      var friendly = /fetch|network|Failed to fetch|NetworkError/i.test(msg)
        ? '网络好像断了，请检查后端是否在运行'
        : '有个后台操作没完成，已记录';
      if (shouldShow('p:' + msg)) notify(friendly);
    } catch (err) { /* 静默 */ }
  });

  // —— 对外手动上报接口（业务代码可主动调用）——
  window.reportError = function (message, detail) {
    record('manual', message, detail || null);
  };

  // —— 给诊断导出用：返回错误队列快照 ——
  window.getErrorReport = function () {
    try { return JSON.parse(JSON.stringify(queue)); }
    catch (e) { return queue.slice(); }
  };

  // —— 清空队列（用户主动反馈后可清）——
  window.clearErrorReport = function () { queue.length = 0; };

  console.log('[Anima] 全局错误边界已就绪');
})();
