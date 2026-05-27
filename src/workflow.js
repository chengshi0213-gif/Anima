/**
 * Anima — workflow.js
 * Workflow builder, templates, scheduler, file watcher, group chat, TTS, AI assist
 */
import { CONFIG, AGENTS, wsConns, wsStatus, escHtml, formatTime, toast, agentAvatarHtml, agentName, scrollBottom } from './state.js';
// ══════════════════════════════════════════════════
//  工作流构建器
// ══════════════════════════════════════════════════
const WF_API = () => `${CONFIG.api}/workflow`;
let wfStepList = [];   // [{agent, prompt, pass_context}]
let wfCurrentId = null;

const WF_AGENTS = [
  { id:'xi',   label:'👩‍💼 Anima — 私人助理' },
  { id:'yiyi',     label:'🌸 晞 — 情感伙伴' },
  { id:'tianyuan', label:'🏢 陶朱 — CEO' },
  { id:'shoucang',  label:'🎓 守藏 — 知识研究员' },
  { id:'executor', label:'⚡ 执行者 — 任务执行' },
  { id:'writer',   label:'✍️ 写手 — 内容创作' },
  { id:'reader',   label:'📖 阅读者 — 文档阅读' },
  { id:'critic',   label:'🔍 评审 — 质量把关' },
];

function wfRender() {
  const el = document.getElementById('wfSteps');
  if (!el) return;
  if (!wfStepList.length) {
    el.innerHTML = '<div style="text-align:center;color:var(--muted);padding:20px 0;font-size:13px">点击"添加步骤"开始构建工作流</div>';
    return;
  }
  const opts = WF_AGENTS.map(a =>
    `<option value="${a.id}">${a.label}</option>`).join('');

  const connector = (i) => i > 0 ? `<div class="wf-connector"><div class="wf-connector-line"></div><span class="wf-connector-arrow">▼</span><div class="wf-connector-line"></div></div>` : '';
  const delBtn   = (i) => `<button onclick="wfRemoveStep(${i})" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:14px;margin-left:auto" title="删除">✕</button>`;
  const agentSel = (val, path) => `<select class="wf-step-agent-select" onchange="${path}=this.value">${WF_AGENTS.map(a=>`<option value="${a.id}"${val===a.id?' selected':''}>${a.label}</option>`).join('')}</select>`;

  el.innerHTML = wfStepList.map((step, i) => {
    const nodeType = step.type || 'sequential';
    let card = '';

    if (nodeType === 'parallel') {
      const branches = (step.branches || []).map((b, bi) => `
        <div class="wf-branch-item">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
            <span style="font-size:11px;color:var(--text-muted)">分支 ${bi+1}</span>
            ${agentSel(b.agent, `wfStepList[${i}].branches[${bi}].agent`)}
          </div>
          <textarea class="wf-step-prompt" rows="2" placeholder="分支 ${bi+1} 提示词…"
            oninput="wfStepList[${i}].branches[${bi}].prompt=this.value">${escHtml(b.prompt||'')}</textarea>
        </div>`).join('');
      card = `<div class="wf-step-card wf-node-parallel" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num" style="background:#f59e0b">${i+1}</div>
          <span style="font-size:12px;font-weight:700;color:#92400e">⚡ 并行节点</span>
          ${delBtn(i)}
        </div>
        <div class="wf-branches">${branches}</div>
      </div>`;
    } else if (nodeType === 'condition') {
      card = `<div class="wf-step-card wf-node-condition" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num" style="background:#8b5cf6">${i+1}</div>
          <span style="font-size:12px;font-weight:700;color:#5b21b6">🔀 条件节点</span>
          ${delBtn(i)}
        </div>
        <div class="wf-step-body">
          <div style="margin-bottom:8px">
            <label style="font-size:11px;color:var(--text-muted)">如果上步输出包含关键词：</label>
            <input style="width:100%;margin-top:4px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:var(--bg-main);color:var(--text-main)"
              value="${escHtml(step.keyword||'')}" oninput="wfStepList[${i}].keyword=this.value" placeholder="例：失败、错误、否">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div>
              <div style="font-size:11px;color:#16a34a;font-weight:600;margin-bottom:4px">✓ 是：</div>
              ${agentSel(step.true_step?.agent||'xi', `wfStepList[${i}].true_step.agent`)}
              <textarea class="wf-step-prompt" rows="2" style="margin-top:4px" placeholder="条件满足时的任务…"
                oninput="wfStepList[${i}].true_step.prompt=this.value">${escHtml(step.true_step?.prompt||'')}</textarea>
            </div>
            <div>
              <div style="font-size:11px;color:#dc2626;font-weight:600;margin-bottom:4px">✗ 否：</div>
              ${agentSel(step.false_step?.agent||'xi', `wfStepList[${i}].false_step.agent`)}
              <textarea class="wf-step-prompt" rows="2" style="margin-top:4px" placeholder="条件不满足时的任务…"
                oninput="wfStepList[${i}].false_step.prompt=this.value">${escHtml(step.false_step?.prompt||'')}</textarea>
            </div>
          </div>
        </div>
      </div>`;
    } else if (nodeType === 'loop') {
      card = `<div class="wf-step-card wf-node-loop" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num" style="background:#0ea5e9">${i+1}</div>
          <span style="font-size:12px;font-weight:700;color:#0369a1">🔁 循环节点</span>
          ${delBtn(i)}
        </div>
        <div class="wf-step-body">
          <div style="display:flex;gap:8px;margin-bottom:8px">
            <div style="flex:1">
              <label style="font-size:11px;color:var(--text-muted)">最多循环次数</label>
              <input type="number" min="1" max="10" value="${step.max_iter||3}"
                oninput="wfStepList[${i}].max_iter=+this.value"
                style="width:100%;margin-top:4px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:var(--bg-main);color:var(--text-main)">
            </div>
            <div style="flex:1">
              <label style="font-size:11px;color:var(--text-muted)">停止关键词</label>
              <input value="${escHtml(step.stop_keyword||'完成')}"
                oninput="wfStepList[${i}].stop_keyword=this.value"
                style="width:100%;margin-top:4px;padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:var(--bg-main);color:var(--text-main)">
            </div>
          </div>
          ${agentSel(step.step?.agent||'xi', `wfStepList[${i}].step.agent`)}
          <textarea class="wf-step-prompt" rows="2" style="margin-top:6px" placeholder="每次循环执行的任务…"
            oninput="wfStepList[${i}].step.prompt=this.value">${escHtml(step.step?.prompt||'')}</textarea>
        </div>
      </div>`;
    } else {
      // sequential
      card = `<div class="wf-step-card" draggable="true" data-idx="${i}"
               ondragstart="wfDragStart(event,${i})" ondragover="wfDragOver(event,${i})" ondrop="wfDrop(event,${i})">
        <div class="wf-step-header">
          <div class="wf-step-num">${i+1}</div>
          ${agentSel(step.agent||'xi', `wfStepList[${i}].agent`)}
          <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
            ${i > 0 ? `<label style="font-size:11px;display:flex;align-items:center;gap:3px;color:var(--text-muted)">
              <input type="checkbox" ${step.pass_context?'checked':''} onchange="wfStepList[${i}].pass_context=this.checked"> 接收上步
            </label>` : ''}
            <button onclick="wfRemoveStep(${i})" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px" title="删除">✕</button>
          </div>
        </div>
        <div class="wf-step-body">
          <textarea class="wf-step-prompt" placeholder="输入给该 Agent 的任务提示词…" rows="3"
            oninput="wfStepList[${i}].prompt=this.value">${escHtml(step.prompt||'')}</textarea>
        </div>
      </div>`;
    }
    return connector(i) + card;
  }).join('');
}

