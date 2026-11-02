"""
把指定日期的三张日报长图推送到钉钉群（以当前用户身份发 Markdown 图文消息）

用法: python push_images.py [YYYY-MM-DD] [--dry-run]   (不传日期默认今天)

说明：
- 钉钉自定义机器人 Webhook 只能发文字，发不了本地图片；
  这里改用钉钉连接器 CLI（dws），图片可在群里直接预览。
- dws 发送是异步的：先拿到 openTaskId，再查 query-send-status 确认。
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
CID = CFG.get("dingtalk_group", {}).get("open_conversation_id", "")
GROUP_NAME = CFG.get("dingtalk_group", {}).get("name", "")
LABEL = CFG.get("store", {}).get("store_label", "门店")
# 每张图要艾特的人：{"02_赠菜折扣与停开售": ["余志玲", "罗惠玲"], ...}
MENTIONS = CFG.get("mentions") or {}
MEMBERS_CACHE = os.path.join(BASE, "members.json")


def _dws_bin():
    """定位 dws CLI。
    - Windows 下同时存在无扩展名的 sh 脚本和 dws.cmd，优先取 .cmd
    - PATH 里查不到时（例如计划任务环境没有注入 WorkBuddy 的 PATH），
      回退到默认安装目录
    """
    for name in ("dws.cmd", "dws.exe", "dws"):
        p = shutil.which(name)
        if p:
            return p
    for rel in (
        r".workbuddy\binaries\node\cli-connector-packages\dws.cmd",
        r".workbuddy\node\cli-connector-packages\dws.cmd",
    ):
        p = os.path.join(os.path.expanduser("~"), rel)
        if os.path.exists(p):
            return p
    return "dws"


DWS = _dws_bin()


def _node_dirs():
    """计划任务环境里通常没有 node，这里把 WorkBuddy 的 node 目录补进 PATH。"""
    dirs = []
    base = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries",
                        "node", "versions")
    if os.path.isdir(base):
        for d in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, d)
            if os.path.exists(os.path.join(p, "node.exe")):
                dirs.append(p)
    pkgs = os.path.join(os.path.expanduser("~"), ".workbuddy", "node",
                        "cli-connector-packages")
    if os.path.isdir(pkgs):
        dirs.append(pkgs)
    return dirs


def _run(args):
    env = os.environ.copy()
    extra = os.pathsep.join(_node_dirs())
    if extra:
        env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    if os.name == "nt":
        # dws 是 .cmd 批处理，必须交给 cmd.exe 才能启动
        cmd = subprocess.list2cmdline([str(a) for a in args])
        kw = {"shell": True}
    else:
        cmd = args
        kw = {}
    p = subprocess.run(cmd, cwd=OUT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, **kw)
    return p.returncode, p.stdout or "", p.stderr or ""


def _load_members():
    try:
        return json.load(open(MEMBERS_CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _refresh_members():
    """拉取群成员，得到 姓名 → openDingTalkId 映射并缓存"""
    code, out, err = _run([
        DWS, "chat", "+chat-members-list",
        "--conversation-id", CID, "--format", "json",
    ])
    data = _first_json_block(out) or {}
    users = data.get("users") or []
    if not users:
        print(f"[警告] 群成员拉取失败，本次不艾特：{(err or out)[:120]}")
        return {}
    m = {u.get("name"): u.get("openDingtalkId") or u.get("openDingTalkId")
         for u in users if u.get("name")}
    try:
        json.dump(m, open(MEMBERS_CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    return m


def _resolve_ids(names, members):
    """把姓名解析成 openDingTalkId；缓存里找不到就刷新一次群成员再试"""
    ids = [(n, members.get(n)) for n in names]
    if any(v is None for _, v in ids):
        members = _refresh_members() or members
        ids = [(n, members.get(n)) for n in names]
    ok = [(n, v) for n, v in ids if v]
    miss = [n for n, v in ids if not v]
    if miss:
        print(f"[警告] 群里找不到这些人，未艾特：{'、'.join(miss)}")
    return ok, members


def _first_json_block(text):
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def push(date=None, dry_run=False):
    """推送该日期的全部日报图片，返回 (成功数, 总数)。"""
    if not CID:
        print("config.json 未配置 dingtalk_group.open_conversation_id，跳过推送")
        return 0, 0

    td = date or datetime.date.today().isoformat()
    pngs = sorted(
        p for p in os.listdir(OUT)
        if p.startswith(f"report_{td}_") and p.lower().endswith(".png")
    )
    if not pngs:
        print(f"output 目录找不到 {td} 的日报图片，请先运行 daily_report.py {td}")
        return 0, 0

    print(f"目标群：{GROUP_NAME}（{CID}）")
    print(f"待推送 {len(pngs)} 张图片")

    members = _load_members()
    ok_count = 0
    for name in pngs:
        stem = os.path.splitext(name)[0]
        parts = stem.split("_")
        suffix = parts[3] if len(parts) > 3 else stem
        key = f"{parts[2]}_{parts[3]}" if len(parts) > 3 else stem
        title = f"{LABEL} {td[5:]} {suffix}"

        content = f"![{title}](./{name})"
        pairs = []
        ats = MENTIONS.get(key) or []
        if ats:
            pairs, members = _resolve_ids(ats, members)
            if pairs:
                content += "\n\n" + " ".join(f"<@{v}>" for _, v in pairs)
                print(f"  艾特：{'、'.join(n for n, _ in pairs)}")

        cmd = [
            DWS, "chat", "message", "send",
            "--group", CID,
            "--title", title,
            "--content", content,
            "--format", "json",
        ]
        if ats and pairs:
            cmd += ["--at-open-dingtalk-ids", ",".join(v for _, v in pairs)]
        if dry_run:
            cmd.append("--dry-run")
        code, out, err = _run(cmd)
        data = _first_json_block(out) or {}
        if code != 0 or not data.get("ok"):
            detail = (data.get("error") if data else None) or err or out
            print(f"[失败] {name}：{str(detail)[:200]}")
            continue
        if dry_run:
            print(f"[试运行] {name} 参数校验通过，未实际发送")
            ok_count += 1
            continue

        task_id = (data.get("data") or {}).get("result", {}).get("openTaskId")
        if not task_id:
            print(f"[警告] {name}：已提交但未返回 taskId：{out[:200]}")
            ok_count += 1
            continue

        _, out2, err2 = _run([
            DWS, "chat", "message", "query-send-status",
            "--open-task-id", task_id, "--format", "json",
        ])
        d2 = _first_json_block(out2) or {}
        msg_id = (d2.get("messageRef") or {}).get("openMessageId")
        if msg_id:
            print(f"[成功] {name} → messageId {msg_id}")
            ok_count += 1
        else:
            print(f"[警告] {name}：状态未确认：{(out2 or err2)[:200]}")

    print(f"推送完成：{ok_count}/{len(pngs)}")
    return ok_count, len(pngs)


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv
    _args = [a for a in sys.argv[1:] if a != "--dry-run"]
    _ok, _total = push(_args[0] if _args else None, _dry)
    sys.exit(0 if _ok == _total else 1)
