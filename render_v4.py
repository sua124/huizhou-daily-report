"""
营业日报（4 店式单页版）渲染器

版式对照 4 店(领展广场店) 日报：
  深色页头 → 12 个核心指标卡片（含目标达成 / 损耗）→ 超时分析 4 卡 → 近 7 日两张表

与旧版图 1 的区别：
  - 营业额按实收口径（与"当日目标达成"同口径，和 4 店一致）
  - 新增：堂食/外卖拆分、当日目标达成、月累计达成、损耗金额与占比
  - 近 7 日表把赠菜/折扣/损耗并到一张，另加"营业额达成"表
"""
import datetime
from PIL import Image, ImageDraw

from render_report import (W, PAD, CARD, INK, INK2, INK3, LINE, ACCENT,
                           UP, DOWN, HILITE, HILITE_BG, F, money)

DARK = "#16233A"          # 页头深蓝
DARK_SUB = "#93A8C0"
CARD_LINE = "#EDEFF3"
TH_BG = "#F2F4F7"
SUM_BG = "#FAFBFC"


def m2(v):
    try:
        return f"{float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "-"


def pctv(a, b, digits=2):
    """a 占 b 的百分比字符串"""
    try:
        if not b:
            return "-"
        return f"{a / b * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def chg(cur, base):
    """环比字符串 + 颜色（涨红跌绿，国内习惯）"""
    if not base:
        return "环比 -", INK3
    v = (cur - base) / base * 100
    arrow = "▲" if v >= 0 else "▼"
    return f"{arrow}{abs(v):.1f}%", (UP if v >= 0 else DOWN)