window.wfAddStep = function(type = 'sequential') {
  if (type === 'parallel') {
    wfStepList.push({
      type: 'parallel',
      branches: [
        { agent: 'writer',   prompt: '', pass_context: true },
        { agent: 'reader',   prompt: '', pass_context: true },
      ],
    });
  } else if (type === 'condition') {
    wfStepList.push({
      type: 'condition',
      keyword: '失败',
      true_step:  { agent: 'xi', prompt: '处理失败情况：' },
      false_step: { agent: 'xi', prompt: '继续正常流程：' },
    });
  } else if (type === 'loop') {
    wfStepList.push({
      type: 'loop',
      max_iter: 3,
      stop_keyword: '完成',
      step: { agent: 'xi', prompt: '', pass_context: true },
    });
  } else {
    wfStepList.push({ type: 'sequential', agent:'xi', prompt:'', pass_context: wfStepList.length > 0 });
  }
  wfRender();
};

window.wfRemoveStep = function(idx) {
  wfStepList.splice(idx, 1);
  wfRender();
};

window.wfNew = function() {
  wfStepList.length = 0;  // 清空数组但保持引用（wfRun 引用同一个数组）
  window._wfStepsData = wfStepList;
  wfCurrentId = null;
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = '我的工作流';
  document.getElementById('wfResults').innerHTML = '';
  document.getElementById('wfRunStatus').textContent = '等待运行…';
  wfRender();
};

// 拖拽排序
let _wfDragIdx = null;
window.wfDragStart = (e, idx) => { _wfDragIdx = idx; e.dataTransfer.effectAllowed = 'move'; };
window.wfDragOver  = (e, idx) => { e.preventDefault(); };
window.wfDrop      = (e, idx) => {
  e.preventDefault();
  if (_wfDragIdx === null || _wfDragIdx === idx) return;
  const [item] = wfStepList.splice(_wfDragIdx, 1);
  wfStepList.splice(idx, 0, item);
  _wfDragIdx = null;
  wfRender();
};

// 运行
window.wfRun = async function() {
  if (!wfStepList.length) { toast('请先添加步骤', 'error'); return; }
  // 验证：只检查 sequential 节点的 prompt（其他节点结构不同）
  const anyEmpty = wfStepList.some(s => {
    const t = s.type || 'sequential';
    if (t === 'sequential') return !s.prompt?.trim();
    if (t === 'loop') return !s.step?.prompt?.trim();
    return false;
  });
  if (anyEmpty) { toast('有步骤的提示词为空', 'error'); return; }

  const btn     = document.getElementById('wfRunBtn');
  const status  = document.getElementById('wfRunStatus');
  const results = document.getElementById('wfResults');
  if (btn) btn.disabled = true;
  if (status) status.textContent = '运行中…';
  if (results) results.innerHTML = '<div style="text-align:center;padding:20px;color:var(--muted)">⏳ 执行中，请稍候…</div>';

  try {
    const useKb = document.getElementById('wfUseKb')?.checked || false;
    const r = await fetch(`${WF_API()}/run`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ steps: wfStepList, use_kb: useKb }),
    });
    const { results: res, error } = await r.json();
    if (error) throw new Error(error);
    if (status) status.textContent = `完成 · ${res.length} 步`;
    results.innerHTML = res.map((r, i) => {
      const isErr = (r.output || '').startsWith('执行错误');
      let typeLabel = '';
      if (r.type === 'parallel')  typeLabel = '<span style="font-size:10px;background:#fef3c7;color:#92400e;padding:2px 6px;border-radius:100px;margin-left:4px">并行</span>';
      if (r.type === 'condition') typeLabel = `<span style="font-size:10px;background:#ede9fe;color:#5b21b6;padding:2px 6px;border-radius:100px;margin-left:4px">条件${r.matched?'✓':'✗'}</span>`;
      if (r.type === 'loop')      typeLabel = `<span style="font-size:10px;background:#e0f2fe;color:#0369a1;padding:2px 6px;border-radius:100px;margin-left:4px">循环×${r.iterations||'?'}</span>`;
      return `<div class="wf-result-step">
        <div class="wf-result-hdr" onclick="this.nextElementSibling.classList.toggle('open')">
          <div class="wf-step-num" style="background:${isErr?'var(--error)':'var(--accent)'}">${r.step}</div>
          <span>${escHtml(AGENTS[r.agent]?.name || r.agent || r.type)}</span>
          ${typeLabel}
          <span style="margin-left:auto;color:var(--muted);font-size:11px">⏱ ${r.elapsed}s</span>
          <span style="color:var(--muted);font-size:12px">▼</span>
        </div>
        <div class="wf-result-body${i === res.length-1 ? ' open' : ''}">${escHtml(r.output)}</div>
      </div>`;
    }).join('');
    toast('工作流执行完成 ✓', 'success');
  } catch(e) {
    if (status) status.textContent = '执行失败';
    if (results) results.innerHTML = `<span style="color:var(--error)">${e.message}</span>`;
    toast(`运行失败: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
};

// 保存
window.wfSave = async function() {
  const name = document.getElementById('wfName')?.value.trim() || '未命名';
  if (!wfStepList.length) { toast('工作流为空', 'error'); return; }
  try {
    const r = await fetch(`${WF_API()}/save`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ id: wfCurrentId, name, steps: wfStepList }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    wfCurrentId = d.id;
    toast(`"${name}" 已保存`, 'success');
    wfLoadList();
  } catch(e) { toast(`保存失败: ${e.message}`, 'error'); }
};

// 加载已保存列表
window.wfLoadList = async function() {
  const el = document.getElementById('wfSavedList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${WF_API()}/list`);
    const { workflows } = await r.json();
    const wfs = (workflows || []).filter(w => w.type === 'workflow');
    if (!wfs.length) { el.innerHTML = '<span style="color:var(--muted)">暂无保存的工作流</span>'; return; }
    el.innerHTML = wfs.map(w => `
      <div class="wf-saved-row">
        <div class="wf-saved-name">${escHtml(w.name)}</div>
        <div class="wf-saved-meta">${(w.steps||[]).length} 步</div>
        <button class="hdr-btn-sm" onclick="wfLoad(${JSON.stringify(w).replace(/"/g,'&quot;')})">载入</button>
        <button class="kb-doc-del" onclick="wfDelete('${w.id}')">🗑</button>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

window.wfLoad = function(wf) {
  wfCurrentId = wf.id;
  wfStepList  = (wf.steps || []).map(s => ({ ...s }));
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = wf.name || '工作流';
  wfRender();
  toast(`已载入"${wf.name}"`, 'success');
};

window.wfDelete = async function(id) {
  if (!confirm('确认删除此工作流？')) return;
  try {
    await fetch(`${WF_API()}/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    wfLoadList();
  } catch(e) { toast('删除失败', 'error'); }
};

