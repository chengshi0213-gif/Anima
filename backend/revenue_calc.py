# ============================================
# 陶朱公司 · App月度收入测算
# 口径：人民币/月
# ============================================

dau = 100_000          # 日活跃用户数
pay_rate = 0.03        # 付费率 3%
arpu = 12.0            # 月ARPU（元/付费用户）

# 1. 基础月收入
monthly_revenue = dau * pay_rate * arpu

print("=" * 55)
print("【基础测算】")
print(f"  DAU                = {dau:>10,} 人")
print(f"  付费率             = {pay_rate*100:>9.1f}%")
print(f"  月ARPU             = {arpu:>10.1f} 元")
print(f"  ─────────────────────────────")
print(f"  月收入             = {monthly_revenue:>10,.0f} 元")
print(f"                      ≈ {monthly_revenue/10000:.2f} 万元")
print("=" * 55)

# 2. 敏感性分析：付费率 2% ~ 4%（步长0.5%）
print()
print("【敏感性分析 · 付费率 vs 月收入】")
print(f"{'付费率':>8s} | {'月收入(元)':>12s} | {'月收入(万元)':>12s} | {'相对基准变化':>10s}")
print("-" * 50)

base_rev = monthly_revenue
rates = [r/100 for r in range(200, 405, 50)]  # 2.0%, 2.5%, 3.0%, 3.5%, 4.0%

for r in rates:
    rev = dau * r * arpu
    change = (rev - base_rev) / base_rev * 100
    print(f"{r*100:>7.1f}% | {rev:>12,.0f} | {rev/10000:>11.2f} | {change:>+9.1f}%")

print("-" * 50)
print(f"基准付费率: 3.0% → 月收入 {base_rev:,.0f} 元 ({base_rev/10000:.2f} 万元)")
print(f"付费率每变动 ±0.5%，月收入同比例变动 ±{0.5/3*100:.1f}%")
print("=" * 55)
