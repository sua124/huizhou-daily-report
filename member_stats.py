"""
会员复购数据（后台「6.9.10 复购率汇总」，接口 /admin/food_analysis/repurchase）

口径（与后台一致）：统计期内消费 N 次的人数 = num_N；
  会员消费人次 = Σ total_num；首次消费人次 = Σ num_1；
  复购人数 = Σ num_2..num_10；复购率 = 复购人数 / 会员消费人次。
月度趋势 = 按月分别调用（近 3 个完整月 + 当前月）。
"""
import datetime


def _month_shift(d, k):
    """日期 d 所在月份往前推 k 个月，返回该月 1 号"""
    y, m = d.year, d.month - k
    while m <= 0:
        m += 12
        y -= 1
    return d.replace(year=y, month=m, day=1)


def pull_repurchase(c, d1, d2, store_id):
    """拉取 [d1, d2] 区间的会员复购汇总，按等级聚合"""
    r = c.post("/admin/food_analysis/repurchase", {
        "date_arr": [d1, d2], "store_ids": [store_id], "page": 1, "limit": 10,
    })
    rows = (r.get("data") or {}).get("list") or []
    total = first = repeat = 0
    tiers = []
    for x in rows:
        t = int(x.get("total_num") or 0)
        n1 = int(x.get("num_1") or 0)
        rep = sum(int(x.get(f"num_{k}") or 0) for k in range(2, 11))
        total += t
        first += n1
        repeat += rep
        tiers.append({
            "name": (x.get("member_type_name") or "").strip(),
            "total": t, "first": n1, "repeat": rep,
            "rate": round(rep / t * 100, 2) if t else 0,
            "first_rate": round(n1 / t * 100, 2) if t else 0,
        })
    return {
        "total": total, "first": first, "repeat": repeat,
        "rate": round(repeat / total * 100, 2) if total else 0,
        "tiers": tiers,
    }


def member_report(c, tgt, store_id):
    """
    会员复购完整报告（共 5 次请求，只有目标日拉）：
      today: 当日     month: 本月累计（月初 → 当日）
      trend: 近 3 个完整月 + 当前月的复购率
    """
    tgt = datetime.date.fromisoformat(tgt) if isinstance(tgt, str) else tgt
    today = pull_repurchase(c, tgt.isoformat(), tgt.isoformat(), store_id)

    month_start = tgt.replace(day=1)
    month = pull_repurchase(c, month_start.isoformat(), tgt.isoformat(), store_id)

    trend = []
    for k in (3, 2, 1):  # 近 3 个完整月
        m0 = _month_shift(month_start, k)
        m1 = _month_shift(month_start, k - 1) - datetime.timedelta(days=1)
        s = pull_repurchase(c, m0.isoformat(), m1.isoformat(), store_id)
        trend.append({"label": f"{m0.month}月", "rate": s["rate"],
                      "repeat": s["repeat"], "total": s["total"]})
    trend.append({"label": f"{month_start.month}月至今", "rate": month["rate"],
                  "repeat": month["repeat"], "total": month["total"]})

    return {"date": tgt.isoformat(), "today": today, "month": month, "trend": trend}


if __name__ == "__main__":
    import sys, os, json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from moda_client import ModaClient
    c = ModaClient()
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    sid = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    rep = member_report(c, d, sid)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
