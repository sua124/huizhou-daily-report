"""
赠菜明细拉取：返回每条记录 + 按原因归类
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from collections import defaultdict


def pull_send_detail(ds, store_id=16):
    c = ModaClient()
    r = c.post("/admin/food_analysis/sendDetail", {
        "date_arr": [ds, ds], "store_ids": [store_id], "page": 1, "limit": 500,
    })
    lst = r.get("data") or []
    items = []
    for x in lst:
        items.append({
            "name": x.get("name"),
            "amount": float(x.get("food_total_price") or 0),
            "num": x.get("num"),
            "unit": x.get("unit") or "",
            "reason": (x.get("reason") or "").strip(),
            "remark": (x.get("remark") or "").strip(),
            "admin": x.get("refund_admin_name") or "",
            "time": (x.get("created_at") or "")[11:16],
            "table": x.get("table_name") or "",
            "order_sn": x.get("order_sn") or "",
        })
    items.sort(key=lambda i: -i["amount"])

    by_reason = defaultdict(lambda: {"cnt": 0, "amt": 0.0})
    for i in items:
        key = i["reason"] or i["remark"] or "未标注"
        by_reason[key]["cnt"] += 1
        by_reason[key]["amt"] += i["amount"]

    # 赠菜份数（数量），不是条数
    qty = 0
    for i in items:
        try:
            qty += float(i["num"] or 0)
        except (TypeError, ValueError):
            qty += 1

    return {
        "items": items,
        "total": round(sum(i["amount"] for i in items), 2),
        "count": len(items),
        "qty": int(qty) if float(qty).is_integer() else round(qty, 1),
        "by_reason": dict(by_reason),
    }


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    d = pull_send_detail(ds)
    print(f"{ds}  共 {d['count']} 条  合计 {d['total']:.2f} 元")
    for i in d["items"]:
        print(f"  {i['time']} {i['name'][:22]:<24} {i['amount']:>7.2f}  {i['reason'][:24]}")
