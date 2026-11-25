"""给单个群的 webhook 发一条测试消息，验证通路（不动正式日报）

用法:
    python cloud/test_send.py --token <access_token> [--text "自定义内容"]

安全设置若是「自定义关键词」，内容必须包含「日报」二字才能发出去。
"""
import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--text", default="通道已连通，今晚开始这里也会同步收到门店日报。")
    args = ap.parse_args()

    title = "日报通道测试"
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"## {title}\n\n{args.text}"},
        "at": {"isAtAll": False},
    }
    url = ("https://oapi.dingtalk.com/robot/send?access_token="
           + args.token.strip())
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode())
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("errcode") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
