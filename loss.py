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
import sys, os
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


if __name__ == "__main__":
    from moda_client import ModaClient
    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-11-04"
    sid = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    print(pull_loss(ModaClient(), ds, sid))
