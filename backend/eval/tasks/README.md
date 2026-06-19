# 评估任务集

每个 `*.yaml` 是一道自包含的题。字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 小写字母数字连字符，唯一 |
| `prompt` | ✅ | 交给 agent 的任务描述 |
| `verify` | ✅ | 验收命令，exit 0 = 通过。用 `{py}` 占位符代替解释器（runner 会替换成 `sys.executable`，避免依赖 PATH） |
| `setup.files` | | 初始文件（相对路径 → 内容），物化进隔离工作区 |
| `title` | | 展示名，缺省同 id |
| `category` | | bug-fix / add-feature / fix-test / edge-case / refactor |
| `timeout` | | 验收命令超时秒数，默认 120 |

## 设计纪律

- **每题初始状态必须是「红」**（验收命令在 setup 上直接跑会失败）。这样「什么都不做」= 0 分，
  题目才有判别力。新增题务必先确认初始即红。
- **自包含微工作区**，不 clone 整个 Anima 仓库：可复现、跑得快、精确隔离被测点。
- **验收脚本自动判分**，绝不靠人看。pytest 断言或 diff 匹配。
- **宁可少而真，不可多而水**（规划原话）。当前是 6 道种子题，目标扩到 ~20 道、
  覆盖更接近 Anima 真实改动的多文件/带定位的任务（配合 Phase L 落地后加）。

## 怎么跑

```bash
# 框架自检（离线，stub solver，不烧 API）——随单元测试一起跑
python -m pytest tests/test_eval_spine.py -q

# 跑真实基线（烧 API 额度，用户触发）
python -m eval --model DeepSeek-V4-Pro --label baseline
python -m eval --model Claude-Sonnet-4.6 --label claude-ref   # 对照
```
