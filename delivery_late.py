"""传菜时效统计（老板拍板新增的跟踪项，2026-11-05 定稿口径）
口径：出品完成 dish_up_at → 传菜完成 deliver_at，超过 3 分钟记为慢传
      （即纯传菜/上桌环节，不含厨房出品时间；出品环节另看出品超时图）
数据源：/admin/food_analysis/deliverStatistics（注意：该接口只含堂食）
背景：出品口径仅 2 道超时，而传菜环节 3 分钟红线有 75 道 —— 慢在上桌，不在厨房
"""
import datetime
from collections import Counter
from moda_client import ModaClient

LATE_MIN = 3
# 与出品口径一致：制作工艺特殊/挂单口径问题的菜品不计入
EXCLUDE_KEYWORDS = ["三文鱼粥", "寿司包", "豆乳芝士"]


def _dt(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def delivery_stats(ds, store_id, limit=3000):
    c = ModaClient()
    r = c.post("/admin/food_analysis/deliverStatistics", {
        "date_arr": [ds, ds], "store_ids": [store_id], "page": 1, "limit": limit,
    })
    lst = r.get("data") or []
    items = []
    for x in lst:
        try:
            t_up = _dt(x["dish_up_at"])
            t_dl = _dt(x["deliver_at"])
        except Exception:
            continue
        name = (x.get("name") or "").strip()
        if any(k in name for k in EXCLUDE_KEYWORDS):
            continue
        secs = int((t_dl - t_up).total_seconds())
        if secs < 0:
            continue
        items.append({
            "order_id": x.get("order_id"),
            "name": name,
            "mins": secs // 60,
            "secs": secs,
            "dish_up": x["dish_up_at"][11:16],
            "delivered": x["deliver_at"][11:16],
        })

    n = len(items)
    if not n:
        return {"total": 0, "late": 0, "rate": 0, "avg": 0, "median": 0,
                "max": 0, "top": [], "peak": []}

    mins = sorted(i["mins"] for i in items)
    late = [i for i in items if i["mins"] > LATE_MIN]
    late.sort(key=lambda i: -i["secs"])
    peak = Counter(int(i["dish_up"][:2]) for i in late)

    return {
        "total": n,
        "late": len(late),
        "rate": round(len(late) / n * 100, 2),
        "avg": round(sum(mins) / n, 1),
        "median": mins[n // 2],
        "max": mins[-1],
        "top": late[:10],
        "peak": sorted(peak.items()),
    }


if __name__ == "__main__":
    import sys, json
    ds = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    sid = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    d = delivery_stats(ds, sid)
    print(json.dumps(d, ensure_ascii=False, indent=1)[:2000])
