"""传菜时效统计（老板拍板，2026-11-05 第二次定稿）
口径：与后台「6.8.24 传菜统计」一致 ——
      出品完成 dish_up_at → 上桌 deliver_at，超过 3 分钟记为超时，按菜品聚合
      只输出「3 分钟以上传菜数量」榜单，不算平均传菜时间
数据源：/admin/food_analysis/deliverStatistics（该接口只含堂食）
已对后台 11-04 页面逐行核对：A68融化肥肝 13道/65%、B39 3道/75% 等全部吻合
"""
import datetime
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
    agg = {}  # name -> {"total": 道, "late": >3分道}
    for x in lst:
        try:
            serve = (_dt(x["deliver_at"]) - _dt(x["dish_up_at"])).total_seconds() / 60
        except Exception:
            continue
        if serve < 0:
            continue
        name = (x.get("name") or "").strip()
        if any(k in name for k in EXCLUDE_KEYWORDS):
            continue
        a = agg.setdefault(name, {"total": 0, "late": 0})
        a["total"] += 1
        if serve > LATE_MIN:
            a["late"] += 1

    total = sum(a["total"] for a in agg.values())
    late = sum(a["late"] for a in agg.values())
    by_name = [
        {"name": n, "total": a["total"], "late": a["late"],
         "ratio": round(a["late"] / a["total"] * 100, 1)}
        for n, a in agg.items() if a["late"] > 0
    ]
    # 与后台一致：按超时占比降序，同占比按数量降序
    by_name.sort(key=lambda z: (-z["ratio"], -z["late"]))
    return {"total": total, "late": late, "rate": round(late / total * 100, 1) if total else 0,
            "by_name": by_name}