// ══════════════════════════════════════════════════
//  工作流模板库（20 个内置模板）
// ══════════════════════════════════════════════════
// 免费模板 ID（每类各 1 个基础款，其余 Pro 专属）
const WF_FREE_TEMPLATES = new Set([
  'tpl_daily_news',     // 内容
  'tpl_market_research',// 调研
  'tpl_code_review',    // 代码
  'tpl_meeting_summary',// 商业
]);

const WF_TEMPLATES = [
  // ── 内容创作 ──────────────────────────────────────
  {
    id: 'tpl_daily_news',
    name: '📰 AI 新闻日报',
    desc: '搜索 AI 前沿动态，写手提炼摘要，评审把关质量',
    category: 'content', icon: '📰',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'搜索今天最重要的 5 条 AI / 科技新闻，给出标题和 2 句话摘要', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'将以下新闻整理成一份简洁的日报，适合微信群分享，风格轻松有趣', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'检查日报的准确性和可读性，给出最终版本', pass_context:true },
    ],
  },
  {
    id: 'tpl_blog_post',
    name: '✍️ 长文章创作',
    desc: '调研主题 → 写手撰稿 → 评审润色 → 输出成品',
    category: 'content', icon: '✍️',
    steps: [
      { type:'sequential', agent:'reader',  prompt:'研究以下主题，整理关键要点和写作角度：{{主题}}', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'根据上面的调研，写一篇 1500 字的深度文章，包含引言、3 个主体段落、结语', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'对文章进行润色：提升文采、修正逻辑、增加例子，输出最终版', pass_context:true },
    ],
  },
  {
    id: 'tpl_social_content',
    name: '📱 社媒内容矩阵',
    desc: '一键生成微博、小红书、朋友圈三种风格的内容',
    category: 'content', icon: '📱',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'将以下核心内容整理成 3 个关键信息点：{{内容要点}}', pass_context:false },
      { type:'parallel', branches: [
        { agent:'writer', prompt:'根据关键信息点写一条微博（140字内，时事评论风格）', pass_context:true },
        { agent:'writer', prompt:'根据关键信息点写一篇小红书笔记（300字，加 emoji，分点）', pass_context:true },
        { agent:'writer', prompt:'根据关键信息点写一条朋友圈（100字内，生活化表达）', pass_context:true },
      ]},
    ],
  },
  {
    id: 'tpl_product_review',
    name: '🔍 产品评测报告',
    desc: '阅读者收集资料，写手撰写评测，评审打分',
    category: 'content', icon: '🔍',
    steps: [
      { type:'sequential', agent:'reader',  prompt:'搜集关于 {{产品名称}} 的用户评价、专业测评、规格参数', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'撰写一篇产品评测报告：外观、性能、使用体验、性价比各维度分析', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'补充不足、给出综合评分（满分10分）和购买建议', pass_context:true },
    ],
  },

  // ── 调研分析 ──────────────────────────────────────
  {
    id: 'tpl_market_research',
    name: '📊 市场调研分析',
    desc: '陶朱主导：竞品分析 + 市场规模 + 机会洞察',
    category: 'research', icon: '📊',
    steps: [
      { type:'sequential', agent:'xi',   prompt:'收集 {{行业/产品}} 的市场数据：市场规模、主要玩家、增长趋势', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'对竞品进行 SWOT 分析，找出市场空白和差异化机会', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'整理成一份 CEO 级别的市场洞察报告，有图表建议', pass_context:true },
    ],
  },
  {
    id: 'tpl_user_research',
    name: '👥 用户访谈分析',
    desc: '整理用户反馈，提炼需求，生成产品洞察',
    category: 'research', icon: '👥',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'阅读以下用户访谈记录，提炼关键痛点和需求：{{访谈内容}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'基于用户洞察，分析这些需求的商业价值，按优先级排序', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成用户研究报告，包括用户画像、核心诉求、产品建议', pass_context:true },
    ],
  },
  {
    id: 'tpl_tech_research',
    name: '🔬 技术选型调研',
    desc: '对比技术方案，给出选型建议',
    category: 'research', icon: '🔬',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'调研 {{技术领域}} 的主流方案，收集各方案的优缺点、社区活跃度、生产案例', pass_context:false },
      { type:'sequential', agent:'reader',  prompt:'深入对比每个方案的技术细节：性能、学习曲线、生态', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'结合具体场景给出最终选型建议，说明理由', pass_context:true },
    ],
  },
  {
    id: 'tpl_weekly_summary',
    name: '📋 周工作总结',
    desc: '整理本周工作亮点，生成周报和下周计划',
    category: 'research', icon: '📋',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'整理以下工作记录，提炼本周完成事项、遇到的挑战：{{工作内容}}', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'撰写专业的周报：本周完成、关键进展、遇到的问题', pass_context:true },
      { type:'sequential', agent:'tianyuan',prompt:'基于本周情况，制定下周优先级和计划', pass_context:true },
    ],
  },

  // ── 代码开发 ──────────────────────────────────────
  {
    id: 'tpl_code_review',
    name: '💻 代码审查',
    desc: '读取代码，发现问题，生成改进建议',
    category: 'code', icon: '💻',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'阅读以下代码，理解其功能和架构：\n```\n{{代码}}\n```', pass_context:false },
      { type:'sequential', agent:'critic',   prompt:'对代码进行 Code Review：安全漏洞、性能问题、可读性、最佳实践', pass_context:true },
      { type:'sequential', agent:'executor', prompt:'对每个问题给出具体的修复代码示例', pass_context:true },
    ],
  },
  {
    id: 'tpl_bug_fix',
    name: '🐛 Bug 排查修复',
    desc: '分析错误日志，定位问题，生成修复方案',
    category: 'code', icon: '🐛',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'分析以下错误信息和日志，理解报错原因：\n{{错误信息}}', pass_context:false },
      { type:'sequential', agent:'executor', prompt:'根据错误原因，给出 3 种可能的修复方案和代码示例', pass_context:true },
      { type:'sequential', agent:'critic',   prompt:'评估每种方案的可行性，推荐最佳方案并说明理由', pass_context:true },
    ],
  },
  {
    id: 'tpl_api_design',
    name: '🔌 API 接口设计',
    desc: '需求分析 → API 设计 → 接口文档生成',
    category: 'code', icon: '🔌',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'分析以下业务需求，梳理需要的核心功能：{{业务需求}}', pass_context:false },
      { type:'sequential', agent:'executor', prompt:'设计 RESTful API 接口：路径、方法、请求/响应格式、状态码', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成 OpenAPI 格式的接口文档，包含示例', pass_context:true },
    ],
  },
  {
    id: 'tpl_test_generation',
    name: '🧪 测试用例生成',
    desc: '分析代码，自动生成单元测试和边界测试',
    category: 'code', icon: '🧪',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'理解以下函数/模块的功能和边界条件：\n{{代码}}\n', pass_context:false },
      { type:'sequential', agent:'executor', prompt:'生成全面的单元测试：正常流程、边界值、异常情况', pass_context:true },
      { type:'sequential', agent:'critic',   prompt:'检查测试覆盖率是否充分，补充遗漏的测试场景', pass_context:true },
    ],
  },

  // ── 商业决策 ──────────────────────────────────────
  {
    id: 'tpl_business_plan',
    name: '💼 商业计划书',
    desc: '陶朱主导：市场 + 产品 + 财务 + 执行计划',
    category: 'business', icon: '💼',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'基于以下创业想法，分析市场机会和商业模式：{{创业想法}}', pass_context:false },
      { type:'parallel', branches: [
        { agent:'tianyuan', prompt:'撰写市场分析和竞争策略章节', pass_context:true },
        { agent:'writer',   prompt:'撰写产品介绍和用户价值主张章节', pass_context:true },
      ]},
      { type:'sequential', agent:'tianyuan', prompt:'整合以上内容，加上执行路线图和融资需求，完成完整商业计划书', pass_context:true },
    ],
  },
  {
    id: 'tpl_investment_memo',
    name: '📈 投资分析备忘录',
    desc: '对项目/公司做深度投资价值分析',
    category: 'business', icon: '📈',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'收集关于 {{项目/公司}} 的公开信息：团队、产品、融资历史、市场', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'进行投资价值分析：市场规模、竞争壁垒、团队能力、风险点', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成投资备忘录（Investment Memo），专业风格，含推荐结论', pass_context:true },
    ],
  },
  {
    id: 'tpl_customer_email',
    name: '📧 客户沟通邮件',
    desc: '分析情况，生成专业的客户邮件',
    category: 'business', icon: '📧',
    steps: [
      { type:'sequential', agent:'xi',  prompt:'理解以下客户沟通背景：{{背景情况}}', pass_context:false },
      { type:'sequential', agent:'writer',  prompt:'撰写专业的客户邮件：语气得体、逻辑清晰、有行动项', pass_context:true },
      { type:'sequential', agent:'critic',  prompt:'检查邮件的语气、礼貌程度、是否可能引起误解，输出最终版', pass_context:true },
    ],
  },
  {
    id: 'tpl_okr_planning',
    name: '🎯 OKR 目标规划',
    desc: '基于战略方向，制定季度 OKR',
    category: 'business', icon: '🎯',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'分析以下战略方向，确定本季度最重要的 3 个优先级：{{战略方向}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'为每个优先级制定 OKR：1 个 Objective + 3 个可量化的 Key Results', pass_context:true },
      { type:'sequential', agent:'critic',   prompt:'检查 OKR 是否符合 SMART 原则，给出改进建议', pass_context:true },
    ],
  },
  {
    id: 'tpl_meeting_summary',
    name: '📝 会议纪要整理',
    desc: '从会议记录中提炼决策、行动项、负责人',
    category: 'business', icon: '📝',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'阅读以下会议记录，理解讨论的议题：{{会议记录}}', pass_context:false },
      { type:'sequential', agent:'writer',   prompt:'整理会议纪要：关键决策、行动项（含负责人和截止日期）、待跟进事项', pass_context:true },
    ],
  },
  {
    id: 'tpl_negotiation_prep',
    name: '🤝 谈判准备',
    desc: '分析谈判对手，制定策略，准备论点',
    category: 'business', icon: '🤝',
    steps: [
      { type:'sequential', agent:'reader',   prompt:'研究谈判对方的背景、诉求、历史行为：{{对方信息}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'制定谈判策略：目标区间、让步底线、关键论点、可能的反对意见及应对', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'生成谈判准备清单和开场白脚本', pass_context:true },
    ],
  },
  {
    id: 'tpl_crisis_response',
    name: '🚨 危机应对方案',
    desc: '快速生成危机处理预案和对外声明',
    category: 'business', icon: '🚨',
    steps: [
      { type:'sequential', agent:'tianyuan', prompt:'分析以下危机情况的严重程度和影响范围：{{危机描述}}', pass_context:false },
      { type:'condition', keyword:'严重',
        true_step:  { agent:'tianyuan', prompt:'制定紧急应对方案：立即行动项、对外沟通策略、后续修复计划' },
        false_step: { agent:'xi',   prompt:'制定常规处理预案：内部通报、改进措施、预防复发' },
      },
      { type:'sequential', agent:'writer',   prompt:'生成对外公告或内部通报初稿', pass_context:true },
    ],
  },
  {
    id: 'tpl_personal_growth',
    name: '🌱 个人成长计划',
    desc: '晞 + 陶朱联手制定个人发展路径',
    category: 'business', icon: '🌱',
    steps: [
      { type:'sequential', agent:'yiyi',     prompt:'了解用户当前状态、困惑和对未来的期望：{{个人现状}}', pass_context:false },
      { type:'sequential', agent:'tianyuan', prompt:'基于用户的现状和目标，制定 90 天个人成长计划：技能、习惯、里程碑', pass_context:true },
      { type:'sequential', agent:'writer',   prompt:'输出一份激励人心的个人成长方案，包括每周行动指引', pass_context:true },
    ],
  },
];

