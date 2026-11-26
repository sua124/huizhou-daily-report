"""
损耗（报损）数据拉取
接口: POST /admin/scm_product_stock_verify/lossStatistics   （后台菜单 6.8.25 损耗管理）
参数: {date_arr: [起, 止], store_ids: [id]}

返回结构（单日）:
  type_group.sum            损耗总额
  type_group.item / variety_dishes / sample_retention / testing / train  分类明细
  store_group[0].current_loss_price   该店本期损耗
  store_group[0].current_total_price  该店本期实收口径
  loss_rate_threshold                 损耗率红线（0.35，单位 %）
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def pull_loss(client, ds, store_id, ds_end=None):
    """返回 {'loss': 金额, 'base': 后台实收口径, 'detail': 分类明细, 'threshold': 红线%}"""
    end = ds_end or ds
    r = client.post("/admin/scm_product_stock_verify/lossStatistics",
                    {"date_arr": [ds, end], "store_ids": [store_id]})
    data = r.get("data") or {}
    tg = data.get("type_group") or {}
    sg = None
    for row in (data.get("store_group") or []):
        if row.get("store_id") == store_id:
            sg = row
            break
    if sg is None:
        sg = (data.get("store_group") or [{}])[0]

    loss = sg.get("current_loss_price")
    if loss is None:
        loss = tg.get("sum")
    try:
        threshold = float(data.get("loss_rate_threshold") or 0.35)
    except (TypeError, ValueError):
        threshold = 0.35
    return {
        "loss": round(float(loss or 0), 2),
        "base": float(sg.get("current_total_price") or 0),
        "detail": {k: tg.get(k, 0) for k in
                   ("item", "variety_dishes", "sample_retention", "testing", "train")},
        "threshold": threshold,
    }


# 报损类型枚举（后台「报损单-类型」下拉，2026-11-26 老板要求损耗前5显示原因）
# second_type=6 已用备注实证（凤梨过熟/来货破损/淤血 → 供货异常报损），
# 其余按后台下拉顺序推定
LOSS_TYPE_NAMES = {1: "品项报损", 2: "菜品报损", 3: "留样报损", 4: "试味报损",
                   5: "培训报损", 6: "供货异常报损", 7: "餐具报损"}


def loss_top5(client, ds, store_id):
    """损耗前5（品名 + 金额含税）

    口径（2026-11-25 老板要求新增）：
    - 取当天创建的报损单（/admin/scm_product_stock_verify/loss，created_at 日期=当天，
      loss_amount>0），逐单拉明细（/detail 的 cont 字段）；
    - 按商品名聚合「含税金额」= 明细里的 original_amount（含税单价×数量，原价口径），
      无含税价时退回 loss_price（不含税）；
    - 注意：与 lossStatistics 的官方损耗总额日期归属有差异（官方按库存口径），
      本接口用于「当日哪些损耗最多」的排行展示，不作红线判定。
    返回 {'top5': [{'name','amount','num','reason'}...], 'total': 当日含税合计, 'orders': 单数}
    reason = 该品名金额占比最高的报损类型（品项/菜品/留样/试味/培训/供货异常/餐具报损）
    """
    orders = []
    page = 1
    while True:
        r = client.post("/admin/scm_product_stock_verify/loss",
                        {"store_ids": [store_id], "page": page, "limit": 200})
        lst = r.get("data") or []
        if not lst:
            break
        done = False
        for x in lst:
            day = (x.get("created_at") or "")[:10]
            if day < ds:          # 列表按 created_at 倒序，越过目标日即可停
                done = True
                break
            if day == ds and float(x.get("loss_amount") or 0) > 0:
                orders.append(x)
        if done or len(lst) < 200:
            break
        page += 1
        if page > 20:
            break

    agg = {}
    total = 0.0
    for o in orders:
        reason = LOSS_TYPE_NAMES.get(o.get("second_type"), "")
        try:
            rr = client.post("/admin/scm_product_stock_verify/detail",
                             {"id": o.get("id")})
            info = (rr.get("data") or {}).get("info") or {}
            cont = json.loads(info.get("cont") or "[]")
        except Exception:
            continue
        for g in cont:
            name = (g.get("name") or "?").strip()
            amt = float(g.get("original_amount") or 0) or float(g.get("loss_price") or 0)
            num = float(g.get("num") or 0)
            it = agg.setdefault(name, {"name": name, "amount": 0.0, "num": 0.0,
                                       "reasons": {}})
            it["amount"] += amt
            it["num"] += num
            if reason:
                # 原因挂单上：同品名跨单不同原因时，按金额累计
                it["reasons"][reason] = it["reasons"].get(reason, 0.0) + amt
            total += amt

    top = sorted(agg.values(), key=lambda z: -z["amount"])[:5]
    for it in top:
        it["amount"] = round(it["amount"], 2)
        it["num"] = round(it["num"], 1)
        rs = it.pop("reasons", {})
        # 主原因 = 该品名金额占比最高的报损类型
        it["reason"] = max(rs, key=rs.get) if rs else ""
    return {"top5": top, "total": round(total, 2), "orders": len(orders)}


if __name__ == "__main__":
    from moda_client import ModaClient
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-11-04"
    sid = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    print(pull_loss(ModaClient(), ds, sid))
    print(json.dumps(loss_top5(ModaClient(), ds, sid), ensure_ascii=False, indent=1))
