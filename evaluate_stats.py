"""
餐后评价 + 私信老板（问卷）数据拉取
接口:
  POST /admin/food_order_evaluate/index   餐后评价记录（菜单 2.7）
      参数 {page, limit, date_arr:[起,止]} —— store_id 参数无效，返回全部门店，本地按 store_id 过滤
      star: 1~2 星=差评，4~5 星=好评（老板口径）
  POST /admin/question_answer/index       问卷（私信我老板，菜单 6.7）
      无有效日期过滤参数，按 created_at 倒序翻页，本地过滤 store_id + 日期
      反馈类型从 answer JSON 的单选题「你反馈的什么内容？」里取 status==1 的选项
"""
import json

EVAL_PATH = "/admin/food_order_evaluate/index"
DM_PATH = "/admin/question_answer/index"


def _fetch_eval(client, d1, d2):
    out, page = [], 1
    while True:
        r = client.post(EVAL_PATH, {"page": page, "limit": 200,
                                    "date_arr": [d1, d2]})
        lst = r.get("data") or []
        out.extend(lst)
        total = int(r.get("count") or 0)
        if len(out) >= total or not lst or page > 30:
            break
        page += 1
    return out


def evaluate_report(client, ds, store_id, month_start=None):
    """返回 {'total','bad','good','bad_rate','m_total','m_bad','m_good','m_bad_rate'}"""
    ms = month_start or ds[:8] + "01"

    def agg(rows):
        total = len(rows)
        bad = sum(1 for x in rows if float(x.get("star") or 0) <= 2)
        good = sum(1 for x in rows if float(x.get("star") or 0) >= 4)
        return {"total": total, "bad": bad, "good": good,
                "bad_rate": round(bad / total * 100, 2) if total else 0.0}

    today = agg([x for x in _fetch_eval(client, ds, ds)
                 if x.get("store_id") == store_id])
    month = agg([x for x in _fetch_eval(client, ms, ds)
                 if x.get("store_id") == store_id])
    return {"total": today["total"], "bad": today["bad"], "good": today["good"],
            "bad_rate": today["bad_rate"],
            "m_total": month["total"], "m_bad": month["bad"],
            "m_good": month["good"], "m_bad_rate": month["bad_rate"]}


def _dm_type(row):
    """从 answer JSON 里解析反馈类型：单选题选中的选项名"""
    try:
        arr = json.loads(row.get("answer") or "[]")
        for q in arr:
            opts = q.get("answer") or []
            for o in opts:
                if o.get("status") == 1:
                    return o.get("name") or "其他反馈"
    except Exception:
        pass
    return "其他反馈"


def dm_report(client, ds, store_id):
    """当日私信老板：{'total','complaint','praise','other'}"""
    out, page = [], 1
    stop = False
    while not stop:
        r = client.post(DM_PATH, {"page": page, "limit": 100})
        lst = r.get("data") or []
        if not lst:
            break
        for x in lst:
            day = (x.get("created_at") or "")[:10]
            if day < ds:
                stop = True
                break
            if day == ds and x.get("store_id") == store_id:
                out.append(x)
        if stop or len(lst) < 100 or page > 50:
            break
        page += 1

    def pick(*keys):
        n = sum(1 for x in out if any(k in _dm_type(x) for k in keys))
        return n

    complaint = pick("投诉", "批评")
    praise = sum(1 for x in out
                 if "表扬" in _dm_type(x) or "认同" in _dm_type(x))
    return {"total": len(out), "complaint": complaint, "praise": praise,
            "other": max(len(out) - complaint - praise, 0)}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from moda_client import ModaClient
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-11-24"
    sid = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    c = ModaClient()
    print(ds, "评价:", evaluate_report(c, ds, sid))
    print(ds, "私信:", dm_report(c, ds, sid))
