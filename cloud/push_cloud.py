"""
云端推送日报图片到钉钉群（不依赖本机登录态，GitHub Actions / 服务器通用）

用法:
    python cloud/push_cloud.py [YYYY-MM-DD] [--dry-run]

环境变量:
    DINGTALK_WEBHOOK_TOKEN    群自定义机器人的 access_token（必填）
    DINGTALK_WEBHOOK_SECRET   群机器人的加签密钥（选填，推荐配上更安全）
    IMAGE_BASE_URL            图片公网前缀，留空则按 GitHub 仓库自动拼
    IMAGE_SHA                 图片所在的 commit sha（留空用 GITHUB_SHA）

说明：
- 钉钉自定义机器人不支持直接上传本地图片，只能发「公网图片链接」，
  所以图片会先随代码提交到仓库，再用 jsDelivr CDN 的公网地址发出。
- 艾特某人需要手机号：写进 config.json 的 mentions_phones。
"""
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "output")

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
LABEL = CFG.get("store", {}).get("store_label", "门店")
MENTIONS = CFG.get("mentions") or {}
PHONES = CFG.get("mentions_phones") or {}

TOKEN = os.environ.get("DINGTALK_WEBHOOK_TOKEN", "").strip()
SECRET = os.environ.get("DINGTALK_WEBHOOK_SECRET", "").strip()


def image_base_url():
    """图片公网地址前缀"""
    env = os.environ.get("IMAGE_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    sha = (os.environ.get("IMAGE_SHA") or os.environ.get("GITHUB_SHA")
           or os.environ.get("GITHUB_REF_NAME") or "main").strip()
    if repo:
        return f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/reports"
    return ""


def public_url(basename, base):
    return f"{base}/{urllib.parse.quote(basename)}"


def wait_reachable(url, tries=24, wait=10, verbose=True):
    """jsDelivr 首次拉取新文件需要一点时间，这里轮询直到可访问

    tries*wait = 240 秒。实测新 commit 一般 10~60 秒可拉，偶尔更久；
    以前 150 秒就放弃，会白白丢掉一张图，所以放宽到 4 分钟。
    """
    for i in range(tries):
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    if verbose and i:
                        print(f"  图片已可访问（等待 {i * wait} 秒）")
                    return True
        except Exception:
            pass
        time.sleep(wait)
    return False


def _sign(secret):
    ts = str(round(time.time() * 1000))
    to_sign = f"{ts}\n{secret}".encode()
    dig = hmac.new(secret.encode(), to_sign, hashlib.sha256).digest()
    return ts, urllib.parse.quote_plus(base64.b64encode(dig))


def send_markdown(title, text, at_mobiles=None, at_user_ids=None):
    url = f"https://oapi.dingtalk.com/robot/send?access_token={TOKEN}"
    if SECRET:
        ts, sign = _sign(SECRET)
        url += f"&timestamp={ts}&sign={sign}"
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    at = {"isAtAll": False}
    if at_mobiles:
        at["atMobiles"] = at_mobiles
    if at_user_ids:
        at["atUserIds"] = at_user_ids
    body["at"] = at

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    res = {}
    # 钉钉偶发超时/限流（130101=发送过快），重发一次基本就能过；
    # 这里失败会导致某张图缺失，进而整次运行判失败，值得重试。
    for i in range(3):
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json;charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            res = {"errcode": -1, "errmsg": f"{type(e).__name__}: {e}"}
        if res.get("errcode") == 0:
            return res
        if res.get("errcode") in (-1, 130101) and i < 2:
            wait = 3 * (i + 1)
            print(f"  发送失败（{res.get('errmsg') or res.get('errcode')}），{wait}s 后重试")
            time.sleep(wait)
            continue
        return res
    return res


def push(date=None, dry_run=False):
    if not TOKEN and not dry_run:
        print("未设置环境变量 DINGTALK_WEBHOOK_TOKEN，跳过推送")
        return 0, 0

    td = date or datetime.date.today().isoformat()
    pngs = sorted(p for p in os.listdir(OUT)
                  if p.startswith(f"report_{td}_") and p.lower().endswith(".png"))
    if not pngs:
        print(f"output 目录找不到 {td} 的日报图片")
        return 0, 0

    base = image_base_url()
    if not base:
        print("无法确定图片公网前缀，请设置 IMAGE_BASE_URL")
        return 0, len(pngs)

    print(f"待推送 {len(pngs)} 张，图片前缀 {base}")
    ok = 0
    for name in pngs:
        stem = os.path.splitext(name)[0]
        parts = stem.split("_")
        suffix = parts[3] if len(parts) > 3 else stem
        key = f"{parts[2]}_{parts[3]}" if len(parts) > 3 else stem
        # 标题里固定带「日报」二字：机器人安全设置若用「自定义关键词」也能通过
        title = f"{LABEL}日报 {td[5:]} {suffix}"

        url = public_url(name, base)
        text = f"## {title}\n\n![]({url})\n"

        names = MENTIONS.get(key) or []
        if names and not str(names[0]).isdigit():
            # 旧配置格式：mentions 里放姓名、mentions_phones 里查手机号
            mobiles = [PHONES.get(n) for n in names]
            mobiles = [m for m in mobiles if m]
        else:
            # 新配置格式（2026-11-06 起）：mentions 直接放手机号
            mobiles = [str(m) for m in names if str(m).strip()]
        display = [k for k, v in PHONES.items() if v in mobiles] or mobiles
        if names and mobiles:
            text += "\n" + " ".join(f"@{m}" for m in mobiles) + "　请查收"
            print(f"  艾特：{'、'.join(display)}")
        elif names:
            print(f"  提示：{'、'.join(names)} 未配手机号，本次不艾特")

        if dry_run:
            print(f"[试运行] {title}\n{text}")
            ok += 1
            continue

        if not wait_reachable(url):
            print(f"[跳过] {name}：CDN 迟迟不可访问")
            continue

        res = send_markdown(title, text, at_mobiles=mobiles or None)
        if res.get("errcode") == 0:
            print(f"[成功] {name}")
            ok += 1
        else:
            print(f"[失败] {name}：{res}")
        time.sleep(1)

    print(f"推送完成：{ok}/{len(pngs)}")
    return ok, len(pngs)


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv
    _args = [a for a in sys.argv[1:] if a != "--dry-run"]
    _ok, _total = push(_args[0] if _args else None, _dry)
    sys.exit(0 if _ok == _total else 1)
