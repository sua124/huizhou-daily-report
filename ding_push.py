# -*- coding: utf-8 -*-
"""钉钉自定义机器人推送：正佳广场店经营日报"""
import time, hmac, hashlib, base64, urllib.parse, urllib.request, json, ssl, sys, os

WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=74d3603bf4c3041ff211111242b9fd16340dce28212d427fd053a9a3f9b8d211"
SECRET = "SEC9e50fa8e60335af4950849f3587568d3c80905b5d4dbd5197efefe564fdf9596"

CTX = ssl.create_default_context()

def _sign():
    ts = str(round(time.time() * 1000))
    secret_enc = SECRET.encode("utf-8")
    string_to_sign = f"{ts}\n{SECRET}".encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{WEBHOOK}&timestamp={ts}&sign={sign}"

def send(payload):
    req = urllib.request.Request(_sign(), data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=CTX, timeout=15) as r:
        resp = json.loads(r.read().decode("utf-8"))
    if resp.get("errcode") != 0:
        raise RuntimeError(f"钉钉返回错误: {resp}")
    return resp

def send_text(text, at_all=False):
    payload = {"msgtype": "text", "text": {"content": text}}
    if at_all:
        payload["at"] = {"isAtAll": True}
    return send(payload)

def send_markdown(title, md, at_all=False):
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": md}}
    if at_all:
        payload["at"] = {"isAtAll": True}
    return send(payload)

if __name__ == "__main__":
    print(send_text("【测试】正佳日报机器人连通测试，收到请忽略。" if len(sys.argv) < 2 else sys.argv[1]))
