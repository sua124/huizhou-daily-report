"""
拉取指定日期门店完整数据，生成三张日报图（部署包版：门店参数从 config.json 读取）
用法: python daily_report.py [YYYY-MM-DD]  (默认今天)
"""
import json, sys, os, datetime, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moda_client import ModaClient
from render_report import build_all
from order_split import split_orders
from channel_stats import channel_stats
from send_detail import pull_send_detail
from discount_detail import pull_discount_detail
from timeout_top import timeout_stats
from sale_operate import pull_sale_operate
from loss import pull_loss

_CFG = {}
_FULL_CFG = {}
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
if os.path.exists(_cfg_path):
    _FULL_CFG = json.load(open(_cfg_path, encoding="utf-8"))
    _CFG = _FULL_CFG.get("store", {})

STORE_ID = _CFG.get("store_id", 16)
# 门店实际营业桌数（用于翻台率），按门店口径修改
TABLE_COUNT = _CFG.get("table_count", 43)
STORE_LABEL = _CFG.get("store_label", "正佳广场店")

# 营业目标：工作日 / 周五 / 周末 三档 + 月度目标
TARGETS = _FULL_CFG.get("targets", {})


def target_for(ds, targets=None):
    """按星期几取当天营业目标：周五单独一档，周六周日一档，其余工作日一档"""
    t = TARGETS if targets is None else targets
    wd = datetime.date.fromisoformat(ds).weekday()  # 0=周一
    if wd == 4:
        return float(t.get("friday", 0) or 0)
    if wd >= 5:
        return float(t.get("weekend", 0) or 0)
    return float(t.get("weekday", 0) or 0)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "output")
