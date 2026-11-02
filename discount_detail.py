"""
折扣明细：按折扣原因聚合
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from collections import defaultdict


def pull_discount_detail(ds, store_id=16):
    c = ModaClient()
    r = c.post("/admin/food_analysis/discountDetail", {
        "date_arr": [ds, ds], "store_ids": [store_id], "page": 1, "limit": 500,
    })
    d = r.get("data")
    lst = d if isinstance(d, list) else (d.get("list") if isinstance(d, dict) else [])

    items = []
    for x in lst:
        try:
            amt = float(x.get("discount_price") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        items.append({
            "name": x.get("name") or "",
            "amount": amt,
            "num": x.get("num"),
            "orig": float(x.get("food_total_price") or 0),
            "discount": x.get("discount"),
            "reason": (x.get("refund_remark") or "").split(";")[-1].strip() if x.get("refund_remark") else "",
            "admin": (x.get("refund_admin_name") or "").strip(),
            "time": (x.get("created_at") or "")[11:16],
            "table": x.get("table_name") or "",
        })
    items.sort(key=lambda i: -i["amount"])

    # 折扣份数（菜品件数，与条数区分）
    qty = 0
    for i in items:
        try:
            qty += float(i["num"] or 0)
        except (TypeError, ValueError):
            qty += 1

    by_reason = defaultdict(lambda: {"cnt": 0, "amt": 0.0})
    for i in items:
        key = i["reason"] or "未标注"
        by_reason[key]["cnt"] += 1
        by_reason[key]["amt"] += i["amount"]

    # 按桌台聚合（哪张桌打了多少折扣）
    by_table = defaultdict(lambda: {"cnt": 0, "amt": 0.0, "reasons": set(), "items": [],
                                    "discounts": set(), "orig": 0.0})
    for i in items:
        key = i["table"] or "未知"
        by_table[key]["cnt"] += 1
        by_table[key]["amt"] += i["amount"]
        by_table[key]["orig"] += i.get("orig", 0)
        if i["reason"]:
            by_table[key]["reasons"].add(i["reason"])
        if i.get("discount"):
            by_table[key]["discounts"].add(i["discount"])
        by_table[key]["items"].append(i["name"])

    # 按桌台：折扣率（折扣力度）从低到高＝折扣力度从高到低
    # 一桌多档时取最低折扣值（折扣最狠的那档）作为排序依据
    def _worst_rate(t):
        ds = t.get("discounts") or []
        return min(ds) if ds else 999

    table_sorted = sorted(
        ({"table": k, "cnt": v["cnt"], "amt": round(v["amt"], 2),
          "orig": round(v["orig"], 2),
          "rate": round(v["amt"] / v["orig"] * 100, 1) if v["orig"] else 0,
          "discounts": sorted(v["discounts"]),
          "reasons": sorted(v["reasons"]), "items": v["items"]}
         for k, v in by_table.items()),
        key=lambda z: (_worst_rate(z), -z["amt"]),
    )

    # 按折扣力度归类（90=9折 / 80=8折 / 69=6.9折）
    by_discount = defaultdict(lambda: {"cnt": 0, "amt": 0.0, "orig": 0.0,
                                       "tables": set(), "reasons": set()})
    for i in items:
        d = i.get("discount") or 0
        if not d:
            continue
        b = by_discount[d]
        b["cnt"] += 1
        b["amt"] += i["amount"]
        b["orig"] += i.get("orig", 0)
        if i["table"]:
            b["tables"].add(i["table"])
        if i["reason"]:
            b["reasons"].add(i["reason"])

    discount_sorted = sorted(
        ({"discount": d, "label": f"{d/10:g} 折", "cnt": v["cnt"],
          "amt": round(v["amt"], 2), "orig": round(v["orig"], 2),
          "rate": round(v["amt"] / v["orig"] * 100, 1) if v["orig"] else 0,
          "tables": len(v["tables"]), "reasons": sorted(v["reasons"])}
         for d, v in by_discount.items()),
        key=lambda z: (-z["tables"], -z["amt"]),  # 按折扣桌数从高到低
    )

    return {
        "items": items,
        "total": round(sum(i["amount"] for i in items), 2),
        "count": len(items),
        "qty": int(qty) if float(qty).is_integer() else round(qty, 1),
        "by_reason": {k: v for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1]["amt"])},
        "by_table": table_sorted,
        "by_discount": discount_sorted,
    }


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    d = pull_discount_detail(ds)
    print(f"{ds} 折扣 {d['count']} 条 合计 {d['total']:.2f}\n")
    for k, v in d["by_reason"].items():
        print(f"  {k}: {v['cnt']} 条, {v['amt']:.2f} 元")
