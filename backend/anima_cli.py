#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima CLI
与 Anima 后端通信的命令行工具

用法:
  python ANIMA_cli.py chat [agent] "消息"     # 直接与 agent 对话
  python ANIMA_cli.py run  <workflow>          # 运行已保存工作流
  python ANIMA_cli.py skill list               # 列出所有 Skill
  python ANIMA_cli.py skill install <url>      # 安装社区 Skill
  python ANIMA_cli.py kb search "查询"         # 知识库语义检索
  python ANIMA_cli.py kb upload <file>         # 上传文件到知识库
  python ANIMA_cli.py report daily             # 获取今日日报
  python ANIMA_cli.py report weekly            # 获取本周周报
  python ANIMA_cli.py vault tree               # 显示 Vault 文件树
  python ANIMA_cli.py vault read <path>        # 读取 Vault 文件
  python ANIMA_cli.py shoucang sop             # 触发守藏 SOP

环境变量:
  ANIMA_PORT   后端端口（默认 9100）
"""

import sys
import json
import argparse
import urllib.request
import urllib.parse
import time

PORT = int(__import__('os').environ.get('ANIMA_PORT', 9100))
BASE = f"http://127.0.0.1:{PORT}"

# 本地 token：从 ~/.anima/local_token.txt 读取（与后端一致）
def _read_local_token() -> str:
    import pathlib
    tok_file = pathlib.Path.home() / ".anima" / "local_token.txt"
    try:
        if tok_file.exists():
            return tok_file.read_text("utf-8").strip()
    except Exception:
        pass
    return __import__('os').environ.get('ANIMA_TOKEN', '')

LOCAL_TOKEN = _read_local_token()
AUTH_HEADERS = {"Authorization": f"Bearer {LOCAL_TOKEN}"} if LOCAL_TOKEN else {}

AGENT_ALIASES = {
    'h': 'xi', 'xi': 'xi',
    'y': 'yiyi',   'yiyi':   'yiyi',   '晞': 'yiyi',
    't': 'tianyuan','tianyuan':'tianyuan','陶朱':'tianyuan',
    's': 'shoucang', 'shoucang':'shoucang', '守藏':'shoucang',
    'e': 'executor','executor':'executor',
    'w': 'writer',  'writer':  'writer',
    'r': 'reader',  'reader':  'reader',
    'c': 'critic',  'critic':  'critic',
}

COLORS = {
    'reset': '\033[0m',
    'bold':  '\033[1m',
    'cyan':  '\033[36m',
    'green': '\033[32m',
    'yellow':'\033[33m',
    'red':   '\033[31m',
    'blue':  '\033[34m',
    'muted': '\033[2m',
}

def c(color, text):
    """带颜色输出"""
    return f"{COLORS.get(color,'')}{text}{COLORS['reset']}"

def api_get(path: str) -> dict:
    url = BASE + path
    try:
        req = urllib.request.Request(url, headers=AUTH_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        print(c('red', f"✗ 无法连接后端 ({BASE}): {e}"))
        print(c('muted', "请先运行: python websocket_server.py"))
        sys.exit(1)
    except Exception as e:
        print(c('red', f"✗ 错误: {e}"))
        sys.exit(1)

def api_post(path: str, body: dict) -> dict:
    url = BASE + path
    data = json.dumps(body).encode('utf-8')
    headers = {'Content-Type': 'application/json', **AUTH_HEADERS}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        if e.code == 401:
            print(c('red', "✗ 鉴权失败 — token 不匹配，请检查 ~/.anima/local_token.txt"))
            sys.exit(1)
        try:
            err = json.loads(body_bytes)
            print(c('red', f"✗ API 错误 ({e.code}): {err.get('error', body_bytes.decode())}"))
        except Exception:
            print(c('red', f"✗ HTTP {e.code}: {body_bytes.decode()[:200]}"))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(c('red', f"✗ 无法连接后端: {e}"))
        sys.exit(1)

def ws_chat_sync(agent_id: str, message: str) -> str:
    """
    通过 WebSocket 与 Agent 实时流式对话。
    使用 websockets 库（纯同步包装）。
    降级：若 websockets 未安装，退回到 /workflow/run HTTP。
    """
    try:
        import websocket  # websocket-client（pip install websocket-client）
        import threading

        result_holder = {'reply': '', 'done': False}
        ws_url = f"ws://127.0.0.1:{PORT}/ws/{agent_id}"
        sid = f"cli-{int(time.time())}"

        def on_message(ws_obj, raw):
            try:
                msg = json.loads(raw)
                if msg.get('type') == 'status' and msg.get('status') == 'running':
                    sys.stdout.write('')
                    sys.stdout.flush()
                elif msg.get('type') == 'tool_start':
                    tool = msg.get('data', {}).get('tool', '')
                    sys.stdout.write(c('muted', f'\r  [工具: {tool}]  '))
                    sys.stdout.flush()
                elif msg.get('type') == 'response' and msg.get('data', {}).get('status'):
                    result_holder['reply'] = msg['data'].get('summary', '')
                    result_holder['done'] = True
                    ws_obj.close()
                elif msg.get('type') == 'error':
                    result_holder['reply'] = f"[错误] {msg.get('message','')}"
                    result_holder['done'] = True
                    ws_obj.close()
            except Exception:
                pass

        def on_open(ws_obj):
            ws_obj.send(json.dumps({
                'action': 'chat',
                'message': message,
                'session_id': sid,
            }))

        ws_obj = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
        )
        t = threading.Thread(target=ws_obj.run_forever)
        t.daemon = True
        t.start()

        # 等待回复（最长 5 分钟）
        deadline = time.time() + 300
        while not result_holder['done'] and time.time() < deadline:
            time.sleep(0.1)

        sys.stdout.write('\r' + ' ' * 40 + '\r')  # 清除工具状态行
        sys.stdout.flush()
        return result_holder['reply']

    except ImportError:
        # 降级：HTTP workflow/run（无流式）
        steps = [{'agent': agent_id, 'prompt': message, 'pass_context': False}]
        result = api_post('/workflow/run', {'steps': steps})
        outputs = result.get('results', [])
        return outputs[0].get('output', '') if outputs else ''


# ──────────────────────────────────────────────────
#  子命令实现
# ──────────────────────────────────────────────────

def cmd_chat(args):
    """chat [agent] <message>  — 与 Agent 对话"""
    agent = AGENT_ALIASES.get(args.agent, args.agent) if args.agent else 'xi'
    message = args.message or ''
    if not message:
        message = input(c('cyan', f"→ 发送给 {agent}: ")).strip()
    if not message:
        print(c('muted', "消息为空，退出。"))
        return
    print(c('muted', f"⏳ {agent} 正在思考…"))
    t0 = time.time()
    reply = ws_chat_sync(agent, message)
    elapsed = round(time.time() - t0, 1)
    print()
    print(c('bold', f"[{agent}] ") + reply)
    print()
    print(c('muted', f"耗时 {elapsed}s"))


def cmd_run(args):
    """run <workflow_name>  — 运行已保存工作流"""
    name = args.workflow_name
    # 先找到工作流
    data = api_get(f"/workflow/list")
    workflows = data.get('workflows', [])
    wf = next((w for w in workflows if w['name'] == name or w.get('id') == name), None)
    if not wf:
        print(c('red', f"✗ 找不到工作流: {name}"))
        print("可用工作流:", ', '.join(w['name'] for w in workflows))
        sys.exit(1)
    steps = wf.get('steps', [])
    print(c('cyan', f"▶ 运行工作流 [{name}] ({len(steps)} 个步骤)…"))
    result = api_post('/workflow/run', {'steps': steps})
    for r in result.get('results', []):
        print()
        print(c('bold', f"步骤 {r['step']} · {r['agent']}") + c('muted', f"  ({r.get('elapsed',0)}s)"))
        print(r.get('output', ''))
    print()
    print(c('green', "✓ 工作流完成"))


def cmd_skill(args):
    """skill list | install <url>"""
    if args.skill_action == 'list':
        data = api_get('/skills')
        skills = data.get('skills', [])
        summary = data.get('summary', {})
        print(c('bold', f"\n🧩 Skill 列表  (共 {summary.get('total',len(skills))} 个)\n"))
        for s in skills:
            status = '★' * int(s.get('avg_score', 0)) if s.get('avg_score') else '新'
            print(f"  {s.get('icon','⚙️')}  {c('bold',s['name']):<20} v{s.get('version',1)}  {status}")
            print(c('muted', f"      {s.get('description','')[:80]}"))
            print()
    elif args.skill_action == 'install':
        url = args.skill_url
        if not url:
            print(c('red', "✗ 请提供 Skill URL，如：github:user/repo"))
            sys.exit(1)
        print(c('muted', f"⏳ 安装 {url}…"))
        result = api_post('/skills/install', {'url': url})
        if result.get('error'):
            print(c('red', f"✗ 安装失败: {result['error']}"))
        else:
            print(c('green', f"✓ 已安装：{result.get('name', url)}"))
    else:
        print(c('red', f"✗ 未知 skill 操作: {args.skill_action}"))
        sys.exit(1)


def cmd_kb(args):
    """kb search <query> | upload <file>"""
    if args.kb_action == 'search':
        query = args.kb_arg
        if not query:
            print(c('red', "✗ 请提供查询内容"))
            sys.exit(1)
        result = api_post('/kb/search', {'query': query, 'top_k': 5})
        hits = result.get('hits', [])
        if not hits:
            print(c('muted', "没有找到相关内容"))
            return
        print(c('bold', f"\n📚 找到 {len(hits)} 个相关片段：\n"))
        for i, h in enumerate(hits, 1):
            print(c('cyan', f"[{i}] {h.get('doc_name','未知')}") +
                  c('muted', f"  相似度 {h.get('score',0):.2f}"))
            print(h.get('text','')[:200].strip())
            print()
    elif args.kb_action == 'upload':
        filepath = args.kb_arg
        if not filepath:
            print(c('red', "✗ 请提供文件路径"))
            sys.exit(1)
        import pathlib
        p = pathlib.Path(filepath)
        if not p.exists():
            print(c('red', f"✗ 文件不存在: {filepath}"))
            sys.exit(1)
        text = p.read_text('utf-8', errors='replace')
        print(c('muted', f"⏳ 上传 {p.name}…"))
        result = api_post('/kb/upload', {'text': text, 'name': p.name})
        if result.get('error'):
            print(c('red', f"✗ 失败: {result['error']}"))
        else:
            print(c('green', f"✓ 已入库：{result.get('doc_id',p.name)}  ({result.get('chunks',0)} 个片段)"))
    else:
        print(c('red', f"✗ 未知 kb 操作: {args.kb_action}"))
        sys.exit(1)


def cmd_report(args):
    """report daily | weekly"""
    rtype = args.report_type or 'daily'
    if rtype not in ('daily', 'weekly'):
        print(c('red', f"✗ 报告类型必须是 daily 或 weekly"))
        sys.exit(1)
    print(c('muted', f"⏳ 获取{('日报' if rtype=='daily' else '周报')}…"))
    report = api_get(f"/reports/{rtype}")
    if not report:
        print(c('muted', "暂无报告数据"))
        return
    print()
    print(c('bold', f"  {'📅 日报' if rtype=='daily' else '📊 周报'} · {report.get('date','')}"))
    print()
    print(report.get('warm_text', ''))
    stats = report.get('stats', {})
    if stats:
        print()
        print(c('muted', f"  对话 {stats.get('total_sessions',0)} 次 · "
                          f"消息 {stats.get('total_messages',0)} 条 · "
                          f"最活跃 {stats.get('peak_hour',0)}:00"))
    upgrades = report.get('skill_upgrades', [])
    if upgrades:
        print()
        print(c('bold', "🚀 Skill 成长:"))
        for s in upgrades:
            print(f"  {s.get('icon','⚙️')} {s.get('name','')} v{s.get('version',1)}")


def cmd_vault(args):
    """vault tree | read <path>"""
    if args.vault_action == 'tree':
        data = api_get('/vault/tree')
        vault_dir = data.get('vault_dir', '~/Anima-Vault')
        tree = data.get('tree', [])
        print(c('bold', f"\n🗂 Vault: {vault_dir}\n"))
        _print_tree(tree, 0)
    elif args.vault_action == 'read':
        path = args.vault_arg
        if not path:
            print(c('red', "✗ 请提供文件路径"))
            sys.exit(1)
        data = api_get(f"/vault/file?path={urllib.parse.quote(path)}")
        if data.get('error'):
            print(c('red', f"✗ {data['error']}"))
        else:
            print(data.get('content', ''))
    else:
        print(c('red', f"✗ 未知 vault 操作: {args.vault_action}"))
        sys.exit(1)

def _print_tree(nodes, depth):
    for n in nodes:
        indent = '  ' * depth
        if n['type'] == 'dir':
            print(c('cyan', f"{indent}📁 {n['name']}/"))
            _print_tree(n.get('children', []), depth + 1)
        else:
            print(f"{indent}📄 {n['name']}")


def cmd_shoucang(args):
    """shoucang sop  — 触发守藏日常 SOP"""
    if args.shoucang_action == 'sop':
        result = api_post('/shoucang/sop', {})
        print(c('green', f"✓ {result.get('message','SOP 已启动')}"))
    else:
        print(c('red', f"✗ 未知操作: {args.shoucang_action}"))
        sys.exit(1)


def cmd_status(args):
    """status  — 显示所有 Agent 状态"""
    data = api_get('/status')
    print(c('bold', "\n  Anima Agent 状态\n"))
    for name, s in data.items():
        busy_str = c('yellow', '⚡ 工作中') if s.get('busy') else c('green', '✓ 就绪')
        print(f"  {s.get('agent',name):<12} {busy_str:<20} 模型: {s.get('model','-')}")
    print()


def cmd_hook(args):
    """hook [agent] <prompt> [--wait]  — Webhook 触发 Agent 任务"""
    agent  = AGENT_ALIASES.get(args.agent, args.agent) if args.agent else 'xi'
    prompt = args.prompt or ''
    if not prompt:
        prompt = input(c('cyan', f"→ 发送给 {agent}: ")).strip()
    if not prompt:
        print(c('muted', "消息为空，退出。"))
        return
    body = {"prompt": prompt, "return_result": bool(args.wait)}
    result = api_post(f'/hook/{agent}', body)
    if args.wait:
        print()
        print(c('bold', f"[{agent}] ") + result.get('result', ''))
    else:
        print(c('green', f"✓ {result.get('message', '已后台触发')}"))
        print(c('muted', f"  task_id: {result.get('task_id','')}"))


def cmd_learn(args):
    """learn <key> <value>  — 让 Anima 记住一件事"""
    result = api_post('/memory/learn', {'key': args.key, 'value': args.value})
    if result.get('ok'):
        print(c('green', f"🧠 {result.get('message', 'Anima 记住了')}"))
    else:
        print(c('red', f"✗ 失败: {result.get('error','')}"))


def cmd_project(args):
    """project list | create <name> | activate <name> | clear"""
    action = args.action
    if action == 'list':
        data = api_get('/projects')
        projects = data.get('projects', [])
        active   = data.get('active')
        print(c('bold', f"\n📁 项目列表  (活跃: {active or '无'})\n"))
        for p in projects:
            prefix = c('green', '▶ ') if p.get('is_active') else '  '
            print(f"{prefix}{c('bold', p['name']):<20}  {p.get('files',0)} 文件")
            if p.get('description'):
                print(c('muted', f"    {p['description'][:60]}"))
        print()
    elif action == 'create':
        name = args.name
        if not name:
            print(c('red', "✗ 请提供项目名称"))
            sys.exit(1)
        result = api_post('/projects', {'name': name})
        if result.get('ok'):
            print(c('green', f"✓ 项目 '{name}' 创建成功  路径: {result.get('path','')}"))
        else:
            print(c('red', f"✗ {result.get('error','')}"))
    elif action == 'activate':
        name = args.name
        if not name:
            print(c('red', "✗ 请提供项目名称"))
            sys.exit(1)
        result = api_post(f'/projects/{urllib.parse.quote(name)}/activate', {})
        if result.get('ok'):
            print(c('green', f"✓ 已切换到项目：{name}"))
        else:
            print(c('red', f"✗ {result.get('error','')}"))
    elif action == 'clear':
        result = api_post('/projects/deactivate', {})
        if result.get('ok'):
            print(c('green', "✓ 已清除活跃项目"))
    else:
        print(c('red', f"✗ 未知操作: {action}"))
        sys.exit(1)


def cmd_membership(args):
    """membership status | activate <code> | deactivate | generate"""
    action = args.action
    if action == 'status':
        data = api_get('/membership/status')
        tier = data.get('tier', 'free')
        active = data.get('active', False)
        if active and tier == 'pro':
            print(c('bold', "\n👑 Anima Pro"))
            print(f"   有效至 {c('green', data.get('expires','?'))}（剩余 {data.get('days_left',0)} 天）")
            print(f"   全部 30 个 Skill + 工作流模板已解锁\n")
        else:
            print(c('bold', "\n🆓 Anima Free"))
            print(f"   8 个基础 Skill 可用")
            if data.get('error'):
                print(c('red', f"   ⚠ {data['error']}"))
            print(c('muted', "   使用 xi membership activate <激活码> 升级到 Pro\n"))
    elif action == 'activate':
        code = args.code
        if not code:
            print(c('red', "✗ 请提供激活码，格式: ANIMA-XXXX-XXXX-XXXX-XXXX-XXXXXXXX"))
            sys.exit(1)
        result = api_post('/membership/activate', {'code': code})
        if result.get('ok'):
            print(c('green', f"🎉 {result.get('message', '激活成功！')}"))
        else:
            print(c('red', f"✗ {result.get('error', '激活失败')}"))
    elif action == 'deactivate':
        result = api_post('/membership/deactivate', {})
        if result.get('ok'):
            print(c('green', "✓ 已退回免费版"))
        else:
            print(c('red', f"✗ {result.get('error', '操作失败')}"))
    elif action == 'generate':
        # 本地生成（开发者用，不走 HTTP）
        try:
            from membership import generate_license
            days = args.days or 365
            code = generate_license(days=days, tier='pro')
            print(c('bold', f"\n🔑 生成激活码（{days} 天有效）："))
            print(c('green', f"   {code}\n"))
        except Exception as e:
            print(c('red', f"✗ 生成失败: {e}"))
    else:
        print(c('red', f"✗ 未知操作: {action}"))
        sys.exit(1)


# ──────────────────────────────────────────────────
#  主入口
# ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='xi',
        description='Anima CLI — 本地 AI 多智能体工作台命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  anima chat xi "帮我看看最新的 AI 新闻"
  anima skill list
  anima kb upload ./readme.md
  anima report daily
  anima vault tree
  anima shoucang sop
  anima status
  anima hook xi "检查服务器是否正常运行"  --wait
  anima learn "我的时区" "UTC+8，北京时间"
  anima project list
  anima project create MyProject
  anima project activate MyProject
"""
    )
    sub = parser.add_subparsers(dest='command')

    # chat
    p_chat = sub.add_parser('chat', help='与 Agent 对话')
    p_chat.add_argument('agent', nargs='?', default='xi',
                        help='Agent 名称 (xi/yiyi/tianyuan/shoucang/…)')
    p_chat.add_argument('message', nargs='?', help='消息内容')

    # run
    p_run = sub.add_parser('run', help='运行已保存工作流')
    p_run.add_argument('workflow_name', help='工作流名称或 ID')

    # skill
    p_skill = sub.add_parser('skill', help='Skill 管理')
    p_skill.add_argument('skill_action', choices=['list','install'], help='操作')
    p_skill.add_argument('skill_url', nargs='?', help='Skill URL（install 时）')

    # kb
    p_kb = sub.add_parser('kb', help='知识库操作')
    p_kb.add_argument('kb_action', choices=['search','upload'], help='操作')
    p_kb.add_argument('kb_arg', nargs='?', help='查询词或文件路径')

    # report
    p_rpt = sub.add_parser('report', help='获取日报/周报')
    p_rpt.add_argument('report_type', choices=['daily','weekly'], nargs='?', default='daily')

    # vault
    p_vault = sub.add_parser('vault', help='Obsidian Vault 操作')
    p_vault.add_argument('vault_action', choices=['tree','read'], help='操作')
    p_vault.add_argument('vault_arg', nargs='?', help='文件路径（read 时）')

    # shoucang
    p_sch = sub.add_parser('shoucang', help='守藏 SOP')
    p_sch.add_argument('shoucang_action', choices=['sop'], help='操作')

    # status
    sub.add_parser('status', help='查看 Agent 状态')

    # hook
    p_hook = sub.add_parser('hook', help='通过 Webhook 触发 Agent（异步）')
    p_hook.add_argument('agent', nargs='?', default='xi', help='Agent 名称')
    p_hook.add_argument('prompt', nargs='?', help='任务指令')
    p_hook.add_argument('--wait', action='store_true', help='等待结果同步返回')

    # learn
    p_learn = sub.add_parser('learn', help='让 Anima 记住一件事')
    p_learn.add_argument('key',   help='关键词（这是关于什么）')
    p_learn.add_argument('value', help='具体内容')

    # project
    p_proj = sub.add_parser('project', help='项目管理')
    p_proj.add_argument('action', choices=['list','create','activate','clear'], help='操作')
    p_proj.add_argument('name', nargs='?', help='项目名称')

    p_member = sub.add_parser('membership', help='会员管理')
    p_member.add_argument('action', choices=['status','activate','deactivate','generate'], help='操作')
    p_member.add_argument('code', nargs='?', help='激活码（activate 时必填）')
    p_member.add_argument('--days', type=int, default=365, help='生成激活码有效天数（generate）')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        'chat':       cmd_chat,
        'run':        cmd_run,
        'skill':      cmd_skill,
        'kb':         cmd_kb,
        'report':     cmd_report,
        'vault':      cmd_vault,
        'shoucang':   cmd_shoucang,
        'status':     cmd_status,
        'hook':       cmd_hook,
        'learn':      cmd_learn,
        'project':    cmd_project,
        'membership': cmd_membership,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
