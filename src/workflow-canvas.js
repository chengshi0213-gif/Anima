/**
 * workflow-canvas.js — n8n / 扣子 风格节点画布（基于 Drawflow）
 * 节点 + 端口 + 自由连线 + 拖拽缩放；导出为后端 DAG 图 {nodes, connections}。
 * 端口约定：condition output_1=是 / output_2=否；router output_k=第 k 条 route。
 */
(function () {
  let editor = null, seq = 0;

  const AGENTS = [
    ['xi', '👩‍💼 Anima'],
    ['executor', '⚡ 执行者'], ['writer', '✍️ 写手'], ['reader', '📖 阅读者'], ['critic', '🔍 评审'],
  ];
  const agentOpts = (sel) => AGENTS.map(([v, l]) => `<option value="${v}"${v === sel ? ' selected' : ''}>${l}</option>`).join('');

  // 节点定义：标题/主色/输入数/输出数/HTML(df-* 双向绑定到 node.data)
  const DEFS = {
    agent: { t: 'Agent', c: '#2563EB', i: 1, o: 1, html: (d) =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#2563EB"></i>Agent</div>
       <select df-agent class="wfx-sel">${agentOpts(d.agent || 'xi')}</select>
       <textarea df-prompt class="wfx-ta" placeholder="任务提示词…">${d.prompt || ''}</textarea>` },
    condition: { t: '条件', c: '#8b5cf6', i: 1, o: 2, html: (d) =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#8b5cf6"></i>条件分支</div>
       <input df-keyword class="wfx-in" placeholder="命中关键词（如：通过）" value="${d.keyword || ''}">
       <div class="wfx-ports"><span>✓ 是</span><span>✗ 否</span></div>` },
    router: { t: 'AI路由', c: '#16a34a', i: 1, o: 3, html: (d) =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#16a34a"></i>AI 路由</div>
       <input df-question class="wfx-in" placeholder="判定标准" value="${d.question || ''}">
       <input df-r1 class="wfx-in" placeholder="路线1" value="${d.r1 || ''}">
       <input df-r2 class="wfx-in" placeholder="路线2" value="${d.r2 || ''}">
       <input df-r3 class="wfx-in" placeholder="路线3（可空）" value="${d.r3 || ''}">` },
    loop: { t: '循环', c: '#0ea5e9', i: 1, o: 1, html: (d) =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#0ea5e9"></i>循环</div>
       <div class="wfx-row"><input type="number" df-max_iter class="wfx-in" style="width:60px" value="${d.max_iter || 3}" title="最多次数">
       <input df-stop_keyword class="wfx-in" placeholder="停止词" value="${d.stop_keyword || '完成'}"></div>
       <select df-agent class="wfx-sel">${agentOpts(d.agent || 'xi')}</select>
       <textarea df-prompt class="wfx-ta" placeholder="每轮任务…">${d.prompt || ''}</textarea>` },
    human: { t: '人审', c: '#dc2626', i: 1, o: 1, html: (d) =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#dc2626"></i>人审闸门</div>
       <textarea df-message class="wfx-ta" placeholder="请用户审核什么…">${d.message || ''}</textarea>` },
    taozu: { t: '动态拆解', c: '#6b21a8', i: 1, o: 1, html: (d) =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#6b21a8"></i>Anima·动态拆解</div>
       <textarea df-goal class="wfx-ta" placeholder="一句话目标，运行时拆成子流程…">${d.goal || ''}</textarea>` },
    merge: { t: '合流', c: '#64748b', i: 2, o: 1, html: () =>
      `<div class="wfx-hd"><i class="wfx-dot" style="background:#64748b"></i>合流</div>
       <div class="wfx-note">汇合多路输入</div>` },
  };

  function init() {
    const el = document.getElementById('wfCanvas');
    if (!el || el._df) return;
    if (!window.Drawflow) { console.warn('[wf] Drawflow 未加载'); return; }
    editor = new Drawflow(el);
    editor.reroute = true;
    editor.curvature = 0.5;
    editor.start();
    el._df = editor;
    if (Object.keys(editor.export().drawflow.Home.data).length === 0) {
      addNode('agent', 40, 60);   // 起始节点
    }
  }

  function addNode(type, x, y) {
    if (!editor) init();
    if (!editor) return;
    const def = DEFS[type] || DEFS.agent;
    seq++;
    const px = x != null ? x : 60 + (seq % 3) * 270;
    const py = y != null ? y : 40 + Math.floor(seq / 3) * 190 + (seq % 2) * 20;
    const data = {};
    const html = `<div class="wfx wfx-${type}">${def.html(data)}</div>`;
    editor.addNode(type, def.i, def.o, px, py, `wfx-node wfx-node-${type}`, data, html);
  }

  // Drawflow 导出 → 后端 DAG 图
  function exportGraph() {
    if (!editor) return { nodes: {}, connections: [] };
    const home = editor.export().drawflow.Home.data;
    const nodes = {}, connections = [];
    for (const id in home) {
      const n = home[id];
      const data = Object.assign({}, n.data);
      if (n.name === 'router') {
        data.routes = [data.r1, data.r2, data.r3].filter(Boolean).map((l) => ({ label: l }));
      }
      if (n.name === 'loop') data.max_iter = +data.max_iter || 3;
      nodes[id] = { type: n.name, data };
      for (const out in n.outputs) {
        (n.outputs[out].connections || []).forEach((c) =>
          connections.push({ source: id, target: String(c.node), sourcePort: out }));
      }
    }
    return { nodes, connections };
  }

  function clear() {
    if (editor) { editor.clear(); seq = 0; }
  }

  // 把后端图 / 模板（线性 steps 或 graph）导入画布
  function importGraph(g) {
    if (!editor) init();
    if (!editor || !g) return;
    editor.clear(); seq = 0;
    if (Array.isArray(g)) {            // 旧线性 steps → 串成链
      let prev = null, y = 50;
      g.forEach((s, k) => {
        const type = ({ sequential: 'agent', parallel: 'merge' })[s.type] || s.type || 'agent';
        const def = DEFS[type] || DEFS.agent;
        const id = editor.addNode(type, def.i, def.o, 60 + k * 270, y, `wfx-node wfx-node-${type}`,
          { agent: s.agent, prompt: s.prompt, keyword: s.keyword,
            max_iter: s.max_iter, stop_keyword: s.stop_keyword, goal: s.goal,
            message: s.message, question: s.question }, `<div class="wfx wfx-${type}">${def.html(s)}</div>`);
        if (prev != null) try { editor.addConnection(prev, id, 'output_1', 'input_1'); } catch (e) {}
        prev = id; y += (k % 2) * 30;
      });
    } else if (g.nodes) {              // 已是图
      const idmap = {};
      for (const oid in g.nodes) {
        const nd = g.nodes[oid]; const type = nd.type || 'agent'; const def = DEFS[type] || DEFS.agent;
        idmap[oid] = editor.addNode(type, def.i, def.o, 60, 60, `wfx-node wfx-node-${type}`,
          nd.data || {}, `<div class="wfx wfx-${type}">${def.html(nd.data || {})}</div>`);
      }
      (g.connections || []).forEach((c) => {
        try { editor.addConnection(idmap[c.source], idmap[c.target], c.sourcePort || 'output_1', 'input_1'); } catch (e) {}
      });
      try { editor.arrange_starting_node?.(); } catch (e) {}
    }
  }

  window.PersonaWF = { init, addNode, exportGraph, clear, importGraph, get editor() { return editor; } };
  // 兼容旧调用：palette 按钮的 wfAddStep 改为加节点
  window.wfAddNode = addNode;
})();