let _wfTplCat = 'all';
let _membershipPro = false; // 缓存会员状态供模板库用

async function _refreshMembershipCache() {
  try {
    const r = await fetch(`${CONFIG.api}/membership/status`);
    const m = await r.json();
    _membershipPro = m.active && m.tier === 'pro';
  } catch(_) { _membershipPro = false; }
}

// 渲染模板库
function wfRenderTemplates() {
  const grid = document.getElementById('wfTemplateGrid');
  if (!grid) return;
  const filtered = _wfTplCat === 'all'
    ? WF_TEMPLATES
    : WF_TEMPLATES.filter(t => t.category === _wfTplCat);

  grid.innerHTML = filtered.map(t => {
    const isPremium = !WF_FREE_TEMPLATES.has(t.id);
    const isLocked = isPremium && !_membershipPro;
    return `
    <div class="wf-tpl-card${isLocked?' locked':''}" onclick="wfLoadTemplate('${t.id}')" data-premium="${isPremium}">
      <span class="wf-tpl-icon">${t.icon}</span>
      <div class="wf-tpl-info">
        <div class="wf-tpl-name">${escHtml(t.name)}${isPremium?'<span class="skill-premium-badge">Pro</span>':''}</div>
        <div class="wf-tpl-desc">${escHtml(t.desc)}</div>
      </div>
      <span class="wf-tpl-steps">${t.steps.length}步</span>
    </div>`;
  }).join('');
}

window.wfTplFilter = function(cat, btn) {
  _wfTplCat = cat;
  document.querySelectorAll('.wf-tpl-filter').forEach(b => b.classList.remove('active'));
  btn?.classList.add('active');
  wfRenderTemplates();
};

window.wfLoadTemplate = function(id) {
  const tpl = WF_TEMPLATES.find(t => t.id === id);
  if (!tpl) return;
  // Pro 门控
  if (!WF_FREE_TEMPLATES.has(id) && !_membershipPro) {
    toast('🔒 此模板为 Pro 专属，请在设置页激活会员', 'info');
    return;
  }
  wfStepList.length = 0;
  tpl.steps.forEach(s => wfStepList.push(JSON.parse(JSON.stringify(s)))); // 深拷贝
  window._wfStepsData = wfStepList;
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = tpl.name;
  document.getElementById('wfResults').innerHTML = '';
  document.getElementById('wfRunStatus').textContent = '模板已加载，填写 {{占位符}} 后运行';
  wfRender();
  if (typeof renderWfCanvas === 'function') renderWfCanvas(wfStepList);
  toast(`✅ 模板已加载：${tpl.name}`, 'success');
};

// 切换到工作流 tab 时初始化模板库
const _origSwitchTabWf = window.switchTab;

