# Verify 闸门消融 · 离线判别力自检

> 这是 **apparatus self-test（尺子自检）**，不是模型基准。用确定性「弱模型」桩跑消融对照，
> 证明消融管道能量出 Verify 闸门的增益。真实数字需本机烧额度跑：
> `python -m eval --model DeepSeek-V4-Pro`（开）/ `--no-verify-gate`（关）。

- **gate-off**：弱模型没测就收工（什么都不改）→ 留红
- **gate-on**：Verify 闸门逼自修复到绿（等价套参考解）→ 转绿

# 对比报告　gate-off → gate-on

- gate-off（stub-weak-model）：0.0%　（0/2）
- gate-on（stub-weak-model）：100.0%　（2/2）
- **完成率变化：＋100.0%**

| 题目 | gate-off | gate-on | 变化 |
|---|---|---|---|
| cross-file-rounding | ❌ | ✅ | 🟢 修好了 |
| deep-import-precision | ❌ | ✅ | 🟢 修好了 |
