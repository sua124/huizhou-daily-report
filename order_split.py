"""
订单类型拆解：只统计「已结账」订单（status=2）
堂食 = order_type 1；外卖 = 2(小程序) / 4(美团) / 5(京东) / 6(饿了么)
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from collections import Counter


def fetch_all_orders(ds, store_id=16, page_size=200, max_pages=60):
    c = ModaClient()
    out = []
    for page in range(1, max_pages + 1):
        # 注意：该接口前端真实参数是 created_arr（date_arr 已失效，返回空）
        r = c.post("/admin/food_order/index", {
            "created_arr": [ds, ds], "store_ids": [store_id],
            "status": [], "order_types": [],
            "page": page, "limit": page_size,
        })
        lst = r.get("data")
        if not isinstance(lst, list) or not lst:
            break
        out.extend(lst)
        if len(lst) < page_size:
            break
        time.sleep(0.03)
    return out


def split_orders(ds, store_id=16):
    orders = fetch_all_orders(ds, store_id)
    paid = [o for o in orders if int(o.get("status") or 0) == 2]
    cnt = Counter(int(o.get("order_type") or 0) for o in paid)
    amt = Counter()
    for o in paid:
        try:
            amt[int(o.get("order_type") or 0)] += float(o.get("total_price") or 0)
        except (TypeError, ValueError):
            pass

    dine = cnt.get(1, 0)
    takeout_detail = {
        "小程序外卖": cnt.get(2, 0),
        "美团": cnt.get(4, 0),
        "京东": cnt.get(5, 0),
        "饿了么": cnt.get(6, 0),
    }
    takeout = sum(takeout_detail.values())
    return {
        "total_orders": len(paid),
        "raw_count": len(orders),
        "dine_in": dine,
        "takeout": takeout,
        "takeout_detail": takeout_detail,
        "dine_amount": round(amt.get(1, 0), 2),
        "takeout_amount": round(sum(amt.get(k, 0) for k in (2, 4, 5, 6)), 2),
    }


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    r = split_orders(ds)
    print(f"{ds}  已结账单 {r['total_orders']}（原始 {r['raw_count']}）")
    print(f"  堂食 {r['dine_in']} 单 / {r['dine_amount']:,.2f} 元")
    print(f"  外卖 {r['takeout']} 单 / {r['takeout_amount']:,.2f} 元")
    for k, v in r["takeout_detail"].items():
        print(f"    - {k}: {v}")