os.makedirs(DATA, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def pull(target_date=None, lookback=14):
    """
    注意：后台 storeBusinessPool 在【跨日区间查询】时，会把"当天"的流水重复计算
    （单日查 64,589，跨日查询却给 129,179）。因此：
      - 历史日期：用区间查询
      - 目标日/当天：单独单日查询，避免翻倍
    """
    c = ModaClient()
    tgt = datetime.date.fromisoformat(target_date) if target_date else datetime.date.today()
    start = tgt - datetime.timedelta(days=lookback)
    prev_day = tgt - datetime.timedelta(days=1)

    base_rows = {}

    def fetch_pool(s, e):
        r = c.post("/admin/food_analysis/storeBusinessPool", {
            "date_arr": [s, e], "store_ids": [STORE_ID],
            "order": "store_date", "row_show": "store_date",
        })
        out = {}
        for row in r.get("data", {}).get("list", []):
            d = row.get("date")
            if not d or row.get("store_id") != STORE_ID:
                continue
            if str(row.get("store_name", "")).strip() == "合计":
                continue
            out[d] = row
        return out

    # 历史区间（不含目标日）
    if start <= prev_day:
        base_rows.update(fetch_pool(start.isoformat(), prev_day.isoformat()))
    # 目标日单独查
    base_rows.update(fetch_pool(tgt.isoformat(), tgt.isoformat()))

    # 月累计实收：只查「月初 → 昨天」这段历史区间（区间含今天会把今天算两遍）
    month_key = tgt.strftime("%Y-%m")
    month_start = tgt.replace(day=1)
    month_pay = 0.0
    if month_start <= prev_day:
        for _d, _r in fetch_pool(month_start.isoformat(), prev_day.isoformat()).items():
            if _d.startswith(month_key):
                month_pay += float(_r.get("pay_price") or 0)

    rows = []
    for ds in sorted(base_rows):
        b = base_rows[ds]
        rr = c.post("/admin/food_analysis/businessStatistics", {
            "date_arr": [ds, ds], "store_ids": [STORE_ID],
            "type": "index", "category_type": 1,
        })
        lst = rr.get("data", {}).get("list", [])
        x = lst[0] if lst else {}
        # 订单类型拆解（只算已结账）
        try:
            sp = split_orders(ds, STORE_ID)
        except Exception:
            sp = {"dine_in": 0, "takeout": 0, "takeout_detail": {}}
        # 三大外卖平台明细
        try:
            channels, _, dinein = channel_stats(ds, STORE_ID)
        except Exception:
            channels, dinein = [], {"revenue": 0, "orders": 0}
        # 赠菜明细
        try:
            sd = pull_send_detail(ds, STORE_ID)
        except Exception:
            sd = {"items": [], "total": 0, "count": 0, "qty": 0, "by_reason": {}}
        # 折扣明细
        try:
            dd = pull_discount_detail(ds, STORE_ID)
        except Exception:
            dd = {"items": [], "total": 0, "count": 0, "qty": 0, "by_reason": {}, "by_table": []}
        # 出品超时（菜品维度，下单→传菜 > 20 分钟）
        try:
            ts = timeout_stats(ds, STORE_ID)
        except Exception:
            ts = {"total": 0, "timeout": 0, "rate": 0, "top": [], "by_name": []}
        # 菜品停/开售记录（KDS 出餐/撤回）
        try:
            kd = pull_sale_operate(c, ds, STORE_ID)
        except Exception:
            kd = {"served": 0, "recall": 0, "total": 0, "recalls": []}
        # 损耗（报损单）
        try:
            lo = pull_loss(c, ds, STORE_ID)
        except Exception:
            lo = {"loss": 0, "base": 0, "detail": {}, "threshold": 0.35}
        # 堂食 / 外卖实收拆分（后台直接给堂食口径，外卖=总额减堂食）
        _pay = float(b.get("pay_price") or 0)
        _dine_pay = float(b.get("in_pay_price") or 0)
        _take_pay = round(_pay - _dine_pay, 2)
        _dine_ord = sp.get("dine_in", 0) or 0
        _take_ord = sp.get("takeout", 0) or 0
        rows.append({
            "date": ds,
            "weekday": "一二三四五六日"[datetime.date.fromisoformat(ds).weekday()],
            "revenue": b.get("total_price", 0),
            "send": x.get("send_price", 0),
            "discount": x.get("discount_price", 0),
            "coupon": x.get("coupon_price", 0),
            "meituan_discount": x.get("meituan_discount_price", 0),
            "meituan_service": x.get("meituan_service_price", 0),
            "favourable": b.get("favourable_price", 0),
            "pay": b.get("pay_price", 0),
            "orders": b.get("order_num", 0),
            "dine_in": sp.get("dine_in", 0),
            "takeout": sp.get("takeout", 0),
            "takeout_detail": sp.get("takeout_detail", {}),
            "channels": channels,
            "dinein_revenue": dinein.get("revenue", 0),
            "dinein_avg": round(dinein["revenue"] / dinein["orders"], 2)
                          if dinein.get("orders") else 0,
            "send_detail": sd,
            "discount_detail": dd,
            "send_qty": sd.get("qty", 0),
            "discount_count": dd.get("count", 0),
            "discount_qty": dd.get("qty", 0),
            "discount_tables": len(dd.get("by_table") or []),
            "timeout": ts,
            "sale": kd,
            "loss": lo.get("loss", 0),
            "loss_base": lo.get("base", 0),
            "loss_threshold": lo.get("threshold", 0.35),
            "target": target_for(ds),
            "dine_pay": _dine_pay,
            "takeout_pay": _take_pay,
            "dinein_orders": _dine_ord,
            "takeout_orders": _take_ord,
            "dinein_avg": round(_dine_pay / _dine_ord, 2) if _dine_ord else 0,
            "takeout_avg": round(_take_pay / _take_ord, 2) if _take_ord else 0,
            "people": b.get("people_num", 0),
            "order_avg": b.get("order_total_vag", 0),
            "people_avg": b.get("people_total_vag", 0),
            "table_open": b.get("table_open") or 0,
            "table_num_sys": b.get("table_num") or 0,
            "table_seat": b.get("table_seat_num") or 0,
            "table_count": TABLE_COUNT,
            "turnover": round((b.get("table_open") or 0) / TABLE_COUNT, 2),
            "table_avg": b.get("table_total_vag", 0),
        })
        time.sleep(0.05)

    # 月累计：月初→昨天（上面单独查）+ 当天实收
    if rows:
        rows[-1]["month_pay"] = round(month_pay + float(rows[-1].get("pay") or 0), 2)
        rows[-1]["month_target"] = float(TARGETS.get("month") or 0)

    path = os.path.join(DATA, f"report_{tgt.isoformat()}.json")
    json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path, rows


if __name__ == "__main__":
    td = sys.argv[1] if len(sys.argv) > 1 else None
    path, rows = pull(td)
    last = rows[-1]
    print(f"日期 {last['date']}  营业额 {last['revenue']:,.2f}  赠菜 {last['send']:.2f}  "
          f"折扣 {last['discount']:.2f}  实收 {last['pay']:,.2f}  订单 {last['orders']}  客流 {last['people']}")
    pngs = build_all(path, OUT, STORE_LABEL)
    for p in pngs:
        print("saved:", p)
