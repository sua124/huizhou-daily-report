"""
摩打 · 门店经营日报图片生成器（三张图）
  图 1 经营概览：核心指标 / 优惠结构 / 外卖平台 / 近14天趋势 / 近7天明细
  图 2 赠菜与折扣：赠菜明细 / 折扣明细 / 按桌台
  图 3 出品超时：统计卡 / 时长分布 / TOP10 / 高频超时菜品
输出: 竖版长图 PNG，适合钉钉群直接预览
"""
import os, json, datetime
from PIL import Image, ImageDraw, ImageFont

W = 1080
PAD = 48
BG = "#FFFFFF"
CARD = "#F7F8FA"
INK = "#1A1A1A"
INK2 = "#6B6B6B"
INK3 = "#9A9A9A"
ACCENT = "#1F4E79"
UP = "#C0392B"
DOWN = "#1E8449"
LINE = "#E5E7EB"
# 传菜时效红线（分钟）：下单 → 传菜完成
LATE_MIN = 20
# 实收金额高亮色
HILITE = "#C0392B"
HILITE_BG = "#FDEDEC"
HILITE_SUB = "#D98880"

FONT_CANDIDATES = [
    # Windows（本地）
    (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc"),
    (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simhei.ttf"),
    # Linux（云端 GitHub Actions 预装 fonts-noto-cjk）
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
     "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
     "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    # macOS
    ("/System/Library/Fonts/PingFang.ttc",
     "/System/Library/Fonts/PingFang.ttc"),
]

_HERE = os.path.dirname(os.path.abspath(__file__))


def _scan_system_cjk():
    """兜底：在 Linux 字体目录里找第一个中文字体"""
    for root in ("/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts")):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                low = f.lower()
                if not low.endswith((".ttf", ".otf", ".ttc")):
                    continue
                if any(k in f for k in ("CJK", "Noto", "WenQuanYi", "wqy",
                                        "Droid Sans Fallback")):
                    p = os.path.join(dirpath, f)
                    return p, p
    return None, None


def fonts():
    """返回 (粗体路径, 常规路径)。优先级：随仓库字体 > 系统字体 > 全盘扫描"""
    local_bold = os.path.join(_HERE, "fonts", "Bold.ttf")
    local_reg = os.path.join(_HERE, "fonts", "Regular.ttf")
    if os.path.exists(local_bold) and os.path.exists(local_reg):
        return local_bold, local_reg
    for bold, reg in FONT_CANDIDATES:
        if os.path.exists(bold) and os.path.exists(reg):
            return bold, reg
    return _scan_system_cjk()


BOLD_PATH, REG_PATH = fonts()


def F(size, bold=False):
    path = BOLD_PATH if bold else REG_PATH
    if not path or not os.path.exists(path):
        raise RuntimeError(
            "找不到中文字体。Windows 需 msyh.ttc；Linux 请先执行 "
            "`apt-get install -y fonts-noto-cjk`，或把字体放到 fonts/Bold.ttf 与 "
            "fonts/Regular.ttf。fonts() 返回: %r / %r" % (BOLD_PATH, REG_PATH))
    return ImageFont.truetype(path, size)


def money(v, unit=False):
    if v is None:
        return "-"
    if abs(v) >= 10000:
        return f"{v/10000:.2f}万" if unit else f"{v:,.0f}"
    return f"{v:,.0f}"


def pct(a, b):
    if not b:
        return "-"
    return f"{a/b*100:.2f}%"


class Canvas:
    """带通用组件的画布包装，三张图共用"""

    def __init__(self, last, store_label, page_no, page_title):
        self.last = last
        # 图 2 合并了赠菜折扣 + 停开售，内容较长，画布预留充足
        self.H = 8000
        self.img = Image.new("RGB", (W, self.H), BG)
        self.dr = ImageDraw.Draw(self.img)
        self.y = 226
        self._header(store_label, page_no, page_title)

    def _header(self, store_label, page_no, page_title):
        dr, last = self.dr, self.last
        dr.rectangle([0, 0, W, 190], fill=ACCENT)
        dr.text((PAD, 52), "摩打食堂", font=F(30, True), fill="#FFFFFF")
        dr.text((PAD, 100), f"{store_label} 经营日报", font=F(46, True), fill="#FFFFFF")
        dt = datetime.date.fromisoformat(last["date"])
        wk = "一二三四五六日"[dt.weekday()]
        dr.text((PAD, 158), f"{last['date']}  周{wk}", font=F(26), fill="#C7D8E8")
        dr.text((W - PAD, 158), f"{page_title}　{page_no}/3", font=F(24),
                fill="#C7D8E8", anchor="ra")

    def section(self, title, gap=0):
        self.y += gap
        self.dr.rectangle([PAD, self.y + 6, PAD + 6, self.y + 32], fill=ACCENT)
        self.dr.text((PAD + 20, self.y + 6), title, font=F(30, True), fill=INK)
        self.y += 58
        return self.y

    def kpi_row(self, cards, big=True):
        dr, y = self.dr, self.y
        gap = 16
        n = len(cards)
        cw = (W - PAD * 2 - gap * (n - 1)) // n
        ch = 150 if big else 130
        for i, card in enumerate(cards):
            label, value, sub, color = card[:4]
            hl = card[4] if len(card) > 4 else False
            extra = card[5] if len(card) > 5 else None
            x = PAD + i * (cw + gap)
            if hl:
                dr.rounded_rectangle([x, y, x + cw, y + ch], 12,
                                     fill=HILITE_BG, outline=HILITE, width=2)
                dr.text((x + 20, y + 22), label, font=F(22, True), fill=HILITE)
                dr.text((x + 20, y + 58), value, font=F(42 if big else 36, True), fill=HILITE)
                if sub:
                    dr.text((x + 20, y + ch - 36), sub, font=F(19), fill=HILITE_SUB)
                if extra:
                    dr.text((x + cw - 20, y + ch - 36), extra, font=F(19, True),
                            fill=HILITE, anchor="ra")
            else:
                dr.rounded_rectangle([x, y, x + cw, y + ch], 12, fill=CARD)
                dr.text((x + 20, y + 22), label, font=F(22), fill=INK2)
                dr.text((x + 20, y + 58), value, font=F(42 if big else 36, True), fill=color or INK)
                if sub:
                    dr.text((x + 20, y + ch - 36), sub, font=F(19), fill=INK3)
                if extra:
                    dr.text((x + cw - 20, y + ch - 36), extra, font=F(19, True),
                            fill=ACCENT, anchor="ra")
        self.y = y + ch + 18
        return self.y

    def note(self, text, color=None, size=18):
        self.dr.text((PAD, self.y), text, font=F(size), fill=color or INK3)
        self.y += 28

    def footer(self, lines):
        self.y += 18
        for i, ln in enumerate(lines):
            self.dr.text((PAD, self.y + i * 30), ln, font=F(19), fill=INK3)
        self.y += len(lines) * 30 + 20

    def save(self, path):
        out = self.img.crop((0, 0, W, min(self.y, self.H)))
        out.save(path, "PNG", quality=95)
        return path


def _delta(cur, base):
    if base is None or not base:
        return "环比 -", INK3
    ch = (cur - base) / base * 100
    arrow = "▲" if ch >= 0 else "▼"
    return f"环比 {arrow}{abs(ch):.1f}%", UP if ch >= 0 else DOWN


# ============ 图 1：经营概览 ============
def build_overview(rows, out_path, store_label="13店（正佳广场店）"):
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    c = Canvas(last, store_label, 1, "经营概览")
    dr = c.dr

    # ===== 核心指标 =====
    c.section("核心指标")
    s1, _ = _delta(last["revenue"], prev["revenue"] if prev else None)
    s2, _ = _delta(last["send"], prev["send"] if prev else None)
    s3, _ = _delta(last["discount"], prev["discount"] if prev else None)

    c.kpi_row([
        ("营业额（元）", money(last["revenue"]), s1, ACCENT, False,
         f"优惠 {money(last['favourable'])}"),
        ("赠菜金额（元）", money(last["send"]), s2, INK, False,
         f"{last.get('send_qty', 0)} 份"),
        ("折扣金额（元）", money(last["discount"]), s3, INK, False,
         f"{last.get('discount_count', 0)} 单 · {last.get('discount_qty', 0)} 份"),
    ])

    s4, _ = _delta(last["pay"], prev["pay"] if prev else None)
    c.kpi_row([
        ("实收营业额（元）", money(last["pay"]), s4, HILITE, True),
        ("堂食订单", f"{last.get('dine_in', 0):,}",
         f"占 {pct(last.get('dine_in', 0), last['orders'])}", INK),
        ("外卖订单", f"{last.get('takeout', 0):,}",
         f"占 {pct(last.get('takeout', 0), last['orders'])}", INK),
    ], big=False)

    td = last.get("takeout_detail") or {}
    if td and sum(td.values()) > 0:
        parts = " · ".join(f"{k} {v}" for k, v in td.items() if v)
        c.note(f"外卖渠道：{parts}")
        c.y -= 2

    tno = last.get("turnover") or 0
    p_tno = (prev.get("turnover") or 0) if prev else 0
    if p_tno:
        tch = (tno - p_tno) / p_tno * 100
        tsub = f"环比 {'▲' if tch >= 0 else '▼'}{abs(tch):.1f}%"
    else:
        tsub = f"开台 {last.get('table_open', 0)} 次"
    c.kpi_row([
        ("订单合计", f"{last['orders']:,}",
         f"环比 {last['orders']-(prev['orders'] if prev else 0):+d}", INK),
        ("客流（人）", f"{last['people']:,}", f"客单 {last['order_avg']:.0f} 元", INK),
        ("人均消费", f"{last['people_avg']:.0f} 元",
         f"堂食单均 {last.get('dinein_avg', 0):.0f} 元", INK),
        ("翻台率（次/桌）", f"{tno:.2f}", tsub, ACCENT),
    ], big=False)
    c.note(f"翻台率 = 开台次数 {last.get('table_open', 0)} ÷ 门店桌数 {last.get('table_count', 43)}")

    # 出品时间分析
    ts = last.get("timeout") or {}
    if ts.get("total"):
        c.section("出品时间分析", gap=14)
        # 三段横向对比条：≤10 / 11-20 / >20
        bk = ts.get("buckets") or {}
        fast = bk.get("≤10", 0)
        mid = bk.get("11-20", 0)
        slow = ts.get("timeout", 0)
        tot = fast + mid + slow or 1
        segs = [("10 分钟内", fast, "#5B8DB8"),
                ("11-20 分钟", mid, "#9FBFD9"),
                ("超 20 分钟", slow, "#C0392B")]
        bx, by, bw, bh = PAD, c.y + 6, W - PAD * 2, 40
        cx = bx
        for name, v, color in segs:
            seg = int(bw * v / tot)
            if seg > 0:
                dr.rectangle([cx, by, cx + seg, by + bh], fill=color)
                cx += seg
        ly = by + bh + 20
        colw = (W - PAD * 2) // 3
        for i, (name, v, color) in enumerate(segs):
            lx = PAD + i * colw
            dr.rounded_rectangle([lx, ly + 5, lx + 14, ly + 19], 3, fill=color)
            dr.text((lx + 24, ly), name, font=F(19), fill=INK2)
            dr.text((lx + 24, ly + 26), f"{v:,} 道", font=F(24, True), fill=INK)
            dr.text((lx + 24, ly + 60), f"占 {v/tot*100:.1f}%", font=F(17), fill=INK3)
        c.y = ly + 92

        # 关键结论
        good = (fast + mid) / tot * 100
        c.note(f"20 分钟内出餐 {good:.1f}%　|　中位 {ts.get('median', 0)} 分钟　|　"
               f"平均 {ts.get('avg', 0):.0f} 分钟　|　最长 {ts.get('max', 0)} 分钟",
               color=ACCENT, size=20)
        c.y += 6

    # 外卖平台
    channels = last.get("channels") or []
    if channels and any(ch.get("orders") for ch in channels):
        c.section("外卖平台", gap=10)
        head_y = c.y
        dr.rectangle([PAD, head_y, W - PAD, head_y + 46], fill=CARD)
        cxs = [PAD + 16, PAD + 160, PAD + 300, PAD + 560, PAD + 820]
        for label, cx in zip(["平台", "单数", "营收（应收）", "实收", "毛利率"], cxs):
            dr.text((cx, head_y + 12), label, font=F(20, True), fill=INK2)
        c.y = head_y + 46
        for ch in channels:
            dr.text((cxs[0], c.y + 14), ch["name"], font=F(23, True), fill=INK)
            dr.text((cxs[1], c.y + 14), f"{ch['orders']} 单", font=F(22), fill=INK)
            dr.text((cxs[2], c.y + 14), f"{ch['revenue']:,.0f}", font=F(22), fill=INK)
            dr.text((cxs[3], c.y + 14), f"{ch['pay']:,.0f}", font=F(22), fill=INK)
            gp = (ch["pay"] / ch["revenue"] * 100) if ch["revenue"] else 0
            dr.text((cxs[4], c.y + 14), f"{gp:.1f}%", font=F(22),
                    fill=ACCENT if gp >= 60 else (UP if gp < 50 else INK))
            dr.line([PAD, c.y + 48, W - PAD, c.y + 48], fill=LINE, width=1)
            c.y += 48
        t_ord = sum(ch["orders"] for ch in channels)
        t_rev = sum(ch["revenue"] for ch in channels)
        t_pay = sum(ch["pay"] for ch in channels)
        dr.text((cxs[0], c.y + 14), "外卖合计", font=F(23, True), fill=ACCENT)
        dr.text((cxs[1], c.y + 14), f"{t_ord} 单", font=F(22, True), fill=INK)
        dr.text((cxs[2], c.y + 14), f"{t_rev:,.0f}", font=F(22, True), fill=INK)
        dr.text((cxs[3], c.y + 14), f"{t_pay:,.0f}", font=F(22, True), fill=INK)
        dr.text((cxs[4], c.y + 14), f"{t_pay/t_rev*100:.1f}%" if t_rev else "-",
                font=F(22, True), fill=ACCENT)
        c.y += 58
        c.note("毛利率 = 实收 ÷ 应收，反映平台扣费与优惠后的实际留存", size=18)
        c.y += 6

    # 近14天趋势
    c.section("近 14 天营业额趋势", gap=10)
    chart_x, chart_y = PAD + 8, c.y + 20
    chart_w, chart_h = W - PAD * 2 - 16, 240
    recent = rows[-14:]
    mx = max(r["revenue"] for r in recent) or 1
    mn = min(r["revenue"] for r in recent)
    base_line = chart_y + chart_h
    for g in range(4):
        gy = chart_y + chart_h - chart_h * g / 3
        dr.line([chart_x, gy, chart_x + chart_w, gy], fill=LINE, width=1)
        dr.text((chart_x - 10, gy - 12), f"{mx*g/3/10000:.0f}万",
                font=F(18), fill=INK3, anchor="ra")
    n = len(recent)
    bwid = chart_w / n
    for i, r in enumerate(recent):
        h = chart_h * (r["revenue"] - mn * 0.72) / (mx - mn * 0.72)
        x = chart_x + i * bwid + bwid * 0.18
        w = bwid * 0.64
        is_last = i == n - 1
        color = ACCENT if is_last else "#A9C4DC"
        dr.rounded_rectangle([x, base_line - h, x + w, base_line], 3, fill=color)
        if i % 2 == 0 or is_last:
            lbl = r["date"][5:].replace("-", "/")
            dr.text((x + w / 2, base_line + 10), lbl, font=F(17),
                    fill=INK if is_last else INK3, anchor="ma")
    c.y = base_line + 46

    # 近7天明细（实收紧随营业额）
    c.section("近 7 天明细", gap=10)
    cols = [("日期", 0), ("营业额", 165), ("实收营业额", 285), ("赠菜", 420),
            ("折扣", 530), ("订单", 645), ("翻台", 760)]
    dr.rectangle([PAD, c.y, W - PAD, c.y + 48], fill=CARD)
    for name, off in cols:
        dr.text((PAD + off + 12, c.y + 13), name, font=F(20, True), fill=INK2)
    c.y += 48
    for r in rows[-7:]:
        dt2 = datetime.date.fromisoformat(r["date"])
        dr.text((PAD + 12, c.y + 12), f"{r['date'][5:]}  周{'一二三四五六日'[dt2.weekday()]}",
                font=F(20), fill=INK2)
        vals = [money(r["revenue"]), money(r["pay"]), money(r["send"]),
                money(r["discount"]), f"{r['orders']:,}", f"{r.get('turnover', 0):.2f}"]
        offs = [165, 285, 420, 530, 645, 760]
        for i, (v, o) in enumerate(zip(vals, offs)):
            # 实收列用高亮红，与核心指标呼应
            dr.text((PAD + o + 12, c.y + 12), v, font=F(21, True if i == 1 else False),
                    fill=HILITE if i == 1 else (ACCENT if i == 5 else INK))
        dr.line([PAD, c.y + 46, W - PAD, c.y + 46], fill=LINE, width=1)
        c.y += 46

    c.footer([
        "数据源：摩打后台 · 数据中心　|　口径：营业额=应收，实收=扣除优惠后",
        f"翻台率按门店实际桌数 {last.get('table_count', 43)} 张计算",
        f"生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M}",
    ])
    return c.save(out_path)


# ============ 图 2：赠菜与折扣 ============
def build_discount(rows, out_path, store_label="13店（正佳广场店）"):
    last = rows[-1]
    c = Canvas(last, store_label, 2, "赠菜·折扣·停开售")
    dr = c.dr

    sd = last.get("send_detail") or {}
    dd = last.get("discount_detail") or {}

    # 概览两卡
    c.section("当日汇总")
    fav = last["favourable"]
    c.kpi_row([
        ("赠菜金额（元）", f"{sd.get('total', 0):,.2f}",
         f"{sd.get('count', 0)} 条 · {sd.get('qty', 0)} 份", INK),
        ("折扣金额（元）", f"{dd.get('total', 0):,.2f}",
         f"{dd.get('count', 0)} 单 · {dd.get('qty', 0)} 份", INK),
        ("合计占营业额", pct(sd.get("total", 0) + dd.get("total", 0), last["revenue"]),
         f"共 {sd.get('total', 0) + dd.get('total', 0):,.2f} 元", ACCENT),
    ], big=False)

    # ---- 赠菜明细 ----
    sd_items = sd.get("items") or []
    if sd_items:
        c.section("赠菜明细", gap=12)
        c.note(f"共 {sd.get('count', 0)} 条 · 合计 {sd.get('total', 0):,.2f} 元", size=20)
        # 表头
        dr.rectangle([PAD, c.y, W - PAD, c.y + 42], fill=CARD)
        sx = [PAD + 14, PAD + 120, PAD + 330, PAD + 560, PAD + 810]
        for lbl, cx in zip(["桌号", "菜品", "数量", "赠菜原因", "金额"], sx):
            anchor = "ra" if lbl == "金额" else "la"
            px = W - PAD - 14 if lbl == "金额" else cx
            dr.text((px, c.y + 11), lbl, font=F(19, True), fill=INK2, anchor=anchor)
        c.y += 42
        for it in sd_items[:20]:
            tb = it.get("table") or "-"
            dr.rounded_rectangle([PAD + 10, c.y + 7, PAD + 104, c.y + 37], 6, fill="#EAF0F6")
            dr.text((PAD + 57, c.y + 22), tb if len(tb) <= 7 else tb[:6] + "…",
                    font=F(17, True), fill=ACCENT, anchor="mm")
            nm = it["name"]
            if len(nm) > 14:
                nm = nm[:13] + "…"
            dr.text((sx[1], c.y + 11), nm, font=F(19), fill=INK)
            dr.text((sx[2], c.y + 11), f"{it.get('num', 1)}{it.get('unit', '')}",
                    font=F(18), fill=INK2)
            rsn = it["reason"] or it["remark"] or "未标注"
            if len(rsn) > 16:
                rsn = rsn[:15] + "…"
            dr.text((sx[3], c.y + 11), rsn, font=F(18), fill=INK2)
            dr.text((W - PAD - 14, c.y + 10), f"{it['amount']:,.2f}", font=F(21, True),
                    fill=ACCENT, anchor="ra")
            # 副行：时间 + 操作人
            dr.text((sx[1], c.y + 38),
                    f"{it['time']}　{it['admin']}", font=F(16), fill=INK3)
            dr.line([PAD, c.y + 62, W - PAD, c.y + 62], fill=LINE, width=1)
            c.y += 64
        c.y += 4

    # ---- 折扣明细（按折扣率归类）----
    by_disc = dd.get("by_discount") or []
    dd_by_reason = dd.get("by_reason") or {}
    if by_disc:
        c.section("折扣明细 · 按折扣率", gap=12)
        c.note(f"共 {dd.get('count', 0)} 单 · 合计 {dd.get('total', 0):,.2f} 元", size=20)
        dr.rectangle([PAD, c.y, W - PAD, c.y + 42], fill=CARD)
        dx = [PAD + 14, PAD + 120, PAD + 290, PAD + 420, PAD + 540]
        for lbl, cx in zip(["折扣率", "折扣额", "占原价", "桌数", "主要折扣原因"], dx):
            dr.text((cx, c.y + 11), lbl, font=F(19, True), fill=INK2)
        c.y += 42
        for b in by_disc:
            d = b["discount"]
            dcol = UP if d <= 69 else (INK if d >= 90 else ACCENT)
            dr.rounded_rectangle([PAD + 10, c.y + 8, PAD + 104, c.y + 38], 6,
                                 fill="#EAF0F6")
            dr.text((PAD + 57, c.y + 23), b["label"], font=F(18, True),
                    fill=dcol, anchor="mm")
            dr.text((dx[1], c.y + 11), f"{b['amt']:,.0f}", font=F(21, True), fill=INK)
            dr.text((dx[2], c.y + 13), f"{b['rate']:.1f}%", font=F(19), fill=INK2)
            dr.text((dx[3], c.y + 13), f"{b['tables']} 张", font=F(19), fill=INK3)
            rs = "、".join(b["reasons"][:3]) if b["reasons"] else "未标注"
            if len(rs) > 12:
                rs = rs[:11] + "…"
            dr.text((dx[4], c.y + 13), rs, font=F(17), fill=INK2)
            dr.line([PAD, c.y + 46, W - PAD, c.y + 46], fill=LINE, width=1)
            c.y += 48
        c.y += 4

        # 折扣原因细分（原按类型聚合）
        if dd_by_reason:
            c.section("折扣原因细分", gap=10)
            col_w = (W - PAD * 2) // 2
            reasons = list(dd_by_reason.items())
            for idx, (reason, agg) in enumerate(reasons):
                col, row_i = idx % 2, idx // 2
                rx = PAD + col * col_w
                ry = c.y + row_i * 40
                txt = reason if len(reason) <= 10 else reason[:9] + "…"
                dr.text((rx, ry), txt, font=F(20), fill=INK2)
                dr.text((rx + col_w - 120, ry), f"{agg['amt']:,.0f} 元",
                        font=F(20, True), fill=INK, anchor="ra")
                dr.text((rx + col_w - 10, ry), f"{agg['cnt']} 条", font=F(18), fill=INK3,
                        anchor="ra")
            c.y += ((len(reasons) + 1) // 2) * 40 + 16

    # ---- 折扣按桌台 ----
    by_table = dd.get("by_table") or []
    if by_table:
        c.section("折扣明细 · 按桌台", gap=12)
        c.note(f"有折扣的桌台共 {len(by_table)} 张 · 按折扣率从高到低排序", size=19)
        dr.rectangle([PAD, c.y, W - PAD, c.y + 42], fill=CARD)
        tx = [PAD + 14, PAD + 140, PAD + 480]
        for lbl, cx in zip(["桌号", "折扣率", "折扣原因"], tx):
            dr.text((cx, c.y + 11), lbl, font=F(19, True), fill=INK2)
        c.y += 42
        for t in by_table:
            tb = t["table"]
            dr.rounded_rectangle([PAD + 10, c.y + 8, PAD + 110, c.y + 38], 6, fill="#EAF0F6")
            dr.text((PAD + 60, c.y + 23), tb if len(tb) <= 7 else tb[:6] + "…",
                    font=F(17, True), fill=ACCENT, anchor="mm")
            # 折扣率：后台 discount 字段为折扣力度（90=9折 / 80=8折 / 69=6.9折）
            ds = t.get("discounts") or []
            if len(ds) == 1:
                rt = f"{ds[0]/10:g} 折"
                ccol = UP if ds[0] <= 69 else (INK if ds[0] >= 90 else ACCENT)
            elif ds:
                rt = "/".join(f"{d/10:g}" for d in sorted(ds)) + " 折"
                ccol = ACCENT
            else:
                rt = "-"
                ccol = INK3
            dr.text((tx[1], c.y + 11), rt, font=F(22, True), fill=ccol)
            rs = "、".join(t["reasons"]) if t["reasons"] else "未标注"
            if len(rs) > 18:
                rs = rs[:17] + "…"
            dr.text((tx[2], c.y + 13), rs, font=F(18), fill=INK2)
            dr.line([PAD, c.y + 46, W - PAD, c.y + 46], fill=LINE, width=1)
            c.y += 48
        c.note("折扣率取自点单时的折扣设置（9 折 / 8 折 / 6.9 折）；一桌多档时并列显示", size=17)

    # 菜品停/开售记录（与赠菜折扣合并为同一张图）
    sale_section(c, dr, last.get("sale") or {})

    c.footer([
        "数据源：摩打后台 · 数据中心　|　赠菜、折扣均为门店自担优惠",
        "停售口径：操作记录时间；「当日估清」多为系统次日自动恢复",
        f"生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M}",
    ])
    return c.save(out_path)


# ============ 菜品停/开售记录（作为图 2 的一段）============
def sale_section(c, dr, sd):
    """把「菜品停/开售记录」追加到当前画布末尾"""
    items = sd.get("items") or []
    c.section("菜品停/开售记录", gap=16)
    if not items:
        c.note("当日无停售 / 估清操作记录", color=ACCENT, size=22)
        c.y += 6
        return c
    avg = sd.get("avg_mins")
    c.kpi_row([
        ("停售操作", f"{sd.get('total', 0)}",
         f"涉及 {sd.get('dishes', 0)} 个菜品", INK),
        ("已恢复开售", f"{sd.get('reopened', 0)}",
         f"平均停售 {avg} 分钟" if avg is not None else "—", ACCENT),
        ("尚未恢复", f"{sd.get('closed', 0)}", "需人工确认是否漏恢复",
         UP if sd.get("closed") else INK),
    ], big=False)

    bf = {k: v for k, v in (sd.get("by_field") or {}).items() if v}
    if bf:
        parts = " · ".join(f"{k} {v} 次" for k, v in bf.items())
        c.note(f"操作类型：{parts}", size=19)
        c.y += 4

    # 明细表：时间 / 菜品 / 类型 / 停售人 / 恢复
    c.section("停售明细", gap=10)
    dr.rectangle([PAD, c.y, W - PAD, c.y + 44], fill=CARD)
    cx_time, cx_name = PAD + 14, PAD + 110
    cx_type, cx_admin = PAD + 570, PAD + 720
    for lbl, cx in zip(["停售时间", "菜品", "类型", "停售人"],
                       [cx_time, cx_name, cx_type, cx_admin]):
        dr.text((cx, c.y + 12), lbl, font=F(19, True), fill=INK2)
    dr.text((W - PAD - 14, c.y + 12), "恢复开售", font=F(19, True),
            fill=INK2, anchor="ra")
    c.y += 44

    for it in items[:24]:
        nm = it["name"]
        if len(nm) > 20:
            nm = nm[:19] + "…"
        dr.text((cx_time, c.y + 12), it["close_time"], font=F(20, True), fill=UP)
        dr.text((cx_name, c.y + 12), nm, font=F(19), fill=INK)
        dr.text((cx_type, c.y + 13), it["field_name"], font=F(18), fill=INK2)
        adm = it.get("close_admin") or "-"
        if len(adm) > 8:
            adm = adm[:7] + "…"
        dr.text((cx_admin, c.y + 13), adm, font=F(18), fill=INK2)
        if it["reopened"]:
            rt = f"{it['open_time']} {it['open_admin']}".strip()
            col = ACCENT
        else:
            rt = "未恢复"
            col = UP
        if len(rt) > 14:
            rt = rt[:13] + "…"
        dr.text((W - PAD - 14, c.y + 12), rt, font=F(19, True), fill=col, anchor="ra")
        # 副行：停售时长
        sub = ""
        if it.get("mins") is not None:
            m = it["mins"]
            sub = f"停售 {m//60} 小时 {m%60} 分" if m >= 60 else f"停售 {m} 分钟"
        dr.text((cx_name, c.y + 38), sub, font=F(16), fill=INK3)
        dr.line([PAD, c.y + 62, W - PAD, c.y + 62], fill=LINE, width=1)
        c.y += 62

    if len(items) > 24:
        c.note(f"仅展示前 24 条，其余 {len(items) - 24} 条见后台", size=17)
    c.y += 6
    return c


# ============ 图 4：出品超时 ============
def build_timeout(rows, out_path, store_label="13店（正佳广场店）"):
    last = rows[-1]
    c = Canvas(last, store_label, 3, "出品超时")
    dr = c.dr
    ts = last.get("timeout") or {}

    if not ts.get("total"):
        c.section("出品超时")
        c.note("当日无出品记录", size=22)
        c.footer([
            "数据源：摩打后台 · 出品统计",
            f"生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M}",
        ])
        return c.save(out_path)

    thr_dine = ts.get("thr_dine", 20)
    thr_take = ts.get("thr_take", 15)
    dn = ts.get("dine") or {}
    tk = ts.get("take") or {}

    c.section(f"出品超时（堂食 >{thr_dine} 分 / 外卖 >{thr_take} 分）")
    c.kpi_row([
        ("出品总道数", f"{ts['total']:,}",
         f"堂食 {dn.get('total', 0)} · 外卖 {tk.get('total', 0)}", INK),
        ("超时道数", f"{ts['timeout']:,}",
         f"堂食 {dn.get('timeout', 0)} 道 · 外卖 {tk.get('timeout', 0)} 道",
         UP if ts["timeout"] else INK),
        ("超时率", f"{ts['rate']:.2f}%",
         f"堂食 {dn.get('rate', 0):.2f}% · 外卖 {tk.get('rate', 0):.2f}%",
         UP if ts["rate"] > 3 else ACCENT),
        ("平均出品时长", f"{ts['avg']:.1f} 分",
         f"中位 {ts.get('median', 0):.1f} 分 · 最长 {ts.get('max', 0)} 分", INK),
    ], big=False)

    # 堂食 / 外卖 出品效率对比（KDS 无订单号，按渠道拆开看更有意义）
    if dn.get("total") or tk.get("total"):
        c.section("堂食 / 外卖 出品效率", gap=8)
        cw = W - PAD * 2
        x_dine, x_take = PAD + cw * 0.56, PAD + cw * 0.82
        dr.text((x_dine, c.y), "堂食", font=F(18, True), fill=INK3, anchor="ra")
        dr.text((x_take, c.y), "外卖", font=F(18, True), fill=INK3, anchor="ra")
        c.y += 32
        cmps = [
            ("出品道数", f"{dn.get('total', 0)}", f"{tk.get('total', 0)}"),
            ("平均出品", f"{dn.get('avg', 0):.1f} 分", f"{tk.get('avg', 0):.1f} 分"),
            ("中位出品", f"{dn.get('median', 0):.1f} 分", f"{tk.get('median', 0):.1f} 分"),
            ("最长出品", f"{dn.get('max', 0)} 分", f"{tk.get('max', 0)} 分"),
            ("超时道数", f"{dn.get('timeout', 0)}", f"{tk.get('timeout', 0)}"),
            ("超时率", f"{dn.get('rate', 0):.2f}%", f"{tk.get('rate', 0):.2f}%"),
        ]
        for label, a, b in cmps:
            dr.text((PAD, c.y + 5), label, font=F(19), fill=INK2)
            dr.text((x_dine, c.y), a, font=F(20, True), fill=INK, anchor="ra")
            dr.text((x_take, c.y), b, font=F(20, True), fill=INK, anchor="ra")
            dr.line([PAD, c.y + 34, W - PAD, c.y + 34], fill=LINE, width=1)
            c.y += 38
        c.y += 12

    # 时长分布
    bk = ts.get("buckets") or {}
    segs = [("≤5 分", bk.get("≤5", 0), "#9FBFD9"),
            ("6-10 分", bk.get("6-10", 0), "#5B8DB8"),
            ("11-15 分", bk.get("11-15", 0), "#7FA8C9"),
            ("16-20 分", bk.get("16-20", 0), "#E8A87C"),
            (">20 分", bk.get(">20", 0), "#C0392B")]
    tot_all = sum(v for _, v, _ in segs) or 1
    bx, by, bw, bh = PAD, c.y + 6, W - PAD * 2, 40
    dr.rounded_rectangle([bx, by, bx + bw, by + bh], 6, fill=CARD)
    cx = bx
    for name, v, color in segs:
        seg = int(bw * v / tot_all)
        if seg > 0:
            dr.rectangle([cx, by, cx + seg, by + bh], fill=color)
            cx += seg
    ly = by + bh + 18
    for i, (name, v, color) in enumerate(segs):
        lx = PAD + i * ((W - PAD * 2) // 5)
        dr.rounded_rectangle([lx, ly + 5, lx + 13, ly + 18], 2, fill=color)
        dr.text((lx + 21, ly), f"{name}", font=F(17), fill=INK3)
        dr.text((lx + 21, ly + 22), f"{v}", font=F(20, True), fill=INK)
        dr.text((lx + 21, ly + 48), pct(v, tot_all), font=F(16), fill=INK3)
    c.y = ly + 76

    # TOP10
    tops = ts.get("top") or []
    if tops:
        c.section("超时最久 TOP 10", gap=10)
        c.note("KDS 出品记录不含订单号，按菜品 + 出品时段定位", size=18)
        for i, t in enumerate(tops[:10]):
            nm = t["name"]
            if len(nm) > 18:
                nm = nm[:17] + "…"
            mins = t.get("exact", t["mins"])
            over_by = mins - (t.get("limit") or thr_dine)
            badge_c = "#C0392B" if over_by >= 10 else ("#E8A87C" if over_by >= 5 else "#9FBFD9")
            dr.ellipse([PAD + 4, c.y + 3, PAD + 30, c.y + 29], fill=badge_c)
            dr.text((PAD + 17, c.y + 16), str(i + 1), font=F(16, True),
                    fill="#FFFFFF", anchor="mm")
            dr.text((PAD + 42, c.y + 4), nm, font=F(21), fill=INK)
            dr.text((W - PAD - 8, c.y + 4), f"{mins:.1f} 分", font=F(22, True),
                    fill=UP, anchor="ra")
            hr = t.get("hour")
            when = f"{hr:02d}:00 时段" if isinstance(hr, (int, float)) else "时段未知"
            dr.text((PAD + 42, c.y + 32),
                    f"{t.get('kind_name', '堂食')} · {when} · 红线 {t.get('limit', thr_dine)} 分",
                    font=F(17), fill=INK3)
            dr.line([PAD, c.y + 58, W - PAD, c.y + 58], fill=LINE, width=1)
            c.y += 60
        c.y += 8

    # 高频超时菜品
    bn = ts.get("by_name") or []
    if bn:
        c.section("高频超时菜品", gap=10)
        col_w = (W - PAD * 2) // 2
        for idx, b in enumerate(bn[:6]):
            col, row_i = idx % 2, idx // 2
            rx, ry = PAD + col * col_w, c.y + row_i * 40
            nm = b["name"]
            if len(nm) > 10:
                nm = nm[:9] + "…"
            dr.text((rx, ry), nm, font=F(19), fill=INK)
            dr.text((rx + col_w - 210, ry), f"{b['cnt']} 道", font=F(18),
                    fill=INK3, anchor="ra")
            dr.text((rx + col_w - 130, ry), f"均{b['avg']:.1f}", font=F(18),
                    fill=INK2, anchor="ra")
            dr.text((rx + col_w - 10, ry), f"最长 {b['max']} 分",
                    font=F(18, True), fill=UP, anchor="ra")
        c.y += ((len(bn[:6]) + 1) // 2) * 40 + 16

    # 出品时段分布（全部出品道数，超时部分标红）
    peak = ts.get("peak") or []
    over_map = dict(ts.get("peak_over") or [])
    if peak:
        c.section("出品时段分布", gap=10)
        c.note("柱高 = 该时段出品道数，红色段为其中超时的道数", size=18)
        pmax = max(v for _, v in peak) or 1
        base = c.y + 20
        slot = (W - PAD * 2) / max(len(peak), 1)
        bar_w = min(slot * 0.62, 46)
        for i, (h, v) in enumerate(peak):
            cx = PAD + i * slot + slot / 2
            hbar = max(int(130 * v / pmax), 3)
            top = base + 150 - hbar
            dr.rounded_rectangle([cx - bar_w / 2, top, cx + bar_w / 2, base + 150],
                                 3, fill="#A9C4DC")
            ov = over_map.get(h, 0)
            if ov:
                oh = max(int(130 * ov / pmax), 6)
                dr.rounded_rectangle([cx - bar_w / 2, base + 150 - oh,
                                      cx + bar_w / 2, base + 150], 3, fill=UP)
            dr.text((cx, top - 22), str(v), font=F(16, True), fill=INK, anchor="ma")
            dr.text((cx, base + 158), f"{h}时", font=F(15), fill=INK3, anchor="ma")
        c.y = base + 196

    # 传菜时效（老板指定跟踪项：出品慢 2 道但传菜慢 30+ 道，慢在传菜环节）
    dv = last.get("delivery") or {}
    if dv.get("total"):
        c.section("传菜时效（下单 → 传菜完成，>20 分为慢）", gap=18)
        c.kpi_row([
            ("传菜道数·堂食", f"{dv['total']:,}",
             f"中位 {dv.get('median', 0)} 分 · 最长 {dv.get('max', 0)} 分", INK),
            ("慢传道数", f"{dv.get('late', 0):,}",
             f"超 {LATE_MIN} 分的单据", UP if dv.get("late") else INK),
            ("慢传率", f"{dv.get('rate', 0):.2f}%",
             f"对照出品超时率 {ts.get('rate', 0):.2f}%", ACCENT),
            ("平均传菜时长", f"{dv.get('avg', 0):.1f} 分",
             "含厨房出品 + 传菜全程", INK),
        ], big=False)

        tops = dv.get("top") or []
        if tops:
            c.section("慢传 TOP（含单号，可直接查单）", gap=10)
            for i, t in enumerate(tops[:8]):
                nm = t["name"]
                if len(nm) > 16:
                    nm = nm[:15] + "…"
                over_by = t["mins"] - LATE_MIN
                badge_c = "#C0392B" if over_by >= 8 else ("#E8A87C" if over_by >= 4 else "#9FBFD9")
                dr.ellipse([PAD + 4, c.y + 3, PAD + 30, c.y + 29], fill=badge_c)
                dr.text((PAD + 17, c.y + 16), str(i + 1), font=F(16, True),
                        fill="#FFFFFF", anchor="mm")
                dr.text((PAD + 42, c.y + 2), nm, font=F(21), fill=INK)
                dr.text((W - PAD - 8, c.y + 2), f"{t['mins']} 分",
                        font=F(22, True), fill=UP, anchor="ra")
                dr.text((PAD + 42, c.y + 32),
                        f"单 {t['order_id']} · {t['created']} 下单 → {t['delivered']} 传菜",
                        font=F(17), fill=INK3)
                dr.line([PAD, c.y + 58, W - PAD, c.y + 58], fill=LINE, width=1)
                c.y += 60
            c.y += 6

    # 口径
    c.footer([
        f"口径：下单 → 菜品出品完成（KDS 出品记录），堂食超 {thr_dine} 分、"
        f"外卖超 {thr_take} 分计为超时；按菜品道数计数",
        (f"已剔除 {' / '.join(ts.get('excluded_names') or [])} 共 {ts.get('excluded', 0)} 道"
         f"（制作工艺特殊，计入会失真）") if ts.get("excluded") else "",
        "传菜时效口径：下单 → 传菜完成（仅堂食），超 20 分计为慢传，慢传=出品完成后传菜/取餐环节拖慢",
        "数据源：摩打后台 · 出品统计（kdsStatis）/ 传菜统计（deliverStatistics）",
        f"生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M}",
    ])
    return c.save(out_path)


def build_all(data_path, out_dir, store_label="13店（正佳广场店）"):
    """生成三张图（赠菜折扣与菜品停开售合并为第 2 张），返回路径列表"""
    rows = json.load(open(data_path, encoding="utf-8"))
    date = rows[-1]["date"]
    os.makedirs(out_dir, exist_ok=True)
    # 先清掉该日期遗留的旧图：早期版本图 2 叫「赠菜与折扣」，改名后会与
    # 新图并存，推送时会被当成两张一起发出去。
    _pre = f"report_{date}_"
    for _old in os.listdir(out_dir):
        if _old.startswith(_pre) and _old.lower().endswith(".png"):
            try:
                os.remove(os.path.join(out_dir, _old))
            except OSError:
                pass
    paths = []
    # 图 1 用 4 店式单页版式（含目标达成/损耗/近 7 日两张表）。
    # 延迟导入：render_v4 反过来要 import 本模块的字体与配色，避免循环引用。
    from render_v4 import build_page
    for fn, name in [(build_page, "01_经营概览"),
                     (build_discount, "02_赠菜折扣与停开售"),
                     (build_timeout, "03_出品超时")]:
        p = os.path.join(out_dir, f"report_{date}_{name}.png")
        fn(rows, p, store_label)
        paths.append(p)
    return paths


# 兼容旧调用
def build(data_path, out_path, store_label="13店（正佳广场店）"):
    return build_overview(json.load(open(data_path, encoding="utf-8")), out_path, store_label)


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(base, "data", "zhengjia_2026-10-30.json")
    for p in build_all(src, os.path.join(base, "output")):
        print("saved:", p, os.path.getsize(p), "bytes")
