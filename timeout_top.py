"""
出品超时统计（菜品维度）
口径：下单时间 created_at → 传菜完成 deliver_at，超过 20 分钟记为超时
重要：接口的 use_time 字段不可信（同一单多道菜会累积成 9477 这种值），
      必须用两个时间戳自己算分钟数。
"""
import sys, os, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from collections import Counter, defaultdict

TIMEOUT_MIN = 20

# 排除菜品（这些菜品因制作工艺特殊/挂单口径问题，计入会失真）
EXCLUDE_KEYWORDS = ["三文鱼粥", "寿司包", "豆乳芝士"]


def _excluded(name):
    return any(k in (name or "") for k in EXCLUDE_KEYWORDS)


def _dt(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def pull_deliver(ds, store_id=16, limit=3000):
    c = ModaClient()
    r = c.post("/admin/food_analysis/deliverStatistics", {
        "date_arr": [ds, ds], "store_ids": [store_id], "page": 1, "limit": limit,
    })
    lst = r.get("data") or []
    items, dropped = [], []
    for x in lst:
        try:
            t0 = _dt(x["created_at"])
            t1 = _dt(x["deliver_at"])
        except Exception:
            continue
        name = (x.get("name") or "").strip()
        mins = int((t1 - t0).total_seconds() // 60)
        row = {
            "order_id": x.get("order_id"),
            "name": name,
            "mins": mins,
            "created": x["created_at"][11:16],
            "delivered": x["deliver_at"][11:16],
        }
        if _excluded(name):
            dropped.append(row)
        else:
            items.append(row)
    return items, dropped


def timeout_stats(ds, store_id=16, threshold=TIMEOUT_MIN):
    items, dropped = pull_deliver(ds, store_id)
    n = len(items)
    if not n:
        return {"total": 0, "timeout": 0, "rate": 0, "top": [], "avg": 0,
                "median": 0, "by_name": [], "peak": [], "excluded": 0}

    mins = sorted(i["mins"] for i in items)
    median = mins[n // 2]
    avg = sum(mins) / n

    over = [i for i in items if i["mins"] > threshold]
    over.sort(key=lambda i: -i["mins"])

    # 超时菜品聚合（同名合并）
    agg = defaultdict(lambda: {"cnt": 0, "max": 0, "sum": 0})
    for i in over:
        k = i["name"]
        agg[k]["cnt"] += 1
        agg[k]["sum"] += i["mins"]
        agg[k]["max"] = max(agg[k]["max"], i["mins"])
    by_name = sorted(
        ({"name": k, "cnt": v["cnt"], "max": v["max"],
          "avg": round(v["sum"] / v["cnt"], 1)} for k, v in agg.items()),
        key=lambda z: (-z["max"], -z["cnt"]),
    )

    # 超时时段分布（按菜品下单小时）
    peak = Counter()
    for i in over:
        peak[int(i["created"][:2])] += 1

    # 分档
    buckets = Counter()
    for m in mins:
        if m <= 10:
            buckets["≤10"] += 1
        elif m <= threshold:
            buckets["11-20"] += 1
        elif m <= 30:
            buckets["21-30"] += 1
        elif m <= 60:
            buckets["31-60"] += 1
        else:
            buckets[">60"] += 1

    # TOP 榜：同一单只取最慢的一道，避免一单 15 道菜霸榜
    worst = {}
    for i in over:
        k = i["order_id"]
        if k not in worst or i["mins"] > worst[k]["mins"]:
            worst[k] = i
    top_list = sorted(worst.values(), key=lambda i: -i["mins"])[:10]

    # 排障：整单时长特别离谱的（>60min）单独提示
    long_cnt = sum(1 for m in mins if m > 60)

    return {
        "total": n,
        "orders": len({i["order_id"] for i in items}),
        "timeout": len(over),
        "timeout_orders": len(worst),
        "rate": round(len(over) / n * 100, 2),
        "avg": round(avg, 1),
        "median": median,
        "max": mins[-1],
        "long_cnt": long_cnt,
        "threshold": threshold,
        "buckets": dict(buckets),
        "top": [
            {"name": i["name"], "mins": i["mins"], "order_id": i["order_id"],
             "created": i["created"], "delivered": i["delivered"]}
            for i in top_list
        ],
        "by_name": by_name[:6],
        "peak": sorted(peak.items()),
        # 剔除统计（仅作说明，不参与榜单）
        "excluded": len(dropped),
        "excluded_names": EXCLUDE_KEYWORDS,
    }


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    s = timeout_stats(ds)
    print(f"{ds} 菜品 {s['total']} 道 / {s['orders']} 单")
    print(f"超时(>{s['threshold']}min) {s['timeout']} 道  占比 {s['rate']}%  "
          f"平均 {s['avg']}min  中位 {s['median']}min  最长 {s['max']}min")
    print("分档:", s["buckets"])
    print("\nTOP10:")
    for t in s["top"]:
        print(f"  {t['mins']:>4}min  {t['created']}→{t['delivered']}  {t['name'][:22]:<24} #{t['order_id']}")
    print("\n超时菜品聚合:")
    for b in s["by_name"]:
        print(f"  {b['name'][:22]:<24} {b['cnt']} 道  最长 {b['max']}min  平均 {b['avg']}min")
    print("\n超时时段:", s["peak"])