// ── 在 switchTab 中注入模板初始化 ──
const _wfTabInit_orig = window.switchTab;
(function() {
  const _prev = window.switchTab;
  if (_prev) {
    window.switchTab = function(tabId, el) {
      _prev(tabId, el);
      if (tabId === 'workflow') {
        setTimeout(wfRenderTemplates, 50);
      }
    };
  }
})();

// 首次加载时也渲染
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(wfRenderTemplates, 500);
});

// ══════════════════════════════════════════════════
//  定时任务 UI
// ══════════════════════════════════════════════════
const SCHED_API = () => `${CONFIG.api}/scheduler`;

window.schedTriggerTypeChange = function() {
  const t    = document.getElementById('schedTriggerType')?.value;
  const hint = document.getElementById('schedTriggerHint');
  const val  = document.getElementById('schedTriggerValue');
  if (!hint || !val) return;
  if (t === 'interval') {
    hint.textContent = '间隔：30m=每30分钟、2h=每2小时、1d=每天';
    val.placeholder = '1h / 30m / 1d';
    val.value = '1h';
  } else {
    hint.textContent = '固定时间：09:00=每天9点，或标准 cron "0 9 * * 1-5"';
    val.placeholder = '09:00';
    val.value = '09:00';
  }
};

window.schedAdd = async function() {
  const name    = document.getElementById('schedName')?.value.trim();
  const agent   = document.getElementById('schedAgent')?.value;
  const prompt  = document.getElementById('schedPrompt')?.value.trim();
  const tType   = document.getElementById('schedTriggerType')?.value;
  const tVal    = document.getElementById('schedTriggerValue')?.value.trim();
  if (!name || !prompt || !tVal) { toast('请填写所有必填字段', 'error'); return; }
  try {
    const r = await fetch(`${SCHED_API()}/tasks`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, agent, prompt, trigger_type: tType, trigger_value: tVal }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`✓ "${name}" 已创建`, 'success');
    document.getElementById('schedName').value   = '';
    document.getElementById('schedPrompt').value = '';
    schedLoadTasks();
  } catch(e) { toast(`创建失败: ${e.message}`, 'error'); }
};

