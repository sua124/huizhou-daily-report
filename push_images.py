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
# 每张图要艾特的手机号：{"02_赠菜折扣与停开售": ["134...", ...], ...}
# 2026-11-06 起直接配手机号（云端机器人用 atMobiles；本地 dws 需经
# mentions_phones 反查姓名、再查 openDingTalkId）
MENTIONS = CFG.get("mentions") or {}
PHONES = CFG.get("mentions_phones") or {}
MOBILE2NAME = {str(v): k for k, v in PHONES.items()}
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


def _valid_id(v):
    """完整 openDingTalkId 一般 30+ 字符；过短视为截断（2026-11-05 的缓存
    就是被截断过，艾特给了残缺 ID 导致群里根本没 @ 到人）。"""
    return bool(v) and len(str(v)) >= 25


def _load_members():
    try:
        m = json.load(open(MEMBERS_CACHE, encoding="utf-8"))
    except Exception:
        return {}
    # 缓存里混有截断 ID 时整份弃用，强制刷新
    if any(not _valid_id(v) for v in m.values()):
        print("[提示] 成员缓存含残缺 ID，重新拉取群成员")
        return {}
    return m


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
    m = {}
    for u in users:
        oid = u.get("openDingtalkId") or u.get("openDingTalkId")
        if u.get("name") and oid:
            if not _valid_id(oid):
                print(f"[警告] {u['name']} 的 ID 疑似截断（{oid}），跳过")
                continue
            m[u["name"]] = oid
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
        # 配置里是手机号 → 反查姓名 → 查 openDingTalkId（兼容旧配置直接写姓名）
        names = [MOBILE2NAME.get(str(a), str(a)) for a in ats]
        if names:
            pairs, members = _resolve_ids(names, members)
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
