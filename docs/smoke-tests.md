# 手动冒烟测试（smoke tests）

一组**连真实后端跑**的临时端到端脚本，用来快速确认「服务起来了、关键链路通了」。
和 `backend/tests/`（pytest 自动化测试）是两回事：

| | 冒烟脚本 `smoke_*.py` | 自动化测试 `backend/tests/` |
|---|---|---|
| 跑法 | 手动 `python backend/smoke_xxx.py` | `pytest` |
| 依赖 | **需要后端在 :9100 跑着** | 不需要，自带桩/临时目录 |
| 入库 | 否（`.gitignore` 忽略 `backend/smoke_*.py`） | 是 |
| 用途 | 开发时随手验证某条链路 | CI / 回归，锁定行为 |

> 约定：冒烟脚本统一命名 `backend/smoke_<主题>.py`，属于本地 scratch，不提交。
> 真正要长期守护的行为，请补成 `backend/tests/test_*.py`。

## 前置

1. 启动后端，确认监听 `ws://127.0.0.1:9100`：

   ```bash
   cd backend
   python websocket_server.py
   ```

2. 装依赖（冒烟脚本用裸 `websockets` 客户端，不走项目依赖）：

   ```bash
   pip install websockets
   ```

## 现有脚本

### `smoke_analyst.py` — analyst 角色动态加载

验证 executor 调用 analyst 子角色时能正确动态加载。两步：

1. **连 `xi` worker** 发一条 `chat`：验证 WS 服务在线、消息收发格式正常。
2. **连 `executor` worker** 让它「调用 analyst 角色」：触发 analyst 动态加载并跑通。

跑：

```bash
python backend/smoke_analyst.py
```

预期：两步都打印一串 `<-` 收到的消息，各自以 `[done]` 收尾，无异常退出即通过。

## 写一个新的冒烟脚本

WebSocket worker 端点是 `ws://127.0.0.1:9100/ws/<agent_id>`（如 `xi` / `executor` /
`yiyi` / `shoucang` …）。最小骨架：

```python
import asyncio, json, websockets

async def recv_until_done(ws, timeout=30):
    """收到 done/error 或 status=completed/unverified 即停。"""
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
        data = json.loads(msg) if isinstance(msg, str) and msg.startswith("{") else {}
        print("  <-", str(msg)[:200])
        t = data.get("type", "")
        status = data.get("status") or data.get("data", {}).get("status", "")
        if t in ("done", "error") or status in ("completed", "unverified"):
            print("  [done]"); break

async def test():
    async with websockets.connect("ws://127.0.0.1:9100/ws/xi") as ws:
        await ws.send(json.dumps({"action": "chat", "message": "你好"}))
        await recv_until_done(ws, timeout=20)

asyncio.run(test())
```

要点：

- 状态字段可能在顶层（`status`），也可能嵌在 `data.data.status` 里，两处都判一下。
- 完成信号有多种：`type` 为 `done`/`error`，或 `status` 为 `completed`/`unverified`。
- 给足 `timeout`——调用大模型/动态加载角色的步骤会慢，必要时调到 40s 以上。
