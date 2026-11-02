import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from collections import defaultdict, Counter
from order_split import fetch_all_orders

c = ModaClient()

NAMES = {1: "堂食", 2: "小程序外卖", 4: "美团", 5: "京东", 6: "饿了么"}


def channel_stats(ds, store_id=16):
    orders = fetch_all_orders(ds, store_id)
    paid = [o for o in orders if int(o.get("status") or 0) == 2]
    cnt = Counter()
    amt = defaultdict(float)
    pay_rev = defaultdict(float)
    for o in paid:
        t = int(o.get("order_type") or 0)
        cnt[t] += 1
        try:
            amt[t] += float(o.get("total_price") or 0)
        except (TypeError, ValueError):
            pass
        try:
            pay_rev[t] += float(o.get("pay_price") or 0)
        except (TypeError, ValueError):
            pass
    out = []
    for t in (4, 6, 5):
        out.append({
            "type": t,
            "name": NAMES.get(t, str(t)),
            "orders": cnt.get(t, 0),
            "revenue": round(amt.get(t, 0), 2),
            "pay": round(pay_rev.get(t, 0), 2),
        })
    # 堂食口径：类型 1（堂食）+ 2（小程序外卖按门店自渠道，也计入堂食账套）
    # 堂食应收 = 已结账总应收 - 三大平台外卖应收
    total_amt = sum(amt.values())
    dinein_rev = round(total_amt - sum(amt.get(t, 0) for t in (4, 6, 5)), 2)
    dinein_cnt = cnt.get(1, 0) + cnt.get(2, 0) + cnt.get(3, 0)
    return out, len(paid), {"revenue": dinein_rev, "orders": dinein_cnt}


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    res, total, din = channel_stats(ds)
    print(ds, "已结账总数", total, "堂食应收", din["revenue"], "堂食单数", din["orders"])
    for r in res:
        print(f"  {r['name']:<6} {r['orders']:>4} 单  应收 {r['revenue']:>10,.2f}  实收 {r['pay']:>10,.2f}")
