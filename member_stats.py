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


def daily_trend(c, tgt, store_id, days=14, window=7, workers=4):
    """
    近 N 天的「日复购率」= 滚动窗口口径（默认 7 天）：
    第 d 天的值 = [d-6, d] 这 7 天的复购率。
    单日当天复购（同一天来两趟）几乎恒为 0，没有观察价值，所以用滚动窗口。
    每天一次请求（共 days 次），多线程并发（每线程独立客户端，token 走缓存）。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from moda_client import ModaClient

    tgt = datetime.date.fromisoformat(tgt) if isinstance(tgt, str) else tgt
    day_list = [tgt - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]
    tlocal = threading.local()

    def one(d):
        cli = getattr(tlocal, "c", None)
        if cli is None:
            cli = ModaClient()
            tlocal.c = cli
        d1 = d - datetime.timedelta(days=window - 1)
        s = pull_repurchase(cli, d1.isoformat(), d.isoformat(), store_id)
        return {"date": d.isoformat(), "label": f"{d.month}/{d.day}",
                "rate": s["rate"], "repeat": s["repeat"], "total": s["total"]}

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            return list(ex.map(one, day_list))
    except Exception:
        return []


def pull_new_members(c, tgt, store_id, days=14):
    """
    每日新增会员（注册日 = user.created_at）。
    注意：/admin/user/index 的 created_arr 实际不生效，接口固定按注册时间倒序返回，
    所以一次多拉几页、再本地按日期分组（14 天约 500~700 条，1~2 次请求足够）。
    """
    tgt = datetime.date.fromisoformat(tgt) if isinstance(tgt, str) else tgt
    need_from = tgt - datetime.timedelta(days=days - 1)
    month_start = tgt.replace(day=1)
    oldest = min(need_from, month_start)

    rows, page, limit = [], 1, 1000
    while page <= 3:
        r = c.post("/admin/user/index", {
            "created_arr": [oldest.isoformat(), tgt.isoformat()],
            "store_ids": [store_id], "page": page, "limit": limit,
        })
        lst = r.get("data") or []
        rows += [x for x in lst if int(x.get("store_id") or 0) == int(store_id)]
        if len(lst) < limit:
            break
        earliest = min((str(x.get("created_at"))[:10] for x in lst), default="9999")
        if earliest < oldest.isoformat():
            break
        page += 1

    cnt = {}
    for x in rows:
        d = str(x.get("created_at") or "")[:10]
        if d:
            cnt[d] = cnt.get(d, 0) + 1

    series = []
    for i in range(days - 1, -1, -1):
        d = tgt - datetime.timedelta(days=i)
        k = d.isoformat()
        series.append({"date": k, "label": f"{d.month}/{d.day}", "count": cnt.get(k, 0)})

    return {
        "daily": series,
        "today": cnt.get(tgt.isoformat(), 0),
        "month": sum(v for k, v in cnt.items()
                     if month_start.isoformat() <= k <= tgt.isoformat()),
        "total": sum(v for k, v in cnt.items() if k >= need_from.isoformat()),
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

    # 近 14 日日复购率（滚动 7 天口径）
    try:
        daily = daily_trend(c, tgt, store_id)
    except Exception:
        daily = []

    # 每日新增会员
    try:
        new_members = pull_new_members(c, tgt, store_id)
    except Exception:
        new_members = {}

    return {"date": tgt.isoformat(), "today": today, "month": month,
            "trend": trend, "daily": daily, "daily_window": 7,
            "new_members": new_members}


if __name__ == "__main__":
    import sys, os, json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from moda_client import ModaClient
    c = ModaClient()
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    sid = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    rep = member_report(c, d, sid)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
