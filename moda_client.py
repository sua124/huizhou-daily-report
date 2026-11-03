"""
摩打后台数据拉取客户端（部署包版：账号密码从 config.json 读取）
- 自动登录 / token 复用（带过期时间）
- 统一请求头 Source: api + Token
- post() 返回接口原始响应 dict（与数据脚本配套）
"""
import json, os, time, urllib.request, urllib.error, http.cookiejar

TOOLS = os.path.dirname(os.path.abspath(__file__))

def _cfg():
    """配置优先级：环境变量 > config_local.json > config.json

    仓库是公开的（CDN 只服务公开仓库），所以 config.json 里不放任何密码。
    - 本地：把真实账号写进 config_local.json（已 gitignore）
    - 云端：用 MODA_ACCOUNT / MODA_PASSWORD 两个 Secrets 注入
    """
    p = os.path.join(TOOLS, "config.json")
    cfg = {}
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    lp = os.path.join(TOOLS, "config_local.json")
    if os.path.exists(lp):
        try:
            with open(lp, "r", encoding="utf-8") as f:
                local = json.load(f)
            for k, v in local.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass

    env_acc = os.environ.get("MODA_ACCOUNT", "").strip()
    env_pwd = os.environ.get("MODA_PASSWORD", "").strip()
    if env_acc or env_pwd:
        cfg.setdefault("moda", {})
        if env_acc:
            cfg["moda"]["account"] = env_acc
        if env_pwd:
            cfg["moda"]["password"] = env_pwd
    return cfg

_C = _cfg()
BASE = _C.get("moda", {}).get("base_url", "https://moda.xjr2018.com")
TOKEN_FILE = os.path.join(TOOLS, "token.json")
RETRY = 3  # 网络抖动重试次数
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

ACCOUNT = _C.get("moda", {}).get("account", "")
PASSWORD = _C.get("moda", {}).get("password", "")


class ModaClient:
    def __init__(self, account=ACCOUNT, password=PASSWORD):
        self.account = account
        self.password = password
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )
        self.token = None
        self._load_token()
        if not self.token:
            self.login()

    def _load_token(self):
        if os.path.exists(TOKEN_FILE):
            try:
                d = json.load(open(TOKEN_FILE, encoding="utf-8"))
                if d.get("exp", 0) > time.time() + 120:
                    self.token = d["token"]
            except Exception:
                pass

    def _save_token(self, token, exp):
        json.dump({"token": token, "exp": exp}, open(TOKEN_FILE, "w", encoding="utf-8"))

    def _raw(self, path, data, headers):
        """单次请求 + 抗抖动重试。

        云端 runner 到后台的链路偶发 ConnectionReset / 超时，以前一次抖动就整份日报作废。
        这里只对「暂时性错误」（网络异常、5xx、429）重试 3 次（2s/4s/8s 退避）；
        业务错误（4xx、返回体里的 code!=1）立即返回，不做无意义重试。
        这些接口都是只读查询，重试不会产生副作用。
        """
        body = json.dumps(data).encode()
        last = None
        for i in range(RETRY):
            req = urllib.request.Request(BASE + path, data=body, headers=headers, method="POST")
            try:
                with self.opener.open(req, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8", "ignore"))
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf-8", "ignore")[:300]
                last = {"code": -1, "_http": e.code, "_body": txt}
                if e.code < 500 and e.code != 429:
                    return last
            except Exception as e:
                last = {"code": -1, "_err": f"{type(e).__name__}: {e}"}
            if i < RETRY - 1:
                delay = 2 ** (i + 1)
                why = last.get("_err") or f"HTTP {last.get('_http')}"
                print(f"  [重试] {path} 暂时失败（{why}），{delay}s 后第 {i + 2}/{RETRY} 次")
                time.sleep(delay)
        return last

    def login(self):
        h = {
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": UA,
            "Origin": BASE,
            "Referer": BASE + "/manage_admin/",
        }
        r = self._raw("/admin/login/login",
                      {"account": self.account, "password": self.password}, h)
        if r.get("code") != 1:
            # 区分「网络打不通」和「账号密码错」，否则排障时会误判
            if r.get("_err") or r.get("_http"):
                raise RuntimeError(f"登录请求失败（网络/服务端问题，已重试 {RETRY} 次）: {r}")
            raise RuntimeError(f"登录失败（账号或密码不对）: {r}")
        self.token = r["data"]["token"]
        self._save_token(self.token, r["data"].get("exp", int(time.time()) + 3600))
        return self.token

    def post(self, path, data=None):
        h = {
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": UA,
            "Origin": BASE,
            "Referer": BASE + "/manage_admin/",
            "Source": "api",
            "Token": self.token,
        }
        r = self._raw(path, data or {}, h)
        if r.get("code") == 0 and "登录" in str(r.get("msg", "")):
            self.login()
            h["Token"] = self.token
            r = self._raw(path, data or {}, h)
        return r


if __name__ == "__main__":
    c = ModaClient()
    print("token ok:", (c.token or "")[:10], "...")
    stores = c.post("/admin/store/getList").get("data", [])
    print("stores:", len(stores))
