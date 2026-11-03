"""运行失败时往钉钉群发一条告警，避免"静默漏发"。

用法（workflow 里 if: failure() 调用）:
    python cloud/alert.py
环境变量: DINGTALK_WEBHOOK_TOKEN、GITHUB_RUN_URL（GitHub 自动注入 RUN_URL 拼出）
"""
import datetime
import json
import os
import urllib.request

TOKEN = os.environ.get("DINGTALK_WEBHOOK_TOKEN", "").strip()
SECRET = os.environ.get("DINGTALK_WEBHOOK_SECRET", "").strip()
RUN_URL = os.environ.get("GITHUB_RUN_URL", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
LABEL = os.environ.get("STORE_LABEL", "惠州店")


def sign(token, secret):
    import base64
    import hashlib
    import hmac
    import time
    import urllib.parse

    ts = str(round(time.time() * 1000))
    s = f"{ts}\n{secret}".encode()
    h = hmac.new(secret.encode(), s, digestmod=hashlib.sha256).digest()
    return (
        f"https://oapi.dingtalk.com/robot/send?access_token={token}"
        f"&timestamp={ts}&sign={urllib.parse.quote_plus(base64.b64encode(h))}"
    )


def main():
    if not TOKEN:
        print("没有 DINGTALK_WEBHOOK_TOKEN，跳过告警")
        return 0

    url = sign(TOKEN, SECRET) if SECRET else (
        f"https://oapi.dingtalk.com/robot/send?access_token={TOKEN}"
    )
    today = datetime.date.today().isoformat()
    link = RUN_URL or (f"https://github.com/{REPO}/actions" if REPO else "")
    text = (
        f"### {LABEL}日报生成失败\n\n"
        f"- 日期：{today}\n"
        f"- 原因：云端流程中途报错（常见是数据接口超时或图片提交冲突）\n"
        f"- 排查：{link}\n\n"
        f"可以在手机 GitHub → Actions → 该次运行 → 点 Run workflow 重跑一次。"
    )
    body = {"msgtype": "markdown",
            "markdown": {"title": f"{LABEL}日报失败", "text": text}}
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json;charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("告警已发送:", r.read().decode())
    except Exception as e:
        print("告警发送失败:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
