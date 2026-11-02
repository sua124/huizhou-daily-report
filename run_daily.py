"""
惠州店日报一键流水线：拉数据 -> 生成三张图 -> 推送到钉钉群

用法: python run_daily.py [YYYY-MM-DD]   (不传日期默认今天；计划任务里不传参)
日志: daily.log
"""
import datetime
import json
import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
LOG = os.path.join(BASE, "daily.log")
SENT = os.path.join(BASE, "data", "sent.json")

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STORE_LABEL = CFG.get("store", {}).get("store_label", "门店")


def log(msg):
    line = "[{}] {}".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line)
    except Exception:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_sent():
    try:
        with open(SENT, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _mark_sent(d):
    s = _load_sent()
    s.add(d)
    os.makedirs(os.path.dirname(SENT), exist_ok=True)
    with open(SENT, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=1)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        return run_one(arg)

    now = datetime.datetime.now()
    today = now.date()

    # 22:00 前后的正常触发，直接发当天
    if now.hour >= 20:
        return run_one(today.isoformat())

    # 白天开机时被「错过任务补跑」唤醒：只补历史，不发今天（今天数据还没结束）
    if not os.path.exists(SENT):
        y = (today - datetime.timedelta(days=1)).isoformat()
        log("没有推送记录（首次补跑）：改发昨日 {}，今日等 22:00 再发".format(y))
        return run_one(y)

    sent = _load_sent()
    targets = [(today - datetime.timedelta(days=k)).isoformat() for k in range(3, 0, -1)]
    targets = [d for d in targets if d not in sent]
    if not targets:
        log("开机补跑：最近 3 天日报都已推送，无需补发")
        return 0

    log("开机补跑：发现漏发 {}".format("、".join(targets)))
    rc = 0
    for d in targets:
        rc |= run_one(d)
    return rc


def run_one(td):
    log("=" * 60)
    log("开始生成 {}（{}）经营日报".format(STORE_LABEL, td))

    from daily_report import pull
    from render_report import build_all
    import push_images

    data_path, rows = pull(td)
    last = rows[-1]
    log(
        "数据就绪：营业额 {:,.2f} / 实收 {:,.2f} / 订单 {} / 客流 {}".format(
            last["revenue"], last["pay"], last["orders"], last["people"]
        )
    )

    pngs = build_all(data_path, os.path.join(BASE, "output"), STORE_LABEL)
    for p in pngs:
        log("生成图片：{}".format(p))

    ok, total = push_images.push(td)
    log("推送结果：{}/{}".format(ok, total))
    # 全部成功才记账，避免漏发被误判为已发
    if total and ok == total:
        _mark_sent(td)
    return 0 if ok == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("运行异常：\n" + traceback.format_exc())
        sys.exit(1)
