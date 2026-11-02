"""
菜品停/开售记录（后台：数据中心 → 菜品停开售操作记录）
接口: /admin/food_store_sale_operate_record/index
参数: page / limit / store_ids[] / food_ids[] / classify_id / created_arr[起,止] / update_arr[]
字段:
  field       is_sale=停开售 / is_show=上下架 / daily_sale_status=当日估清
  close_admin + created_at   停售操作人与时间
  open_admin  + updated_at   开售操作人与时间（为空表示尚未恢复）
菜品名通过 /admin/food/getList 建 id→name 字典，本地缓存到 food_names.json
"""
import datetime
import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "food_names.json")

FIELD_NAME = {
    "is_sale": "停开售",
    "is_show": "上下架",
    "daily_sale_status": "当日估清",
}


def food_names(client, force=False):
    """菜品 id→name 字典，带本地缓存；发现缺失的 id 时自动刷新全表"""
    names = {}
    if not force and os.path.exists(CACHE):
        try:
            names = {int(k): v for k, v in
                     json.load(open(CACHE, encoding="utf-8")).items()}
        except Exception:
            names = {}
    need_refresh = force or not names
    if not need_refresh:
        return names
    page = 1
    while True:
        r = client.post("/admin/food/getList", {"page": page, "limit": 200})
        d = r.get("data") or []
        if not d:
            break
        for f in d:
            if f.get("id") is not None:
                names[f["id"]] = f.get("name") or ""
        if len(d) < 200:
            break
        page += 1
        time.sleep(0.05)
    try:
        json.dump(names, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return names


def _mins(a, b):
    try:
        return int((b - a).total_seconds() // 60)
    except Exception:
        return None


def pull_sale_operate(client, target_date, store_id, limit=100):
    """拉取某门店某天的停/开售操作记录"""
    rows = []
    page = 1
    while True:
        r = client.post("/admin/food_store_sale_operate_record/index", {
            "page": page, "limit": limit,
            "store_ids": [store_id], "food_ids": [],
            "classify_id": "", "created_arr": [target_date, target_date],
            "update_arr": [],
        })
        d = r.get("data") or []
        rows.extend(d)
        total = r.get("count") or 0
        if not d or len(rows) >= total:
            break
        page += 1
        time.sleep(0.05)

    names = food_names(client)
    miss = [x.get("food_id") for x in rows if x.get("food_id") not in names]
    if miss:
        names = food_names(client, force=True)

    items = []
    for x in rows:
        try:
            close_dt = datetime.datetime.strptime(
                x.get("created_at", ""), "%Y-%m-%d %H:%M:%S")
        except Exception:
            close_dt = None
        open_admin = (x.get("open_admin") or "").strip()
        open_dt = None
        if open_admin:
            try:
                open_dt = datetime.datetime.strptime(
                    x.get("updated_at", ""), "%Y-%m-%d %H:%M:%S")
            except Exception:
                open_dt = None
        mins = _mins(close_dt, open_dt) if (close_dt and open_dt) else None
        # 恢复时间跨天时标注「次日」，避免看起来像倒挂
        open_label = ""
        if open_admin and open_dt:
            open_label = (x.get("updated_at") or "")[11:16]
            if (x.get("updated_at") or "")[:10] != target_date:
                open_label = f"次日{open_label}"
        items.append({
            "food_id": x.get("food_id"),
            "name": names.get(x.get("food_id"), f"菜品#{x.get('food_id')}"),
            "field": x.get("field", ""),
            "field_name": FIELD_NAME.get(x.get("field", ""), x.get("field", "") or "-"),
            "close_time": (x.get("created_at") or "")[11:16],
            "close_admin": x.get("close_admin") or "-",
            "open_time": open_label,
            "open_admin": open_admin or "",
            "reopened": bool(open_admin),
            "mins": mins,
            "close_full": x.get("created_at") or "",
            "open_full": x.get("updated_at") or "" if open_admin else "",
        })

    items.sort(key=lambda v: v["close_full"])
    reopened = [i for i in items if i["reopened"]]
    closed = [i for i in items if not i["reopened"]]
    mlist = [i["mins"] for i in reopened if i["mins"] is not None]
    return {
        "total": len(items),
        "dishes": len({i["food_id"] for i in items}),
        "reopened": len(reopened),
        "closed": len(closed),
        "avg_mins": round(sum(mlist) / len(mlist)) if mlist else None,
        "by_field": {fn: sum(1 for i in items if i["field_name"] == fn)
                     for fn in FIELD_NAME.values()},
        "items": items,
    }


if __name__ == "__main__":
    import sys
    from moda_client import ModaClient
    td = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    c = ModaClient()
    res = pull_sale_operate(c, td, 42)
    print(f"{td} 停/开售 {res['total']} 条 · 涉及 {res['dishes']} 个菜品 · "
          f"已恢复 {res['reopened']} · 未恢复 {res['closed']}")
    for i in res["items"]:
        print(f"  {i['close_time']} {i['name']} [{i['field_name']}] "
              f"停售人 {i['close_admin']} → 恢复 {i['open_time'] or '未恢复'} "
              f"{i['open_admin']}")
