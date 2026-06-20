# Anima 结构整改方案（2026-06-20）

> 来源：PROJECT_MAP.md §9 的 6 项结构问题。
> 北极星：**更可靠**。任何整改若不能在本环境验证、且可能危及冻结二进制，宁可暂缓也不冒险。

---

## 0. 决定性约束（为什么不无脑大改）

1. **冻结二进制不可在本环境验证**：CI 用 `pyinstaller --onefile websocket_server.py` 打包，只追**静态 import**。本地 910 测试跑的是扁平 `sys.path` 的源码——**测试全绿 ≠ 打包不炸**。任何改 import 拓扑的大动作（物理分包），在这里过了也无法证明 sidecar 还能起。
2. **导航痛点已被 PROJECT_MAP.md 解决**：物理分包的主要收益（找文件）边际下降，风险/收益比变差。
3. **最脆弱区是 worker 簇**：`SUBAGENT_FACTORIES` 用字符串名动态 `importlib.import_module` 加载 worker（为破循环依赖才这么写），与 CI 打包强耦合——恰是最不该轻动的地方。

结论：**优先做可验证的可靠性修复（R1-R4），物理分包暂缓为 ADR（R6），config 拆分否决（R5）。**

---

## R1 ── 修复扩展 Worker 不进冻结包【可靠性 BUG · 高优先】

**问题**：`analyst_worker` / `pm_worker` / `researcher_worker` 仅经 `SUBAGENT_FACTORIES` 字符串动态加载，全仓库无任何静态 import。CI `--onefile websocket_server.py` 不会把它们打进二进制 → **打包版调用「数据分析师/产品经理/研究员」会 `ModuleNotFoundError` 崩溃**。

**为何不用"加静态 import"修**：这三个连同 executor 等都是被 orchestrator 懒加载的——懒加载本就是为了**打破循环依赖**（worker → orchestrator → worker）。在 orchestrator 顶部加 `import xxx_worker` 会把循环引回来。

**修法**：在 `build.yml` 四条 pyinstaller 命令各加
`--hidden-import analyst_worker --hidden-import pm_worker --hidden-import researcher_worker`。
hidden-import 是**纯增量**——只会把模块塞进包，不可能破坏已有打包，安全性由构造保证。

**验证**：本环境无法跑 CI；靠"增量安全"性质 + 下次 tag 触发的 CI 构建确认。

---

## R2 ── 版本号单一真源【可靠性 · 中优先】

**问题**：三处漂移——`package.json`/`tauri.conf.json`/`Cargo.toml` = `1.2.3`，后端启动横幅硬编码 `v1.0.0`，已发布 tag = `v1.3.0`。

**修法**：
- 三个清单 → `1.3.0`。
- 后端新增单一常量 `config.ANIMA_VERSION = "1.3.0"`，横幅改 `f"后端服务 v{ANIMA_VERSION}"`，消灭硬编码 `1.0.0`。

---

## R3 ── code_index 索引收归缓存目录【整洁/结构 · 中优先】

**问题**：`code_index._DATA_DIR` 未配 `data_dir` 时回退 `Path(".")` = cwd，索引糊在**仓库根**，已堆 32 个 `.code_index_*.json`。

**修法**：索引落点改为 `_DATA_DIR/.anima_index/code_index_{key}.json`（自动建目录）；清理 32 个残留；`.gitignore` 补 `.anima_index/`。测试无硬编码该路径，零回归风险。

---

## R4 ── 签名私钥护栏【安全 · 低改动】

**问题**：`anima-signing.key`（私钥）躺在仓库根，未追踪，仅靠 `.gitignore` 的 `*.key` 兜底。

**修法**：**不物理移动**（避免破坏本地签名脚本）。强化 `.gitignore` 注释，确认 `*.key` + 显式 `anima-signing.key` 双重覆盖；保持私钥永不入库。代码层无改动。

---

## R5 ── config god module 拆分【否决】

**评估**：`config.py` 被 import 29 次、导出 45 符号。但它是**集中配置**，中枢化是其职责本身；拆成子模块易引入子模块间循环 import，收益（可读性）低、风险（破坏配置加载）高——**违背"更可靠"，否决**。保留单文件，仅在其中加 `ANIMA_VERSION`（见 R2）。

---

## R6 ── 后端 81 文件物理分包【暂缓 · ADR】

**目标形态**（未来）：`memory/` `workers/` `agent/` `integrations/` `security/` 等子包，根目录只留入口。

**为何暂缓**（见 §0）：
- 冻结二进制不可本环境验证，分包改全量 import 拓扑，过测不等于打包可用。
- worker 簇的动态 import + CI 打包耦合是高危区。
- 导航已由 PROJECT_MAP.md 兜底。

**未来安全执行前置条件**：
1. 先在本机装 PyInstaller，能跑通 `pyinstaller --onefile websocket_server.py` 并**实际启动 sidecar 冒烟**。
2. 分包按簇逐个迁移，每簇：改 import → 跑 910 测试 → 本机重打包冒烟 → 提交。
3. 同步 `SUBAGENT_FACTORIES` 字符串名与 `--hidden-import` 路径。

---

## 执行顺序与验收

| 步骤 | 动作 | 验收 |
|---|---|---|
| R3 | 改 code_index 落点 + 清残留 + gitignore | 910 测试全绿 |
| R2 | 三清单 + 后端常量 + 横幅 | 910 测试全绿 |
| R1 | build.yml 加 hidden-import | 改动审阅（CI 下次构建实测） |
| R4 | gitignore 护栏强化 | 私钥仍未追踪 |
| — | 更新 PROJECT_MAP.md §9 与版本头 | 导航与现状一致 |

**全程纪律**：选择性 `git add`，绝不 `git add -A`；私钥绝不入库。