class Page:
    def __init__(self, last, store_label, subtitle):
        self.H = 6000
        self.img = Image.new("RGB", (W, self.H), "#FFFFFF")
        self.dr = ImageDraw.Draw(self.img)
        self._header(last, store_label, subtitle)
        self.y = 236

    def _header(self, last, store_label, subtitle):
        dr = self.dr
        dr.rectangle([0, 0, W, 168], fill=DARK)
        dr.text((PAD, 42), f"{store_label} · 营业日报", font=F(42, True), fill="#FFFFFF")
        dr.text((PAD, 108), subtitle, font=F(21), fill=DARK_SUB)
        dt = datetime.date.fromisoformat(last["date"])
        wk = "一二三四五六日"[dt.weekday()]
        dr.text((W - PAD, 108), f"{last['date']}  周{wk}", font=F(21), fill=DARK_SUB,
                anchor="ra")
        dr.text((PAD, 194), f"数据日期：{last['date']}", font=F(22), fill=INK2)

    # ---------- 组件 ----------
    def section(self, title, gap=26):
        self.y += gap
        self.dr.rectangle([PAD, self.y + 4, PAD + 6, self.y + 30], fill=ACCENT)
        self.dr.text((PAD + 18, self.y), title, font=F(27, True), fill=INK)
        self.y += 50

    def cards(self, items, cols=4, height=132, gap=14):
        dr, y = self.dr, self.y
        cw = (W - PAD * 2 - gap * (cols - 1)) // cols
        for idx, it in enumerate(items):
            r, cidx = divmod(idx, cols)
            x = PAD + cidx * (cw + gap)
            yy = y + r * (height + gap)
            label = it.get("label", "")
            value = it.get("value", "-")
            sub = it.get("sub", "")
            extra = it.get("extra", "")
            vcolor = it.get("color", INK)
            hl = it.get("hl", False)
            dr.rounded_rectangle([x, yy, x + cw, yy + height], 12,
                                 fill=HILITE_BG if hl else CARD,
                                 outline=HILITE if hl else CARD_LINE, width=2 if hl else 1)
            dr.text((x + 18, yy + 18), label, font=F(20, True),
                    fill=HILITE if hl else INK2)
            dr.text((x + 18, yy + 50), value, font=F(34, True), fill=HILITE if hl else vcolor)
            if sub:
                dr.text((x + 18, yy + height - 34), sub, font=F(17),
                        fill=HILITE if hl else INK3)
            if extra:
                dr.text((x + cw - 16, yy + 20), extra, font=F(17, True),
                        fill=HILITE if hl else INK3, anchor="ra")
        rows = (len(items) + cols - 1) // cols
        self.y = y + rows * (height + gap)

    def table(self, headers, rows, widths, aligns=None, sum_row=None,
              row_h=52, head_h=54, colors=None):
        """通用表格：headers 列表、rows 二维、widths 像素宽（合计=内容区宽）"""
        dr = self.dr
        aligns = aligns or ["center"] * len(headers)
        total_w = sum(widths)
        x0 = PAD + (W - PAD * 2 - total_w) // 2

        def cell(x, y, w, h, text, font, color, align):
            anchor = {"left": "lm", "center": "mm", "right": "rm"}[align]
            px = x + 14 if align == "left" else (x + w - 14 if align == "right" else x + w // 2)
            dr.text((px, y + h // 2), str(text), font=font, fill=color, anchor=anchor)

        # 表头
        dr.rectangle([x0, self.y, x0 + total_w, self.y + head_h], fill=TH_BG)
        cx = x0
        for i, h in enumerate(headers):
            cell(cx, self.y, widths[i], head_h, h, F(19, True), INK2, aligns[i])
            cx += widths[i]
        self.y += head_h

        # 数据行
        for r_i, row in enumerate(rows):
            if r_i % 2 == 1:
                dr.rectangle([x0, self.y, x0 + total_w, self.y + row_h], fill="#FCFCFD")
            cx = x0
            for i, v in enumerate(row):
                color = INK
                if colors and colors(r_i, i, v):
                    color = colors(r_i, i, v)
                cell(cx, self.y, widths[i], row_h, v, F(19), color, aligns[i])
                cx += widths[i]
            # 分隔线
            dr.line([x0, self.y + row_h, x0 + total_w, self.y + row_h], fill=LINE)
            self.y += row_h

        # 合计行
        if sum_row:
            dr.rectangle([x0, self.y, x0 + total_w, self.y + row_h], fill=SUM_BG)
            cx = x0
            for i, v in enumerate(sum_row):
                cell(cx, self.y, widths[i], row_h, v, F(19, True), INK, aligns[i])
                cx += widths[i]
            self.y += row_h
        self.y += 10

    def note(self, text, size=17, color=None, gap=8):
        self.y += gap
        self.dr.text((PAD, self.y), text, font=F(size), fill=color or INK3)
        self.y += 28

    def save(self, path):
        out = self.img.crop((0, 0, W, min(self.y + 24, self.H)))
        out.save(path, "PNG", quality=95)
        return path


def _timeout_peak(ts):
    """超时高峰时段文案。peak_over 是 [(小时, 超时菜道数), ...]"""
    peak = ts.get("peak_over") or []
    if not peak:
        return "-", "无超时"
    hour, cnt = max(peak, key=lambda z: z[1])
    total = ts.get("timeout") or 1
    sub = f"{cnt} 道 · 占超时 {cnt / total * 100:.0f}%"
    return f"{hour:02d}:00—{hour + 1:02d}:00", sub


def build_page(rows, out_path, store_label="惠州店",
               subtitle="摩打食堂 · 数据中心自动日报"):
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    p = Page(last, store_label, subtitle)

    pay = float(last.get("pay") or 0)
    target = float(last.get("target") or 0)
    rate = pay / target * 100 if target else 0
    month_pay = float(last.get("month_pay") or 0)
    month_target = float(last.get("month_target") or 0)
    m_rate = month_pay / month_target * 100 if month_target else 0

    t_chg, t_col = chg(pay, prev.get("pay") if prev else None)

    # ===== 第一组：经营结果 =====
    p.cards([
        {"label": "营业额（元）", "value": m2(pay), "extra": t_chg, "color": INK},
        {"label": "订单数", "value": f"{last.get('orders', 0):,}",
         "sub": f"堂食 {last.get('dinein_orders', 0)} · 外卖 {last.get('takeout_orders', 0)}"},
        {"label": "堂食营业额（元）", "value": m2(last.get("dine_pay")),
         "sub": f"{last.get('table_open', 0)} 桌 · 客单价 ¥{m2(last.get('dinein_avg', 0))}"},
        {"label": "外卖营业额（元）", "value": m2(last.get("takeout_pay")),
         "sub": f"{last.get('takeout_orders', 0)} 单 · 均价 ¥{m2(last.get('takeout_avg', 0))}"},
    ])

    # ===== 第二组：目标与优惠 =====
    goal_color = DOWN if rate >= 100 else UP
    p.cards([
        {"label": "当日目标达成", "value": f"{rate:.1f}%" if target else "-",
         "sub": f"目标 ¥{money(target)}", "extra": f"差 {m2(pay - target)}" if target else "",
         "color": goal_color, "hl": rate < 90 and target > 0},
        {"label": "月累计达成", "value": f"{m_rate:.1f}%" if month_target else "-",
         "sub": f"月目标 ¥{money(month_target)}", "extra": m2(month_pay),
         "color": DOWN if m_rate >= 100 else UP},
        {"label": "折扣金额（元）", "value": m2(last.get("discount")),
         "sub": f"折扣 {last.get('discount_count', 0)} 单"},
        {"label": "折扣占实收", "value": pctv(last.get("discount"), pay),
         "sub": "按实收计算"},
    ])

    # ===== 第三组：赠菜与损耗 =====
    loss = float(last.get("loss") or 0)
    loss_rate = loss / pay * 100 if pay else 0
    thr = float(last.get("loss_threshold") or 0.35)
    p.cards([
        {"label": "赠菜金额（元）", "value": m2(last.get("send")),
         "sub": f"赠送 {last.get('send_qty', 0)} 份"},
        {"label": "赠菜占实收", "value": pctv(last.get("send"), pay), "sub": "按实收计算"},
        {"label": "损耗金额（元）", "value": m2(loss),
         "sub": f"门店报损 · 红线 {thr:g}%"},
        {"label": "损耗占实收", "value": f"{loss_rate:.2f}%",
         "color": UP if loss_rate > thr else INK,
         "hl": loss_rate > thr,
         "sub": "超红线" if loss_rate > thr else "正常"},
    ])

    # ===== 超时分析 =====
    ts = last.get("timeout") or {}
    prev_ts = (prev or {}).get("timeout") or {}
    peak_txt, peak_sub = _timeout_peak(ts)
    thr_dine = ts.get("thr_dine", 20)
    thr_take = ts.get("thr_take", 15)
    over_chg, _ = chg(ts.get("timeout", 0), prev_ts.get("timeout") or None)
    out_chg, _ = chg(ts.get("total", 0), prev_ts.get("total") or None)

    p.section("出品超时")
    p.cards([
        {"label": "出品数量", "value": f"{ts.get('total', 0):,}",
         "sub": f"菜品道数 · {out_chg}"},
        {"label": "超时出品数", "value": f"{ts.get('timeout', 0)}",
         "color": UP if ts.get("timeout") else INK,
         "sub": f"堂食>{thr_dine}分/外卖>{thr_take}分 · {over_chg}"},
        {"label": "超时占比", "value": f"{ts.get('rate', 0):.2f}%",
         "color": UP if ts.get("rate", 0) > 3 else INK,
         "sub": f"平均出品 {(ts.get('dine') or {}).get('avg', 0):.1f} 分（堂食）"},
        {"label": "超时高峰时段", "value": peak_txt, "sub": peak_sub},
    ], cols=4, height=122)

    # ===== 近 7 日：赠菜 / 折扣 / 损耗 =====
    last7 = rows[-7:]
    p.section("近 7 日营业额与赠菜/折扣/损耗（单位：元）")
    headers = ["日期", "实收", "赠菜", "赠菜%", "折扣", "折扣%", "损耗", "损耗%"]
    widths = [144, 144, 120, 108, 120, 108, 120, 120]
    body, sum_send, sum_disc, sum_loss, sum_pay = [], 0, 0, 0, 0
    for r in last7:
        s = float(r.get("send") or 0)
        d = float(r.get("discount") or 0)
        l = float(r.get("loss") or 0)
        py = float(r.get("pay") or 0)
        sum_send += s
        sum_disc += d
        sum_loss += l
        sum_pay += py
        body.append([
            r["date"][5:], m2(py), m2(s), pctv(s, py, 2),
            m2(d), pctv(d, py, 2), m2(l), pctv(l, py, 2),
        ])

    def color_fn(i, col, v):
        """损耗% 超红线标红；赠菜% 超 1% 标橙红"""
        if col == 7:
            try:
                return UP if float(str(v).rstrip("%")) > 0.35 else INK
            except ValueError:
                return INK
        if col == 3:
            try:
                return UP if float(str(v).rstrip("%")) > 1.0 else INK
            except ValueError:
                return INK
        return None

    p.table(headers, body, widths,
            aligns=["left", "right", "right", "right", "right", "right", "right", "right"],
            sum_row=["合计", m2(sum_pay), m2(sum_send), pctv(sum_send, sum_pay),
                     m2(sum_disc), pctv(sum_disc, sum_pay), m2(sum_loss),
                     pctv(sum_loss, sum_pay)],
            colors=color_fn)

    # ===== 近 7 日：营业额达成 =====
    p.section("近 7 日营业额达成（单位：元）")
    headers2 = ["日期", "当日目标", "实收", "达成率", "差额"]
    widths2 = [168, 196, 196, 172, 252]
    body2 = []
    sum_t, sum_p = 0, 0
    for r in last7:
        t = float(r.get("target") or 0)
        py = float(r.get("pay") or 0)
        sum_t += t
        sum_p += py
        rt = py / t * 100 if t else None
        body2.append([r["date"][5:], money(t) if t else "-", m2(py),
                      f"{rt:.1f}%" if rt is not None else "-",
                      f"{py - t:+,.2f}" if t else "-"])

    def color2(i, col, v):
        if col == 4:  # 差额：超了绿、差了红
            try:
                return DOWN if float(str(v).replace(",", "")) >= 0 else UP
            except ValueError:
                return None
        if col != 3:
            return None
        try:
            x = float(str(v).rstrip("%"))
        except ValueError:
            return None
        return DOWN if x >= 100 else (UP if x < 95 else "#C77C02")

    p.table(headers2, body2, widths2,
            aligns=["left", "right", "right", "right", "right"],
            sum_row=["合计", money(sum_t), m2(sum_p),
                     f"{sum_p / sum_t * 100:.1f}%" if sum_t else "-",
                     f"{sum_p - sum_t:+,.2f}" if sum_t else "-"],
            colors=color2)

    p.note("说明：营业额、目标达成均按实收口径；损耗取后台报损单；超时按 KDS 出品时长，"
           "堂食 >20 分、外卖 >15 分。",
           gap=6)
    p.note(f"生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M} · 数据来源 摩打后台", gap=0)
    return p.save(out_path)


if __name__ == "__main__":
    import json
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "data/report_2026-11-04.json"
    rows = json.load(open(src, encoding="utf-8"))
    print(build_page(rows, "output/_v4_test.png", "惠州店"))
