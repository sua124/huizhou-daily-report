"""通过 GitHub REST API 上传代码（不依赖 git push）

背景：本机到 github.com 的 git 传输通道（443 上的 smart-HTTP）会被重置，
而 api.github.com 一路畅通。所以改用 Git Data API 逐文件建 blob → tree → commit → 建分支。

用法:
    python cloud/push_via_api.py --pat ghp_xxx [--repo huizhou-daily-report] [--message "说明"]

只上传 git 已跟踪的文件（git ls-files），所以 .gitignore 里的敏感文件天然不会进仓库。
"""
import argparse
import base64
import json
import os
import subprocess
import sys
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
        with urllib.request.urlopen(r, timeout=90) as resp:
            txt = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(txt) if txt.strip() else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt}


def tracked_files():
    p = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    raw = p.stdout.decode("utf-8", "replace")
    return [f for f in raw.split("\0") if f.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pat", required=True)
    ap.add_argument("--repo", default="huizhou-daily-report")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="部署门店经营日报（GitHub Actions 云端推送）")
    ap.add_argument("--no-run", action="store_true", help="只上传，不触发运行")
    ap.add_argument("--date", default="", help="触发时带上日报日期 YYYY-MM-DD")
    a = ap.parse_args()
    pat = a.pat.strip()

    code, me = api("GET", "/user", pat)
    if code != 200:
        print("令牌无效：", me.get("message", code))
        return 1
    owner = me["login"]
    print(f"账号：{owner}/{a.repo}")

    # 已有提交则作为父节点，避免覆盖历史
    parent = None
    c, ref = api("GET", f"/repos/{owner}/{a.repo}/git/ref/heads/{a.branch}", pat)
    if c == 200:
        parent = ref["object"]["sha"]
        print("远端已有分支，将建立新提交（父节点", parent[:7] + "）")
    else:
        # 空仓库状态下 Git Data API 全线返回 409「Git Repository is empty」，
        # 必须先用 Contents API 放进一个文件把仓库"点亮"，之后才能正常建 blob/tree。
        print("空仓库，先写入引导文件…")
        boot = base64.b64encode(b"* text=auto eol=lf\n").decode()
        c2, r2 = api("PUT", f"/repos/{owner}/{a.repo}/contents/.gitattributes", pat, {
            "message": "初始化仓库", "content": boot, "branch": a.branch,
        })
        if c2 not in (200, 201):
            print("  引导失败：", r2.get("message", c2))
            return 1
        parent = r2["commit"]["sha"]
        print("  引导提交", parent[:7])

    files = tracked_files()
    print(f"待上传 {len(files)} 个文件…")
    tree = []
    for i, rel in enumerate(files, 1):
        full = os.path.join(ROOT, rel)
        with open(full, "rb") as f:
            data = f.read()
        c, blob = api("POST", f"/repos/{owner}/{a.repo}/git/blobs", pat, {
            "content": base64.b64encode(data).decode(),
            "encoding": "base64",
        })
        if c != 201:
            print(f"  ✗ {rel} — {blob.get('message', c)}")
            return 1
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  [{i}/{len(files)}] {rel} ({len(data)} B)")

    payload = {"tree": tree}
    if parent:
        payload["base_tree"] = api(
            "GET", f"/repos/{owner}/{a.repo}/git/commits/{parent}", pat)[1]["tree"]["sha"]
    c, t = api("POST", f"/repos/{owner}/{a.repo}/git/trees", pat, payload)
    if c != 201:
        print("建 tree 失败：", t.get("message", c))
        return 1

    commit_body = {"message": a.message, "tree": t["sha"]}
    if parent:
        commit_body["parents"] = [parent]
    c, cm = api("POST", f"/repos/{owner}/{a.repo}/git/commits", pat, commit_body)
    if c != 201:
        print("建 commit 失败：", cm.get("message", c))
        return 1
    print("commit:", cm["sha"][:7])

    if parent:
        c, r = api("PATCH", f"/repos/{owner}/{a.repo}/git/refs/heads/{a.branch}", pat,
                   {"sha": cm["sha"], "force": True})
    else:
        c, r = api("POST", f"/repos/{owner}/{a.repo}/git/refs", pat,
                   {"ref": f"refs/heads/{a.branch}", "sha": cm["sha"]})
    if c not in (200, 201):
        print("更新分支失败：", r.get("message", c))
        return 1
    print("分支已更新")

    # 允许 workflow 用 GITHUB_TOKEN 把日报图提交回仓库（CDN 需要）
    c, p = api("PUT", f"/repos/{owner}/{a.repo}/actions/permissions/workflow", pat,
               {"default_workflow_permissions": "write",
                "can_approve_pull_request_reviews": False})
    print("Actions 写权限：", "OK" if c in (200, 204) else f"未设置({c})")

    # 触发一次运行
    if a.no_run:
        print(f"\n仓库：https://github.com/{owner}/{a.repo}（已跳过运行）")
        return 0
    print("触发运行…")
    import time
    payload = {"ref": a.branch}
    if a.date:
        payload["inputs"] = {"date": a.date}
    for _ in range(8):
        c, d = api("POST", f"/repos/{owner}/{a.repo}/actions/workflows/{WORKFLOW}/dispatches",
                   pat, payload)
        if c in (204, 201):
            print("已触发")
            break
        time.sleep(6)
    else:
        print("触发失败（workflow 可能尚未被识别）：", d.get("message", c))
        print(f"稍后手动点一次：https://github.com/{owner}/{a.repo}/actions")
        return 0

    time.sleep(8)
    c, runs = api("GET", f"/repos/{owner}/{a.repo}/actions/runs?per_page=1", pat)
    run = (runs.get("workflow_runs") or [{}])[0]
    print("\n仓库：https://github.com/" + owner + "/" + a.repo)
    print("运行：", run.get("html_url", "（打开 Actions 页面查看）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
