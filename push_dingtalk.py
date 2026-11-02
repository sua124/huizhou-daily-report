"""
钉钉推送脚本（部署包版）
- 通过群自定义机器人 Webhook 推送文字版日报摘要（图片附件 Webhook 不支持，见 README）
- 用法: python push_dingtalk.py [YYYY-MM-DD]
"""
import json, os, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import ding_push  # noqa: E402

cfg = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
w = cfg.get("dingtalk_webhook", {})
if not w.get("access_token"):
    print("config.json 未配置 dingtalk_webhook.access_token，跳过推送")
    sys.exit(0)
# 将 config 注入 webhook 模块
ding_push.WEBHOOK = f"https://oapi.dingtalk.com/robot/send?access_token={w['access_token']}"
ding_push.SECRET = w.get("secret", "")

store = cfg.get("store", {})
label = store.get("store_label", "门店")

td = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
data_path = os.path.join(BASE, "data", f"report_{td}.json")
if not os.path.exists(data_path):
    print(f"找不到数据文件 {data_path}，请先运行 daily_report.py {td}")
    sys.exit(1)

rows = json.load(open(data_path, encoding="utf-8"))
last = rows[-1]
prev = rows[-2] if len(rows) >= 2 else None


def pct(a, b):
    if not prev or not b:
        return ""
    d = (a - b) / b * 100
    return f"（{'+' if d >= 0 else ''}{d:.1f}%）" if prev else ""


md = f"## {label} 经营日报 {td}\n\n"
md += f"- **营业额：{last['revenue']:,.2f} 元** {pct(last['revenue'], prev['revenue'] if prev else 0)}\n"
md += f"- 实收营业额：{last['pay']:,.2f} 元 {pct(last['pay'], prev['pay'] if prev else 0)}\n"
md += f"- 赠菜金额：{last['send']:,.2f} 元（{last.get('send_qty', 0)} 份）\n"
md += f"- 折扣金额：{last['discount']:,.2f} 元（{last.get('discount_tables', 0)} 桌）\n"
md += f"- 订单数：{last['orders']:,}（堂食 {last.get('dine_in', 0)} / 外卖 {last.get('takeout', 0)}）\n"
md += f"- 客流：{last['people']} 人 ｜ 堂食人均 {last.get('people_avg', 0):.0f} 元 ｜ 堂食单均 {last.get('dinein_avg', 0):.0f} 元\n"
md += f"- 翻台率：{last.get('turnover', 0):.2f} 次（{last.get('table_open', 0)} 开台 ÷ {last.get('table_count', '-')} 桌）\n"
t = last.get("timeout", {})
if t.get("total"):
    md += f"- 出品超时（>20分钟，剔除指定品类）：{t['timeout']}/{t['total']}（{t['rate']}%），最长 {t['top'][0]['mins'] if t.get('top') else '-'} 分钟\n"

r = ding_push.send_markdown(f"{label}经营日报 {td}", md)
print("webhook 推送结果:", r)