window.schedLoadTasks = async function() {
  const el = document.getElementById('schedTaskList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${SCHED_API()}/tasks`);
    const { tasks } = await r.json();
    if (!tasks.length) { el.innerHTML = '<span style="color:var(--muted)">暂无任务</span>'; return; }
    el.innerHTML = tasks.map(t => {
      const triggerLabel = t.trigger_type === 'interval'
        ? `每 ${t.trigger_value}`
        : `每天 ${t.trigger_value}`;
      return `
        <div class="sched-task-row">
          <div class="sched-task-led ${t.enabled ? 'on' : 'off'}"></div>
          <div style="flex:1">
            <div style="font-weight:600;font-size:13px">${escHtml(t.name)}</div>
            <div style="font-size:11px;color:var(--muted)">${AGENTS[t.agent]?.icon||''} ${t.agent} · ${triggerLabel} · 执行 ${t.run_count} 次</div>
          </div>
          <div style="display:flex;gap:4px">
            <button class="hdr-btn-sm" onclick="schedRunNow('${t.id}')" title="立即执行">▶</button>
            <button class="hdr-btn-sm" onclick="schedToggle('${t.id}')">${t.enabled ? '暂停' : '启用'}</button>
            <button class="kb-doc-del" onclick="schedDelete('${t.id}')">🗑</button>
          </div>
        </div>`;
    }).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

window.schedToggle = async function(id) {
  try {
    await fetch(`${SCHED_API()}/tasks/${id}/toggle`, { method:'POST' });
    schedLoadTasks();
  } catch(e) { toast('操作失败', 'error'); }
};

window.schedDelete = async function(id) {
  if (!confirm('确认删除此任务？')) return;
  try {
    await fetch(`${SCHED_API()}/tasks/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    schedLoadTasks();
  } catch(e) { toast('删除失败', 'error'); }
};

window.schedRunNow = async function(id) {
  try {
    await fetch(`${SCHED_API()}/tasks/${id}/run`, { method:'POST' });
    toast('已触发执行，稍后查看日志', 'success');
    setTimeout(schedLoadLogs, 3000);
  } catch(e) { toast('触发失败', 'error'); }
};

window.schedLoadLogs = async function() {
  const el = document.getElementById('schedLogList');
  if (!el) return;
  try {
    const r = await fetch(`${SCHED_API()}/logs?limit=30`);
    const { logs } = await r.json();
    if (!logs.length) { el.innerHTML = '<span style="color:var(--muted)">暂无日志</span>'; return; }
    el.innerHTML = logs.map(l => `
      <div style="border-bottom:1px solid var(--border);padding:7px 4px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
          <span style="font-size:12px">${l.ok ? '✅' : '❌'}</span>
          <span style="font-weight:600;font-size:12px">${escHtml(l.task_name)}</span>
          <span style="font-size:11px;color:var(--muted);margin-left:auto">${l.started.slice(0,16).replace('T',' ')}</span>
        </div>
        <div style="font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
          ${escHtml((l.output||'').slice(0,120))}
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

// ══════════════════════════════════════════════════
//  文件监视器 UI
// ══════════════════════════════════════════════════
const FW_API = () => `${CONFIG.api}/watcher`;

window.fwAdd = async function() {
  const name   = document.getElementById('fwName')?.value.trim();
  const path   = document.getElementById('fwPath')?.value.trim();
  const pattern= document.getElementById('fwPattern')?.value.trim() || '*';
  const agent  = document.getElementById('fwAgent')?.value;
  const prompt = document.getElementById('fwPrompt')?.value.trim();
  const evts   = [];
  if (document.getElementById('fwEvtCreate')?.checked) evts.push('created');
  if (document.getElementById('fwEvtModify')?.checked) evts.push('modified');
  if (document.getElementById('fwEvtDelete')?.checked) evts.push('deleted');
  if (!name || !path || !prompt) { toast('请填写规则名称、路径和提示词', 'error'); return; }
  if (!evts.length) { toast('请选择至少一种触发事件', 'error'); return; }
  try {
    const r = await fetch(`${FW_API()}/rules`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, watch_path:path, pattern, events:evts, agent, prompt_template:prompt }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`✓ "${name}" 已创建`, 'success');
    fwLoadRules();
  } catch(e) { toast(`创建失败: ${e.message}`, 'error'); }
};

window.fwLoadRules = async function() {
  const el = document.getElementById('fwRuleList');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--muted)">加载中…</span>';
  try {
    const r = await fetch(`${FW_API()}/rules`);
    const { rules } = await r.json();
    if (!rules.length) { el.innerHTML = '<span style="color:var(--muted)">暂无规则</span>'; return; }
    el.innerHTML = rules.map(rule => `
      <div class="sched-task-row">
        <div class="sched-task-led ${rule.enabled ? 'on' : 'off'}"></div>
        <div style="flex:1">
          <div style="font-weight:600;font-size:13px">${escHtml(rule.name)}</div>
          <div style="font-size:11px;color:var(--muted)">${escHtml(rule.watch_path)} · ${rule.pattern} · ${(rule.events||[]).join('/')} · ${rule.trigger_count||0}次触发</div>
        </div>
        <div style="display:flex;gap:4px">
          <button class="hdr-btn-sm" onclick="fwToggle('${rule.id}')">${rule.enabled?'暂停':'启用'}</button>
          <button class="kb-doc-del" onclick="fwDelete('${rule.id}')">🗑</button>
        </div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

window.fwToggle = async function(id) {
  try {
    await fetch(`${FW_API()}/rules/${id}/toggle`, { method:'POST' });
    fwLoadRules();
  } catch(e) { toast('操作失败', 'error'); }
};

window.fwDelete = async function(id) {
  if (!confirm('确认删除此监视规则？')) return;
  try {
    await fetch(`${FW_API()}/rules/${id}`, { method:'DELETE' });
    toast('已删除', 'success');
    fwLoadRules();
  } catch(e) { toast('删除失败', 'error'); }
};

window.fwLoadEvents = async function() {
  const el = document.getElementById('fwEventList');
  if (!el) return;
  try {
    const r = await fetch(`${FW_API()}/events?limit=30`);
    const { events } = await r.json();
    if (!events.length) { el.innerHTML = '<span style="color:var(--muted)">暂无触发事件</span>'; return; }
    el.innerHTML = events.map(e => `
      <div style="border-bottom:1px solid var(--border);padding:7px 4px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
          <span>${e.ok ? '✅' : '❌'}</span>
          <span style="font-weight:600;font-size:12px">${escHtml(e.rule_name)}</span>
          <span class="model-tag" style="font-size:10px">${e.event}</span>
          <span style="font-size:11px;color:var(--muted);margin-left:auto">${e.started.slice(0,16).replace('T',' ')}</span>
        </div>
        <div style="font-size:11px;color:var(--muted)">${escHtml(e.path)}</div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span style="color:var(--error)">${e.message}</span>`; }
};

// ══════════════════════════════════════════════════
//  多 Agent 群聊 UI
// ══════════════════════════════════════════════════
const GC_AGENT_META = {
  xi:       { icon:'👩‍💼', avatarImg:'assets/xi-avatar.png', cls:'xi-bg'   },
  yiyi:     { icon:'🌸',  cls:'yiyi-bg'     },
  tianyuan: { icon:'🏢',  cls:'tianyuan-bg' },
  shoucang:  { icon:'📜',  cls:'shoucang-bg' },
  executor: { icon:'⚡',  cls:'executor-bg' },
  writer:   { icon:'✍️',  cls:'writer-bg'   },
  reader:   { icon:'📖',  cls:'reader-bg'   },
  critic:   { icon:'🔍',  cls:'critic-bg'   },
};

// ══════════════════════════════════════════════════
//  Agent 配置（名称 / 音色） — 全局存储
// ══════════════════════════════════════════════════
let agentNames  = {};   // {xi:'Anima', yiyi:'晞', ...}
let agentVoices = {};   // {xi:'zh-CN-YunxiNeural', ...}

const DEFAULT_AGENT_META = {
  xi:       { icon:'👩‍💼', avatarImg:'assets/xi-avatar.png', cls:'xi-bg'   },
  yiyi:     { icon:'🌸',  cls:'yiyi-bg'     },
  tianyuan: { icon:'🏢',  cls:'tianyuan-bg' },
  shoucang:  { icon:'📜',  cls:'shoucang-bg' },
  executor: { icon:'⚡',  cls:'executor-bg' },
  writer:   { icon:'✍️',  cls:'writer-bg'   },
  reader:   { icon:'📖',  cls:'reader-bg'   },
  critic:   { icon:'🔍',  cls:'critic-bg'   },
};

const DEFAULT_AGENT_NAMES = {
  xi:'Anima', yiyi:'晞', tianyuan:'陶朱', shoucang:'守藏',
  executor:'执行者', writer:'写手', reader:'阅读者', critic:'评审',
};

async function loadAgentConfig() {
  try {
    const r = await fetch(`${CONFIG.api}/config/agents`);
    if (!r.ok) return;
    const { voices } = await r.json();  // 只取 voices，不取 names
    agentVoices = { ...voices };
  } catch(_) {}
  agentNames = { ...DEFAULT_AGENT_NAMES };  // 始终用 DEFAULT（固定名称）
}

function agentName(id) { return agentNames[id] || DEFAULT_AGENT_NAMES[id] || id; }

function applyAgentNames() {
  // 更新侧边栏导航显示名称
  const navMap = {
    xi:       '[data-tab=xi]',
    yiyi:     '[data-tab=yiyi]',
    tianyuan: '[data-tab=tianyuan]',
    shoucang: '[data-tab=shoucang]',
  };
  for (const [id, sel] of Object.entries(navMap)) {
    const el = document.querySelector(sel);
    if (el) {
      const icon = el.querySelector('.nav-icon')?.outerHTML || '';
      const dot  = el.querySelector('.agent-dot')?.outerHTML || '';
      el.innerHTML = `${icon}${agentName(id)}${dot}`;
    }
  }
  // 更新群聊成员面板
  gcRenderMembers();
}

// ══════════════════════════════════════════════════
//  TTS 语音播放
// ══════════════════════════════════════════════════
let _ttsQueue = [];
let _ttsPlaying = false;

async function ttsSpeak(text, agentId = 'xi') {
  if (!text || text.length < 3) return;
  _ttsQueue.push({ text, agentId });
  if (!_ttsPlaying) _ttsNext();
}

async function _ttsNext() {
  if (!_ttsQueue.length) { _ttsPlaying = false; return; }
  _ttsPlaying = true;
  const { text, agentId } = _ttsQueue.shift();
  const player = document.getElementById('ttsPlayer');
  try {
    const r = await fetch(`${CONFIG.api}/tts`, {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ text: text.slice(0, 400), agent: agentId }),
    });
    if (!r.ok) { _ttsPlaying = false; _ttsNext(); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    player.src = url;
    player.onended = () => { URL.revokeObjectURL(url); _ttsNext(); };
    player.onerror = () => { _ttsPlaying = false; _ttsNext(); };
    await player.play();
  } catch(_) { _ttsPlaying = false; _ttsNext(); }
}

window.ttsStop = function() {
  _ttsQueue = [];
  _ttsPlaying = false;
  const p = document.getElementById('ttsPlayer');
  if (p) { p.pause(); p.src = ''; }
};


// ══════════════════════════════════════════════════
//  群聊 — 飞书/微信风格
// ══════════════════════════════════════════════════
// 群聊状态
const GC_STATE = {
  selectedAgents: new Set(['xi', 'shoucang']),
  messages: [],
  isRunning: false,
  recognition: null,
};

function gcRenderMembers() {
  const el = document.getElementById('gcMembers');
  if (!el) return;
  const allAgents = ['xi','yiyi','tianyuan','shoucang','executor','writer','reader','critic'];
  el.innerHTML = allAgents.map(id => {
    const meta    = DEFAULT_AGENT_META[id];
    const name    = agentName(id);
    const checked = GC_STATE.selectedAgents.has(id);
    return `
      <div class="gc-member ${checked?'':'inactive'}" onclick="gcToggleMember('${id}',this)">
        <div class="gc-member-avatar ${meta.cls}">${meta.icon}</div>
        <div class="gc-member-name">${name}</div>
        <div class="gc-member-check">✓</div>
      </div>`;
  }).join('');

  // Update group meta
  const metaEl = document.getElementById('gcGroupMeta');
  if (metaEl) metaEl.textContent = `${GC_STATE.selectedAgents.size} 位成员`;
}

window.gcToggleMember = function(id, el) {
  if (GC_STATE.selectedAgents.has(id)) {
    if (GC_STATE.selectedAgents.size <= 2) { toast('至少保留 2 个成员', 'error'); return; }
    GC_STATE.selectedAgents.delete(id);
    el.classList.add('inactive');
  } else {
    GC_STATE.selectedAgents.add(id);
    el.classList.remove('inactive');
  }
  const metaEl = document.getElementById('gcGroupMeta');
  if (metaEl) metaEl.textContent = `${GC_STATE.selectedAgents.size} 位成员`;
};

function gcAddMessage(msgData) {
  const container = document.getElementById('gcMessages');
  if (!container) return;

  // Remove welcome screen
  const welcome = container.querySelector('.gc-welcome');
  if (welcome) welcome.remove();

  const { agent, name, content, round, elapsed, isTyping } = msgData;
  const meta = DEFAULT_AGENT_META[agent] || { icon:'🤖', cls:'' };
  const displayName = name || agentName(agent);

  if (isTyping) {
    // Remove existing typing for this agent
    container.querySelector(`.gc-typing[data-agent="${agent}"]`)?.remove();
    const div = document.createElement('div');
    div.className = 'gc-typing';
    div.dataset.agent = agent;
    div.innerHTML = `
      <div class="gc-typing-avatar ${meta.cls}">${meta.icon}</div>
      <div>
        <div style="font-size:11px;color:var(--muted);margin-bottom:4px">${displayName}</div>
        <div class="gc-typing-dots">
          <div class="gc-typing-dot"></div>
          <div class="gc-typing-dot"></div>
          <div class="gc-typing-dot"></div>
        </div>
      </div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
  }

  // Remove typing indicator for this agent
  container.querySelector(`.gc-typing[data-agent="${agent}"]`)?.remove();

  const now = new Date().toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
  const msgId = `gcmsg-${Date.now()}-${Math.random().toString(36).slice(2,6)}`;

  const div = document.createElement('div');
  div.className = 'gc-msg';
  div.id = msgId;
  div.innerHTML = `
    ${meta.avatarImg
      ? `<div class="gc-msg-avatar ${meta.cls} msg-avatar-img"><img src="${meta.avatarImg}" alt="${agentId}" onerror="this.parentElement.innerHTML='${meta.icon}';this.parentElement.classList.remove('msg-avatar-img')"></div>`
      : `<div class="gc-msg-avatar ${meta.cls}">${meta.icon}</div>`
    }
    <div class="gc-msg-body">
      <div class="gc-msg-header">
        <span class="gc-msg-name">${displayName}</span>
        <span class="gc-msg-time">${now}${round ? ` · 第${round}轮` : ''}</span>
      </div>
      <div class="gc-msg-bubble">${escHtml(content)}</div>
      <div class="gc-msg-actions">
        <button class="gc-msg-action-btn" onclick="ttsSpeak(${JSON.stringify(content)}, '${agent}')">🔊 播放</button>
        <button class="gc-msg-action-btn" onclick="navigator.clipboard.writeText(${JSON.stringify(content)});toast('已复制','success')">📋 复制</button>
        ${elapsed ? `<span style="font-size:11px;color:var(--muted);padding:3px 6px">⏱ ${elapsed}s</span>` : ''}
      </div>
    </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

window.gcRun = async function() {
  const topic = document.getElementById('gcTopic')?.value.trim();
  if (!topic) { toast('请输入讨论主题', 'error'); return; }

  const agents = Array.from(GC_STATE.selectedAgents);
  if (agents.length < 2) { toast('请至少选择 2 个成员', 'error'); return; }

  const rounds = parseInt(document.getElementById('gcRounds')?.value || '1');
  const btn    = document.getElementById('gcRunBtn');
  if (btn) btn.disabled = true;
  GC_STATE.isRunning = true;

  // Show topic as divider
  const container = document.getElementById('gcMessages');
  if (container) {
    const welcome = container.querySelector('.gc-welcome');
    if (welcome) welcome.remove();
    const divEl = document.createElement('div');
    divEl.className = 'gc-divider';
    divEl.textContent = topic.length > 40 ? topic.slice(0,40)+'…' : topic;
    container.appendChild(divEl);
  }

  // Show typing indicators immediately
  for (const id of agents) {
    gcAddMessage({ agent: id, isTyping: true });
  }

  try {
    const r = await fetch(`${CONFIG.api}/groupchat/run`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ topic, agents, rounds }),
    });
    const { messages, error } = await r.json();
    if (error) throw new Error(error);

    // Remove all typing indicators
    container?.querySelectorAll('.gc-typing').forEach(el => el.remove());

    // Render messages
    const autoTts = document.getElementById('gcAutoTts')?.checked;
    for (const m of messages) {
      gcAddMessage(m);
      GC_STATE.messages.push(m);
      if (autoTts) await ttsSpeak(m.content, m.agent);
    }

    toast('讨论完成 ✓', 'success');
  } catch(e) {
    container?.querySelectorAll('.gc-typing').forEach(el => el.remove());
    gcAddMessage({ agent:'xi', name:'系统', content:`发生错误：${e.message}` });
    toast(`群聊失败: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    GC_STATE.isRunning = false;
    // Clear input
    const input = document.getElementById('gcTopic');
    if (input) input.value = '';
  }
};

window.gcKeydown = function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    gcRun();
  }
};

window.gcClearMessages = function() {
  const el = document.getElementById('gcMessages');
  if (!el) return;
  el.innerHTML = `
    <div class="gc-welcome">
      <div class="gc-welcome-icon">🤝</div>
      <div class="gc-welcome-title">欢迎来到 Anima 群聊</div>
      <div class="gc-welcome-sub">在下方输入讨论话题，让多个 Agent 一起讨论</div>
    </div>`;
  GC_STATE.messages = [];
};

window.gcExport = function() {
  if (!GC_STATE.messages.length) { toast('暂无消息可导出', 'error'); return; }
  const text = GC_STATE.messages.map(m =>
    `【${agentName(m.agent)}】${m.content}\n`
  ).join('\n');
  navigator.clipboard.writeText(text);
  toast('群聊记录已复制到剪贴板 ✓', 'success');
};

// Voice input
let _gcRecognition = null;
window.gcToggleVoice = function() {
  const btn = document.getElementById('gcVoiceBtn');
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) { toast('此浏览器不支持语音输入', 'error'); return; }

  if (_gcRecognition) {
    _gcRecognition.stop();
    _gcRecognition = null;
    if (btn) btn.classList.remove('recording');
    return;
  }
  const rec = new SpeechRecognition();
  rec.lang = 'zh-CN'; rec.interimResults = false; rec.maxAlternatives = 1;
  rec.onresult = (e) => {
    const t = e.results[0][0].transcript;
    const input = document.getElementById('gcTopic');
    if (input) input.value = (input.value ? input.value + '，' : '') + t;
  };
  rec.onend = () => {
    _gcRecognition = null;
    if (btn) btn.classList.remove('recording');
  };
  rec.onerror = () => { _gcRecognition = null; if(btn) btn.classList.remove('recording'); };
  rec.start();
  _gcRecognition = rec;
  if (btn) btn.classList.add('recording');
  toast('🎤 正在录音，说话后自动停止', 'info');
};

