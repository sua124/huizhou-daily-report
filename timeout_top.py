"""
出品超时统计（KDS 出品口径）

数据源：POST /admin/food_analysis/kdsStatis
    → 菜品级出品记录，字段含 order_type（订单类型）与 use_time（出品耗时，秒）

口径（老板 2026-11-05 指定）：
    堂食（order_type=1）出品 > 20 分钟 记为超时
    外卖（order_type=2/4/5/6）出品 > 15 分钟 记为超时

时长取自 use_time，已验证它精确等于「下单时间 → 菜品出品完成(dish_up_at)」的差值
（2026-11-04 抽样 12 道菜，差 0 秒），且 kdsStatis 覆盖堂食 + 外卖全量。

⚠️ 两个坑（改这个文件前务必看）：
1. /admin/food_analysis/deliverStatistics **只返回堂食**（11-04 实测只覆盖 40/84 单），
   外卖完全不入库，不能用它算全店超时。
2. 早期版本用 deliverStatistics 的「下单 → 传菜完成(deliver_at)」当出品时长，
   把传菜、顾客取餐的时间也算进了厨房，超时率被严重放大
   （11-04 曾算出 34 道超时，按出品口径实际只有 2 道）。
3. kdsStatis 本身不带时间戳，只能靠 date_arr 带时分秒切片反推出品时段，
   所以时段分布是额外打 24 次请求换来的；切片会漏整点边界记录，
   因此「全量」仍以不带时分秒的那次为准，切片只用来补 hour 字段。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from collections import Counter, defaultdict

# 分订单类型的超时红线（分钟）
DINE_LIMIT_MIN = 20      # 堂食
TAKE_LIMIT_MIN = 15      # 外卖
DINE = 1

KIND_NAME = {1: "堂食", 2: "小程序外卖", 4: "美团", 5: "京东", 6: "饿了么"}

# 这些菜品因制作工艺特殊（现熬粥、现包）本来就慢，计入会长期霸榜
EXCLUDE_KEYWORDS = ["三文鱼粥", "寿司包", "豆乳芝士"]


def _excluded(name):
    return any(k in (name or "") for k in EXCLUDE_KEYWORDS)


def _limit(ot):
    return DINE_LIMIT_MIN if ot == DINE else TAKE_LIMIT_MIN


def _kind(ot):
    return "dine" if ot == DINE else "take"


def _pull_all(c, ds, store_id):
    """全天全量（唯一可信的总量来源）"""
    r = c.post("/admin/food_analysis/kdsStatis", {
        "date_arr": [ds, ds], "store_ids": [store_id],
    })
    return r.get("data") or []


def _hour_map(c, ds, store_id):
    """逐小时切片，返回 {记录id: 小时}。用于还原出品时段。"""
    hm = {}
    for h in range(24):
        a = f"{ds} {h:02d}:00:00"
        b = f"{ds} {h:02d}:59:59"
        try:
            d = c.post("/admin/food_analysis/kdsStatis", {
                "date_arr": [a, b], "store_ids": [store_id],
            }).get("data") or []
        except Exception:
            continue
        for x in d:
            hm[x.get("id")] = h
    return hm


def pull_kds(ds, store_id=42, with_hour=True):
    """拉取当日出品明细，附带订单类型与出品时长"""
    c = ModaClient()
    raw = _pull_all(c, ds, store_id)
    if not raw:
        return [], 0

    hm = _hour_map(c, ds, store_id) if with_hour else {}

    items, dropped = [], 0
    for x in raw:
        ot = int(x.get("order_type") or 0)
        secs = int(x.get("use_time") or 0)
        name = (x.get("name") or "").strip()
        if _excluded(name):
            dropped += 1
            continue
        mins = secs / 60.0
        items.append({
            "id": x.get("id"),
            "food_id": x.get("food_id"),
            "name": name,
            "order_type": ot,
            "kind": _kind(ot),
            "kind_name": KIND_NAME.get(ot, f"其他({ot})"),
            "limit": _limit(ot),
            "secs": secs,
            "mins": int(round(mins)),
            "exact": round(mins, 1),
            "hour": hm.get(x.get("id")),
            "over": secs > _limit(ot) * 60,
        })
    return items, dropped


def _branch(items):
    """单渠道汇总"""
    n = len(items)
    if not n:
        return {"total": 0, "timeout": 0, "rate": 0, "avg": 0, "max": 0, "median": 0,
                "limit": 0, "over_share": 0}
    ms = sorted(i["exact"] for i in items)
    over = [i for i in items if i["over"]]
    return {
        "total": n,
        "timeout": len(over),
        "rate": round(len(over) / n * 100, 2),
        "avg": round(sum(ms) / n, 1),
        "median": round(ms[n // 2], 1),
        "max": round(ms[-1], 1),
        "limit": items[0]["limit"],
        "over_share": round(len(over) / n * 100, 2),
    }


def timeout_stats(ds, store_id=42):
    items, dropped = pull_kds(ds, store_id)
    n = len(items)
    if not n:
        return {"total": 0, "timeout": 0, "rate": 0, "top": [], "by_name": [],
                "avg": 0, "median": 0, "max": 0, "peak": [], "peak_over": [],
                "buckets": {}, "orders": 0, "excluded": 0, "excluded_names": [],
                "thr_dine": DINE_LIMIT_MIN, "thr_take": TAKE_LIMIT_MIN,
                "threshold": DINE_LIMIT_MIN,
                "dine": _branch([]), "take": _branch([])}

    ms = sorted(i["exact"] for i in items)
    over = sorted((i for i in items if i["over"]), key=lambda i: -i["exact"])

    # 超时菜品聚合（同名合并）
    agg = defaultdict(lambda: {"cnt": 0, "max": 0, "sum": 0})
    for i in over:
        a = agg[i["name"]]
        a["cnt"] += 1
        a["sum"] += i["exact"]
        a["max"] = max(a["max"], i["exact"])
    by_name = sorted(
        ({"name": k, "cnt": v["cnt"], "max": round(v["max"], 1),
          "avg": round(v["sum"] / v["cnt"], 1)} for k, v in agg.items()),
        key=lambda z: (-z["max"], -z["cnt"]),
    )

    # 时段分布：peak = 全部出品道数，peak_over = 其中超时的道数
    all_peak, over_peak = Counter(), Counter()
    for i in items:
        if i["hour"] is not None:
            all_peak[i["hour"]] += 1
            if i["over"]:
                over_peak[i["hour"]] += 1

    # 出品时长分档（按新红线切）
    buckets = Counter()
    for v in ms:
        if v <= 5:
            buckets["≤5"] += 1
        elif v <= 10:
            buckets["6-10"] += 1
        elif v <= 15:
            buckets["11-15"] += 1
        elif v <= 20:
            buckets["16-20"] += 1
        else:
            buckets[">20"] += 1

    return {
        "total": n,
        "timeout": len(over),
        "rate": round(len(over) / n * 100, 2),
        "avg": round(sum(ms) / n, 1),
        "median": round(ms[n // 2], 1),
        "max": round(ms[-1], 1),
        "threshold": DINE_LIMIT_MIN,
        "thr_dine": DINE_LIMIT_MIN,
        "thr_take": TAKE_LIMIT_MIN,
        # kdsStatis 不带订单号，无法统计"涉及多少单"，保留字段仅作兼容
        "orders": 0,
        "buckets": dict(buckets),
        "dine": _branch([i for i in items if i["kind"] == "dine"]),
        "take": _branch([i for i in items if i["kind"] == "take"]),
        "top": [
            {"name": i["name"], "mins": i["mins"], "exact": i["exact"],
             "kind_name": i["kind_name"], "limit": i["limit"], "hour": i["hour"],
             # 兼容旧渲染字段
             "order_id": None, "created": "", "delivered": ""}
            for i in over[:10]
        ],
        "by_name": by_name[:6],
        "peak": sorted(all_peak.items()),
        "peak_over": sorted(over_peak.items()),
        "excluded": dropped,
        "excluded_names": EXCLUDE_KEYWORDS,
    }


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-11-04"
    s = timeout_stats(ds)
    print(f"{ds} 出品 {s['total']} 道  "
          f"超时 {s['timeout']} 道（{s['rate']}%）  "
          f"平均 {s['avg']} 分  中位 {s['median']} 分  最长 {s['max']} 分")
    print(f"  堂食 {s['dine']['total']} 道 / 超 {s['dine']['timeout']}（>{s['thr_dine']}分，{s['dine']['rate']}%）"
          f"  均 {s['dine']['avg']} 分")
    print(f"  外卖 {s['take']['total']} 道 / 超 {s['take']['timeout']}（>{s['thr_take']}分，{s['take']['rate']}%）"
          f"  均 {s['take']['avg']} 分")
    print("  分档:", s["buckets"])
    print("  时段(道数):", s["peak"])
    print("  时段(超时):", s["peak_over"])
    print("\n超时明细:")
    for t in s["top"]:
        print(f"  {t['mins']:>3}分  {t['kind_name']:<6} {t['hour'] if t['hour'] is not None else '?':>2}时  {t['name']}")
    print("\n高频超时菜品:")
    for b in s["by_name"]:
        print(f"  {b['name'][:20]:<22} {b['cnt']} 道  最长 {b['max']}分  平均 {b['avg']}分")
