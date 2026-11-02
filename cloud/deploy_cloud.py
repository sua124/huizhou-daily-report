"""
一条命令把日报部署到 GitHub Actions（无需任何手动网页操作）

用法（本机执行）:
    python cloud/deploy_cloud.py --pat ghp_xxx \
        --webhook-token xxxxxxxx [--webhook-secret SECxxxx] \
        [--repo huizhou-daily-report]

做的事:
    1. 校验令牌，拿到账号名
    2. 建一个公开仓库（图床需要公开）
    3. 把摩打账号密码 + 钉钉机器人凭证写成 Repo Secrets（加密存储，页面不可见）
    4. 推送本地代码
    5. 触发一次运行，返回运行页面链接

凭证只在本进程内存里用，不落盘、不写进 .git/config。
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = "daily_report.yml"


def api(method, path, pat, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(API + path, data=body, method=method)
    r.add_header("Authorization", "Bearer " + pat)
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("User-Agent", "daily-report-deploy")
    if body:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            txt = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(txt) if txt.strip() else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt}


def sh(cmd, pat=""):
    p = subprocess.run(cmd, cwd=ROOT, shell=True, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if pat:
        out = out.replace(pat, "***")
    return p.returncode, out.strip()


def encrypt_secret(pub_key_b64, value):
    from nacl import encoding, public
    pk = public.PublicKey(pub_key_b64.encode(), encoding.Base64Encoder())
    return base64.b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pat", required=True, help="GitHub 个人访问令牌 ghp_xxx")
    ap.add_argument("--webhook-token", required=True, help="钉钉机器人 access_token")
    ap.add_argument("--webhook-secret", default="", help="钉钉机器人加签密钥 SECxxx（选了自定义关键词就留空）")
    ap.add_argument("--repo", default="huizhou-daily-report", help="仓库名")
    ap.add_argument("--account", default="505", help="摩打后台账号")
    ap.add_argument("--password", default="789789", help="摩打后台密码")
    ap.add_argument("--skip-run", action="store_true", help="只部署，不立即触发运行")
    a = ap.parse_args()

    pat = a.pat.strip()
    print("① 校验令牌…")
    code, me = api("GET", "/user", pat)
    if code != 200:
        print("   失败：", me.get("message", code))
        return 1
    owner = me["login"]
    print(f"   账号 {owner}")

    print(f"② 创建仓库 {owner}/{a.repo} …")
    code, repo = api("POST", "/user/repos", pat, {
        "name": a.repo,
        "description": "门店经营日报自动推送（GitHub Actions）",
        "private": False,          # jsDelivr 图床只服务公开仓库
        "has_issues": False,
        "has_wiki": False,
    })
    if code == 201:
        print("   已创建")
    elif code == 422:
        print("   仓库已存在，继续使用")
    else:
        print("   失败：", repo.get("message", code))
        return 1

    print("③ 写入加密变量…")
    code, key = api("GET", f"/repos/{owner}/{a.repo}/actions/secrets/public-key", pat)
    if code != 200:
        print("   取公钥失败：", key.get("message", code))
        return 1
    secrets = {
        "MODA_ACCOUNT": a.account,
        "MODA_PASSWORD": a.password,
        "DINGTALK_WEBHOOK_TOKEN": a.webhook_token.strip(),
    }
    if a.webhook_secret.strip():
        secrets["DINGTALK_WEBHOOK_SECRET"] = a.webhook_secret.strip()
    for name, val in secrets.items():
        enc = encrypt_secret(key["key"], val)
        c, r = api("PUT", f"/repos/{owner}/{a.repo}/actions/secrets/{name}", pat,
                   {"encrypted_value": enc, "key_id": key["key_id"]})
        print(f"   {name}: {'OK' if c in (201, 204) else '失败 ' + str(r.get('message', c))}")
        if c not in (201, 204):
            return 1

    print("④ 推送代码…")
    sh("git branch -M main")
    url = f"https://x-access-token:{pat}@github.com/{owner}/{a.repo}.git"
    code, out = sh(f'git push "{url}" main --force', pat)
    if code != 0:
        print("   推送失败：\n" + out[-1500:])
        return 1
    print("   完成")

    if a.skip_run:
        print(f"\n仓库地址：https://github.com/{owner}/{a.repo}")
        return 0

    print("⑤ 触发一次运行验证…")
    for attempt in range(6):
        c, r = api("POST", f"/repos/{owner}/{a.repo}/actions/workflows/{WORKFLOW}/dispatches",
                   pat, {"ref": "main"})
        if c in (204, 201):
            break
        time.sleep(5)
    else:
        print("   触发失败（workflow 可能还没注册），稍后到网页上点一次 Run workflow")
        print(f"   仓库地址：https://github.com/{owner}/{a.repo}")
        return 0

    time.sleep(8)
    c, runs = api("GET", f"/repos/{owner}/{a.repo}/actions/runs?per_page=1", pat)
    run = (runs.get("workflow_runs") or [{}])[0]
    print(f"\n仓库：https://github.com/{owner}/{a.repo}")
    print(f"运行：{run.get('html_url', '（请手动打开 Actions 页面查看）')}")
    print("\n接下来：等这次运行跑完（约 3-6 分钟），看群里有没有收到 3 张图。")
    print("收到之后，就可以停掉电脑上的两个计划任务了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
