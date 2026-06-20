# 评估任务集

每个 `*.yaml` 是一道自包含的题。字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 小写字母数字连字符，唯一 |
| `prompt` | ✅ | 交给 agent 的任务描述 |
| `verify` | ✅ | 验收命令，exit 0 = 通过。用 `{py}` 占位符代替解释器（runner 会替换成 `sys.executable`，避免依赖 PATH） |
| `setup.files` | | 初始文件（相对路径 → 内容），物化进隔离工作区 |
| `solution.files` | | 参考解（相对路径 → 内容），覆盖到工作区应让验收转绿。**难题强烈建议带** |
| `title` | | 展示名，缺省同 id |
| `category` | | bug-fix / add-feature / fix-test / edge-case / refactor |
| `timeout` | | 验收命令超时秒数，默认 120 |

## 设计纪律

- **每题初始状态必须是「红」**（验收命令在 setup 上直接跑会失败）。这样「什么都不做」= 0 分，
  题目才有判别力。`test_seed_task_starts_red` 自动守这条。
- **带参考解的题必须「可解」**：套上 `solution.files` 跑验收要转绿。`test_seed_task_winnable` 自动守这条。
  红/绿两侧夹住 → 题既不"白给"也不"做不出"（一道根本做不出的坏题会让 harness 白背锅）。
  难题（多 bug / 多文件 / 边界）务必带参考解。
- **判别力 > 数量**：一道基线一跑就过的题（如 DeepSeek 100% 的那 6 道）只能验框架通不通，
  量不出 harness 的增益。要让完成率"能动"，题必须难到弱模型不靠厚 harness 会栽——
  典型：①一题里埋多个 bug（逼着看测试、多轮自修复）②症状和 bug 不在同一文件（逼定位）
  ③藏边界用例（逼读规范+跑测试）④跨多步的有状态逻辑。
- **自包含微工作区**，不 clone 整个 Anima 仓库：可复现、跑得快、精确隔离被测点。
- **验收脚本自动判分**，绝不靠人看。pytest 断言或 diff 匹配。

## 怎么跑

```bash
# 框架自检（离线，stub solver，不烧 API）——随单元测试一起跑
python -m pytest tests/test_eval_spine.py -q

# 跑真实基线（烧 API 额度，用户触发）
python -m eval --model DeepSeek-V4-Pro --label baseline

# 消融：量化 Verify 闸门对弱模型的真实增益（关掉闸门再跑一遍，比完成率差）
python -m eval --model DeepSeek-V4-Pro --label gate-on
python -m eval --model DeepSeek-V4-Pro --label gate-off --no-verify-gate
```