window.gcInsertEmoji = function() {
  const emojis = ['😊','👍','🎯','💡','🚀','⚡','🌟','📝','🤔','✅'];
  const input = document.getElementById('gcTopic');
  if (!input) return;
  input.value += emojis[Math.floor(Math.random() * emojis.length)];
  input.focus();
};

window.gcSaveSettings = function() {
  // Settings are applied in real time via checkbox
};

// ══════════════════════════════════════════════════

// ════════════════════════════════════════════════════
//  工作流 AI 辅助
// ════════════════════════════════════════════════════
window.wfAiAssist = function() {
  const panel = document.getElementById('wfAiPanel');
  if (panel) panel.style.display = panel.style.display === 'none' ? '' : 'none';
};

window.wfAiGenerate = async function() {
  const desc   = document.getElementById('wfAiDesc')?.value.trim();
  const status = document.getElementById('wfAiStatus');
  if (!desc) return;
  if (status) status.textContent = '⏳ Anima 正在思考…';

  // 构造提示词，让 Anima 以 JSON 格式返回工作流步骤
  const systemPrompt = `用户描述了一个工作流目标，请你返回一个 JSON 数组，每项格式为：
{"agent":"xi|yiyi|tianyuan|shoucang|executor|writer|reader|critic","prompt":"给该 Agent 的指令","pass_context":true}
只返回 JSON 数组，不要解释。`;

  try {
    // 直接通过 Anima WS 让 Anima 生成工作流
    const ws = wsConns['xi'];
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (status) status.textContent = '❌ Anima 未连接';
      return;
    }

    const sid = `wf-ai-${Date.now()}`;
    ws.send(JSON.stringify({
      action: 'chat',
      message: `${systemPrompt}\n\n用户目标：${desc}`,
      session_id: sid,
    }));

    // 监听一次性响应
    const handler = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'response' && msg.data?.summary) {
          ws.removeEventListener('message', handler);
          // 尝试解析 JSON
          const json = msg.data.summary.match(/\[[\s\S]*\]/)?.[0];
          if (json) {
            const steps = JSON.parse(json);
            wfLoadFromSteps(steps);
            if (status) status.textContent = `✅ 已生成 ${steps.length} 个步骤`;
            document.getElementById('wfAiPanel').style.display = 'none';
          } else {
            if (status) status.textContent = '❌ 无法解析工作流，请重试';
          }
        }
      } catch(_) {}
    };
    ws.addEventListener('message', handler);
    setTimeout(() => ws.removeEventListener('message', handler), 30000);
  } catch(e) {
    if (status) status.textContent = `❌ 错误: ${e.message}`;
  }
};

