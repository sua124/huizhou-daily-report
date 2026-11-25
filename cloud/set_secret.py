"""把密钥写进 GitHub Actions Secrets（libsodium sealed box 加密）

用法:
    python cloud/set_secret.py --name DINGTALK_WEBHOOK_TOKEN2 --value df78e8...
    python cloud/set_secret.py --name XXX --value YYY --delete

为什么要有这个脚本：GitHub 的 secrets 接口要求先用仓库公钥做 sealed box 加密，
手搓很容易出错；这里封成一条命令，靠 pynacl。
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDS = os.path.join(BASE, "cloud", ".creds.json")


def api(method, url, pat, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + pat)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "wb-secret")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read().decode()
        return json.loads(t) if t.strip() else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--value", default="")
    ap.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    creds = json.load(open(CREDS, encoding="utf-8"))["github"]
    pat, repo = creds["pat"], creds["repo"]
    if "/" not in repo:
        repo = f"{creds['account']}/{repo}"
    base = f"https://api.github.com/repos/{repo}/actions/secrets"

    if args.delete:
        api("DELETE", f"{base}/{args.name}", pat)
        print(f"已删除 secret {args.name}")
        return

    key = api("GET", f"{base}/public-key", pat)
    from nacl import encoding, public
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(args.value.encode())
    enc = base64.b64encode(sealed).decode()

    api("PUT", f"{base}/{args.name}", pat,
        {"encrypted_value": enc, "key_id": key["key_id"]})
    print(f"已写入 secret {args.name}（{len(args.value)} 字符）")


if __name__ == "__main__":
    sys.exit(main())