// 从步骤数组加载工作流到可视化画布
function wfLoadFromSteps(steps) {
  wfStepList.length = 0;
  steps.forEach(s => wfStepList.push(s));
  window._wfStepsData = wfStepList;
  renderWfCanvas(wfStepList);
}

// 渲染可视化工作流画布
function renderWfCanvas(steps) {
  const canvas = document.getElementById('wfCanvas');
  if (!canvas) return;
  const agentInfo = {
    xi:       { icon:'👩‍💼', name:'Anima' },
    yiyi:     { icon:'🌸',  name:'晞'   },
    tianyuan: { icon:'🏢',  name:'陶朱'   },
    shoucang: { icon:'📜', name:'守藏'  },
    executor: { icon:'⚡',  name:'执行者' },
    writer:   { icon:'✍️',  name:'写手'   },
    reader:   { icon:'📖',  name:'阅读者' },
    critic:   { icon:'🔍',  name:'评审'   },
  };

  if (!steps.length) {
    canvas.innerHTML = `
      <div class="es-workflow-empty">
        <div style="font-size:40px;margin-bottom:10px">⚡</div>
        <div style="font-weight:700;font-size:15px;margin-bottom:6px">设计你的第一个工作流</div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:14px;line-height:1.6">
          从右侧 <b>模板库</b> 选择模板快速开始<br>或点击下方按钮手动添加步骤
        </div>
        <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
          <button class="btn-primary" style="font-size:12px;padding:7px 16px" onclick="wfAddStep('sequential')">➕ 添加顺序步骤</button>
          <button class="hdr-btn-sm" onclick="wfAiAssist()">🤖 AI 辅助生成</button>
        </div>
      </div>`;
    return;
  }
  canvas.innerHTML = `<div class="wf-flow">` +
    steps.map((s, i) => {
      const a = agentInfo[s.agent] || { icon:'🤖', name: s.agent };
      return `
      <div class="wf-node" data-idx="${i}">
        <div class="wf-node-hdr">
          <span class="wf-node-step">步骤 ${i+1}</span>
          <div class="wf-node-agent">
            <span>${a.icon}</span>
            <select class="wf-node-sel" onchange="wfUpdateStep(${i},'agent',this.value)">
              ${Object.entries(agentInfo).map(([id,info])=>
                `<option value="${id}" ${s.agent===id?'selected':''}>${info.icon} ${info.name}</option>`
              ).join('')}
            </select>
          </div>
          <button class="wf-node-del" onclick="wfRemoveStep(${i})">✕</button>
        </div>
        <textarea class="wf-node-prompt" rows="2" placeholder="给 ${a.name} 的指令…"
          onchange="wfUpdateStep(${i},'prompt',this.value)">${s.prompt||''}</textarea>
        <label class="wf-node-ctx">
          <input type="checkbox" ${s.pass_context!==false?'checked':''} onchange="wfUpdateStep(${i},'pass_context',this.checked)">
          传递上下文
        </label>
      </div>
      ${i < steps.length-1 ? '<div class="wf-arrow">↓</div>' : ''}`;
    }).join('') + `</div>`;
}

window.wfUpdateStep = function(idx, field, value) {
  if (wfStepList[idx]) wfStepList[idx][field] = value;
};

window.wfRemoveStep = function(idx) {
  wfStepList.splice(idx, 1);
  renderWfCanvas(wfStepList);
};

// ════════════════════════════════════════════════════
//  wfAddStep / wfRemoveStep / wfNew — 画布联动补丁
//  （修正重复定义，保留类型参数 + 更新可视化画布）
// ════════════════════════════════════════════════════
// 保存 wfAddStep 原始实现（定义于上方，支持 type 参数）
const _wfAddStepBase = window.wfAddStep;

// 重新定义：在类型感知逻辑基础上追加画布刷新
window.wfAddStep = function(type = 'sequential') {
  _wfAddStepBase(type);          // 保留 parallel/condition/loop 逻辑
  window._wfStepsData = wfStepList;
  if (typeof renderWfCanvas === 'function') renderWfCanvas(wfStepList);
};

// wfRemoveStep 已在上方(line ~3500)定义为 canvas-aware 版本，无需再包装

window.wfNew = function() {
  wfStepList.length = 0;          // clear in place so wfRun refs same array
  window._wfStepsData = wfStepList;
  if (typeof renderWfCanvas === 'function') renderWfCanvas(wfStepList);
  const nameEl = document.getElementById('wfName');
  if (nameEl) nameEl.value = '我的工作流';
  const st = document.getElementById('wfRunStatus');
  const rs = document.getElementById('wfResults');
  if (st) st.textContent = '等待运行…';
  if (rs) rs.innerHTML = '';
};

// (tab 切換增强已合并到上方 _origSwitchTab override)