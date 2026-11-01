# -*- coding: utf-8 -*-
"""本地服务路由（M9 第 3 步 · 队列与 v1 前缀）。

M9 在 M8 的路由上改了三件事（其余分支原样保留）：
    · **版本前缀**：`/api/v1/…` 与旧 `/api/…` 走同一套分支 —— 只在入口做一次归一化，绝不复制路由；
    · **单飞 → 有界队列**：先排队、队满才 429（并发默认 1、上限 2、队列 8；见 `队列.py`）；
    · **任务过期/重启 → 410 GONE**（原来是含糊的 404）；会话消息与出处仍可取原文。

仍未做（M9 后续步）：鉴权与绑定（第 4 步）、超时与取消（第 5 步）。

零依赖：只用标准库 http.server。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import 配置
import 契约
import 会话
import 原文
import 队列 as 排队
import 鉴权
import 计量

界面目录 = Path(__file__).resolve().parent

# ★ 放在最后：验证脚本要先 import 路由、再替换 生成.回答，才能抓到"同一份原始结果"。
import 生成  # noqa: E402
import 检索  # noqa: E402

_状态 = {"就绪": False, "库块数": 0, "错误": ""}
_任务表: dict[str, dict] = {}
_任务锁 = threading.Lock()
_当前 = {"任务": "", "开始": 0.0}
_任务上限 = 20
_队列 = None
_任务号格式 = re.compile(r"^j_\d{6}_\d{2}$")


def _读整(名: str, 默认: int) -> int:
    try:
        return int(os.environ.get(名, "") or 默认)
    except ValueError:
        return 默认


def _并发数() -> int:
    return max(1, min(2, _读整("M9_并发", 1)))      # 契约 §七：默认 1，上限 2


def _队列容量() -> int:
    return max(1, _读整("M9_队列长度", 8))


def _保留秒() -> float:
    """任务保留多久（秒）；≤0 表示不按时间过期（只给测试用）。

    ★ 这里必须用 float：测试要把它设成 0.3 秒，用 int() 解析会抛 ValueError
      然后**悄悄落回 1800** —— 实测就是这么让「过期→410」测成 200 的。
    """
    try:
        return float(os.environ.get("M9_任务保留秒", "") or 1800)
    except ValueError:
        return 1800.0


def _生成超时秒() -> float:
    try:
        return float(os.environ.get("M9_生成超时秒", "") or 60)
    except ValueError:
        return 60.0


class 超时(Exception):
    """单题超过上限（契约：60 秒）。★ 异步模型下它只能走 error 事件，给不出 HTTP 504。"""


def _带超时(函数, *a, **kw):
    """在后台线程里跑，超时就抛 `超时`；线程仍会自己跑完，但结果不再被采用。"""
    结果: dict = {}

    def 跑() -> None:
        try:
            结果["值"] = 函数(*a, **kw)
        except BaseException as e:  # noqa: BLE001
            结果["错"] = e

    线程 = threading.Thread(target=跑, name="生成-超时看守", daemon=True)
    线程.start()
    线程.join(_生成超时秒())
    if 线程.is_alive():
        raise 超时(f"生成超过 {_生成超时秒():g} 秒未返回")
    if "错" in 结果:
        raise 结果["错"]
    return 结果.get("值")


def _取队列() -> 排队.有界队列:
    global _队列
    if _队列 is None:
        _队列 = 排队.有界队列(并发=_并发数(), 容量=_队列容量())
    return _队列


def _取任务(任务号: str):
    """取任务；不存在或过期 → (None, (状态码, 响应体))。

    ★ 为什么"我们的任务号 + 查不到"给 410 而不是 404：
      任务只在内存（重启即丢）、且 30 分钟过期；能走到"号对但没了"的，只有这两种情况。
      而号格式不对的，才是调用方拼错 —— 那才是 404。这叫把"该重问"和"你写错了"分开。
    """
    with _任务锁:
        任 = _任务表.get(任务号)
    if 任 is None:
        if _任务号格式.match(任务号 or ""):
            return None, (410, {"码": "GONE", "说明": "任务不存在（可能已过期，或服务重启过）"})
        return None, (404, {"码": "NOT_FOUND", "说明": f"任务号格式不对：{任务号}"})
    保留 = _保留秒()
    if 保留 > 0 and time.time() - float(任.get("开始") or 0) > 保留:
        with _任务锁:
            _任务表.pop(任务号, None)
        return None, (410, {"码": "GONE", "说明": f"任务已过期（保留 {保留:g} 秒）"})
    return 任, None

静态类型 = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


# ---------------------------------------------------------------------------
# 预热与只读信息
# ---------------------------------------------------------------------------
def 启动预热() -> None:
    """后台把向量库读进内存。82.8 MB，冷启动 3~5 秒；不预热第一问会白等。"""

    def 跑() -> None:
        try:
            _, 元数据 = 检索._载库()
            _状态["库块数"] = len(元数据)
            _状态["就绪"] = True
        except Exception as e:  # noqa: BLE001
            _状态["错误"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=跑, name="预热", daemon=True).start()


def 密钥信息() -> dict:
    """只报来源与长度，**不报内容**（AGENTS.md 风险区域 1）。"""
    import os

    key = os.environ.get(配置.密钥环境变量名)
    if key:
        return {"来源": "进程环境", "长度": len(key)}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
            key, _ = winreg.QueryValueEx(h, 配置.密钥环境变量名)
        return {"来源": "注册表", "长度": len(key)}
    except Exception:  # noqa: BLE001
        return {"来源": "未找到", "长度": 0}


def 账本() -> dict:
    合计 = 0.0
    条数 = 0
    for 名 in ("用量账本.jsonl", "重排账本.jsonl"):
        文件 = 配置.缓存目录 / 名
        if not 文件.exists():
            continue
        for 行 in 文件.read_text(encoding="utf-8", errors="replace").splitlines():
            行 = 行.strip()
            if not 行:
                continue
            try:
                记录 = json.loads(行)
            except Exception:  # noqa: BLE001
                continue
            合计 += float(记录.get("费用_元") or 0)
            条数 += 1
    生成 = 计量.汇总()
    return {
        "条目": 条数,
        "累计_元": round(合计 + 生成["费用_元"], 4),
        "生成": 生成,
        "口径": ("向量与重排按账本实算；生成按官网原价**估算**"
                 "（qwen-max：输入 2.4／输出 9.6 元每百万 token，缓存命中与折扣未建模）"),
    }


# ---------------------------------------------------------------------------
# 交互日志与度量（第 7 步）
# ---------------------------------------------------------------------------
_日志锁 = threading.Lock()
日志路径 = 配置.界面数据目录 / "交互日志.jsonl"


def _日志(事件: dict) -> None:
    """一行一个 JSON。**日志写失败不能拖垮问答**，所以吞掉异常并只做最小记录。"""
    事件 = dict(事件)
    事件.setdefault("t", round(time.time(), 3))
    try:
        日志路径.parent.mkdir(parents=True, exist_ok=True)
        with _日志锁, 日志路径.open("a", encoding="utf-8") as f:
            f.write(json.dumps(事件, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _中位数(值们: list[float]):
    值们 = sorted(float(x) for x in 值们 if isinstance(x, (int, float)))
    if not 值们:
        return None
    n = len(值们)
    m = n // 2
    return round(值们[m], 2) if n % 2 else round((值们[m - 1] + 值们[m]) / 2, 2)


def 度量() -> dict:
    """从交互日志算三个时延。口径写在返回里，不靠人猜。"""
    if not 日志路径.exists():
        return {"任务数": 0, "口径": "本机交互日志；中位数；只含本服务产生的事件"}
    按任务: dict[str, dict] = {}
    for 行 in 日志路径.read_text(encoding="utf-8", errors="replace").splitlines():
        行 = 行.strip()
        if not 行:
            continue
        try:
            e = json.loads(行)
        except Exception:  # noqa: BLE001
            continue
        j = e.get("job")
        if not j:
            continue
        d = 按任务.setdefault(j, {"标注": []})
        t = e.get("t")
        类型 = e.get("类型")
        if 类型 == "ask":
            d["ask"] = t
        elif 类型 == "sources":
            d["sources"] = t
        elif 类型 == "first_delta":
            d["first_delta"] = t
        elif 类型 == "final":
            d["final"] = t
        elif 类型 == "source_open":
            d.setdefault("source_open", t)
        elif 类型 == "label":
            d["标注"].append(e.get("值"))

    可点, 首字, 验真 = [], [], []
    有源 = 有验 = 0
    for d in 按任务.values():
        if not d.get("ask"):
            continue
        if d.get("sources"):
            可点.append(d["sources"] - d["ask"])
        if d.get("first_delta"):
            首字.append(d["first_delta"] - d["ask"])
            if d.get("source_open"):
                有验 += 1
                验真.append(d["source_open"] - d["first_delta"])
        if d.get("first_delta"):
            有源 += 1

    标注计数 = {"完整": 0, "部分": 0, "错": 0}
    for d in 按任务.values():
        for v in d.get("标注") or []:
            if v in 标注计数:
                标注计数[v] += 1

    return {
        "任务数": sum(1 for d in 按任务.values() if d.get("ask")),
        "出处可点时延中位数": _中位数(可点),
        "首字时延中位数": _中位数(首字),
        "验真时延中位数": _中位数(验真),
        "验真率": round(有验 / 有源, 3) if 有源 else None,
        "标注计数": 标注计数,
        "口径": "本机交互日志；全部取中位数；验真时延＝首次点开原文 − 首字；只含本服务产生的事件",
    }


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------
_事件锁 = threading.Lock()


def _记事件(任务号: str, 事件名: str, 数据: dict) -> None:
    """把事件追加到任务上。SSE 端从头回放 —— 连得晚也不会丢。

    ★ 第 8 步加 `序`：回放＋重连时前端可能重复收到同一批事件，
      带序号才能让前端"只认比已收到的更大的"。没有序号时，重连会把
      `start` 再放一遍，前端就多出一张永远停在"生成中"的占位卡（实测撞到）。
    """
    任 = _任务表.get(任务号)
    if not 任:
        return
    with _事件锁:
        事件们 = 任.setdefault("事件", [])
        数据 = dict(数据)
        数据["序"] = len(事件们) + 1
        事件们.append({"事件": 事件名, "数据": 数据})


def _取事件(任务号: str) -> list[dict]:
    任 = _任务表.get(任务号)
    if not 任:
        return []
    with _事件锁:
        return list(任.get("事件") or [])


def _跑(任务号: str, 查询: str, 问题: str, 口径: dict, 会话id: str) -> None:
    任 = _任务表.get(任务号) or {}
    任.pop("排队位次", None)
    开始 = time.time()

    def 检索完成(检索结果: dict) -> None:
        任["检索结果"] = 检索结果
        任["阶段"] = "生成中"
        if 任.get("已停") or 任.get("已超时"):
            return
        骨架 = 契约.骨架消息(问题, 口径, 检索结果)
        骨架["id"] = "m_" + 任务号
        骨架["任务"] = 任务号
        _记事件(任务号, "start", {"job": 任务号, "消息": 骨架, "检索耗时": round(time.time() - 开始, 1)})
        _日志({"类型": "sources", "job": 任务号})

    def 流式增量(文本: str) -> None:
        if 任.get("已停") or 任.get("已超时"):
            return
        if not 任.get("首个增量"):
            任["首个增量"] = True
            _日志({"类型": "first_delta", "job": 任务号})
        _记事件(任务号, "delta", {"文本": 文本})

    try:
        任["阶段"] = "检索与生成中"
        原始 = _带超时(生成.回答, 查询, 检索完成回调=检索完成, 流式回调=流式增量)
        # ★ 计量：估算本次生成花了多少（没有 token 数就不记，不编造；失败不影响回答）
        try:
            计量.记(任务号, (原始 or {}).get("用量") or {}, 配置.对话模型)
        except Exception:  # noqa: BLE001
            pass
        用时 = time.time() - 开始
        if 任.get("已停"):
            任.update({"完成": True, "已停止": True, "阶段": "已停止"})
            _记事件(任务号, "error", {"码": "STOPPED", "说明": "已停止", "可重试": False})
        else:
            消息 = 契约.转消息(原始, 问题, 口径, 用时, 检索结果=任.get("检索结果"))
            消息["id"] = "m_" + 任务号
            消息["任务"] = 任务号
            任.update({"完成": True, "消息": 消息, "阶段": "完成"})
            if 会话id:
                # ★ 落盘在**服务端**：刷新页面还在，且与界面状态解耦
                会话.追加消息(会话id, 消息)
            _日志({"类型": "final", "job": 任务号, "状态": 消息.get("状态")})
            _记事件(任务号, "final", {"job": 任务号, "消息": 消息, "用时": round(用时, 1)})
    except 超时 as e:
        #   契约 v1.2：异步模型下超时给不出 HTTP 504 —— 只能落 error 事件（事件码 UPSTREAM_TIMEOUT）
        任.update({"完成": True, "错误": str(e), "阶段": "超时", "已超时": True})
        _记事件(任务号, "error", {"码": "UPSTREAM_TIMEOUT", "说明": str(e), "可重试": True})
    except Exception as e:  # noqa: BLE001
        任.update({"完成": True, "错误": f"{type(e).__name__}: {e}", "阶段": "失败"})
        _记事件(任务号, "error", {"码": "UPSTREAM_ERROR", "说明": f"{type(e).__name__}: {e}", "可重试": True})
    finally:
        _当前["任务"] = ""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class 处理器(BaseHTTPRequestHandler):
    server_version = "M8-UI/0.3"   # ★ 必须是 latin-1 可编码：HTTP 头不能放中文
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        return  # 不刷 stderr；交互日志由前端自己记

    def handle_error(self, request, client_address) -> None:
        """客户端正常挂断（curl 收完就关、浏览器刷新）不是错误，别刷一屏栈。

        ★ 实测：SSE 收尾断连、curl 一次请求后关闭，都会在服务端落一个
          ConnectionResetError(10054)／ConnectionAbortedError(10053) 的 traceback。
          功能没坏，但真错误会被噪声淹掉 —— 所以只静默这三种，其余照常打印。
        """
        import sys as _sys

        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def do_GET(self):  # noqa: N802
        self._分发("GET")

    def do_POST(self):  # noqa: N802
        self._分发("POST")

    def do_DELETE(self):  # noqa: N802
        self._分发("DELETE")

    # ---------- 基础 ----------
    def _分发(self, 方法: str) -> None:
        try:
            u = urlsplit(self.path)
            路径 = unquote(u.path)
            查询 = parse_qs(u.query)
            # ★ M9 第 4 步：先过鉴权（乙方案：本机环回免 token；非本机要 Bearer；跨站来源 403）
            拒绝 = 鉴权.判定(self.client_address[0], 路径, self.headers)
            if 拒绝:
                _日志({"类型": "denied", "路径": 路径, "码": 拒绝[1].get("码")})
                return self._json(*拒绝)
            # ★ M9：`/api/v1/…` 在**入口**归一化成旧路径，后面所有分支原样复用 ——
            #   绝不复制一套路由（复制就会两边慢慢长歪）。旧路径继续可用 = 前端 0 改动。
            用v1 = 路径 == "/api/v1" or 路径.startswith("/api/v1/")
            if 用v1:
                路径 = "/api" + 路径[len("/api/v1"):]
            if 路径.startswith("/api/"):
                self._接口(方法, 路径, 查询, 用v1=用v1)
            else:
                self._静态(路径)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"码": "INTERNAL", "说明": f"{type(e).__name__}: {e}"})

    def _发送(self, 码: int, 类型: str, 数据: bytes, 缓存: str = "no-cache",
              头: dict | None = None) -> None:
        self.send_response(码)
        self.send_header("Content-Type", 类型)
        self.send_header("Content-Length", str(len(数据)))
        self.send_header("Cache-Control", 缓存)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (头 or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(数据)

    def _json(self, 码: int, 对象, 头: dict | None = None) -> None:
        数据 = json.dumps(对象, ensure_ascii=False).encode("utf-8")
        self._发送(码, "application/json; charset=utf-8", 数据, 缓存="no-store", 头=头)

    def _体(self) -> dict:
        长度 = int(self.headers.get("Content-Length") or 0)
        if 长度 > 8192:
            raise ValueError("请求体超过 8 KB")
        原文 = self.rfile.read(长度) if 长度 else b""
        if not 原文:
            return {}
        try:
            return json.loads(原文.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"请求体不是合法 JSON：{e}") from e

    # ---------- 静态 ----------
    def _静态(self, 路径: str) -> None:
        if 路径 in ("", "/"):
            文件 = 界面目录 / "index.html"
        else:
            文件 = (界面目录 / 路径.lstrip("/")).resolve()
            if 文件 != 界面目录 and 界面目录 not in 文件.parents:
                return self._json(404, {"码": "NOT_FOUND", "说明": "路径越界"})
        if not 文件.is_file():
            return self._json(404, {"码": "NOT_FOUND", "说明": f"文件不存在：{路径}"})
        类型 = 静态类型.get(文件.suffix.lower(), "application/octet-stream")
        self._发送(200, 类型, 文件.read_bytes())

    # ---------- 接口 ----------
    def _接口(self, 方法: str, 路径: str, 查询: dict, 用v1: bool = False) -> None:
        段 = [s for s in 路径.strip("/").split("/") if s]

        if 方法 == "GET" and 路径 == "/api/health":
            return self._json(200, {
                "就绪": _状态["就绪"],
                "库块数": _状态["库块数"],
                "错误": _状态["错误"],
                "模型": 配置.对话模型,
                "向量": f"{配置.向量模型}@{配置.向量维度}",
                "重排": 配置.重排模型,
                "阈值": {"高": 检索.重排阈值_高, "低": 检索.重排阈值_低},
                "密钥": 密钥信息(),
                "鉴权": 鉴权.令牌信息(),
                "模式": "真链路",
            })

        if 方法 == "GET" and 路径 == "/api/ledger":
            return self._json(200, 账本())

        if 方法 == "GET" and 路径 == "/api/metrics":
            return self._json(200, 度量())

        if 方法 == "POST" and 路径 == "/api/ask":
            return self._发起()

        if len(段) == 3 and 段[0] == "api" and 段[1] == "job" and 方法 == "GET":
            return self._任务(段[2])

        if len(段) == 3 and 段[0] == "api" and 段[1] == "stream" and 方法 == "GET":
            return self._事件流(段[2])

        if len(段) == 4 and 段[0] == "api" and 段[1] == "job":
            任务号, 动作 = 段[2], 段[3]
            if 动作 == "source" and 方法 == "GET":
                return self._原文(任务号, 查询)
            if 动作 == "stop" and 方法 == "POST":
                return self._停止(任务号)
            if 动作 == "label" and 方法 == "POST":
                if 用v1:
                    #   契约 §四：标注不进 v1 —— 只有人能判「完整／部分／错」，程序调用方不该有这一票
                    return self._json(404, {"码": "NOT_FOUND",
                                            "说明": "v1 不提供人工标注（仅界面内部使用）"})
                return self._标注(任务号)

        if len(段) >= 2 and 段[0] == "api" and 段[1] == "sessions":
            if len(段) == 2 and 方法 == "GET":
                return self._json(200, {"会话": 会话.列表()})
            if len(段) == 2 and 方法 == "POST":
                return self._json(200, 会话.新建())
            if len(段) == 3:
                会话id = 段[2]
                if 方法 == "GET":
                    存 = 会话.读(会话id)
                    return self._json(200, 存) if 存 else self._json(
                        404, {"码": "NOT_FOUND", "说明": f"会话不存在：{会话id}"})
                if 方法 == "DELETE":
                    return self._json(200, {"ok": True}) if 会话.删除(会话id) else self._json(
                        404, {"码": "NOT_FOUND", "说明": f"会话不存在：{会话id}"})
            return self._json(405, {"码": "BAD_REQUEST", "说明": f"会话接口不支持 {方法}"})

        return self._json(404, {"码": "NOT_FOUND", "说明": f"未知接口：{路径}"})

    # ---------- SSE ----------
    def _事件流(self, 任务号: str) -> None:
        """Server-Sent Events：从头回放该任务的全部事件。

        为什么回放而不是"只推新的"：POST /api/ask 与 EventSource 建连是两次请求，
        中间有几百毫秒的空档；只推新的会丢掉最早的 `start`。
        """
        任, 错 = _取任务(任务号)
        if 错:
            return self._json(*错)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def 写(数据: bytes) -> None:
            self.wfile.write(f"{len(数据):X}\r\n".encode("ascii") + 数据 + b"\r\n")
            self.wfile.flush()

        try:
            已发 = 0
            while True:
                事件们 = _取事件(任务号)
                while 已发 < len(事件们):
                    ev = 事件们[已发]
                    已发 += 1
                    序 = ev["数据"].get("序", 已发)
                    体 = (
                        f"id: {序}\n" +
                        "event: " + ev["事件"] + "\n" +
                        "data: " + json.dumps(ev["数据"], ensure_ascii=False) + "\n\n"
                    ).encode("utf-8")
                    写(体)
                if 任.get("完成") and 已发 >= len(_取事件(任务号)):
                    break
                time.sleep(0.05)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            #   ★ SSE 收尾后必须断开长连接：否则客户端一走，下一轮 readline 就抛
            #     ConnectionResetError（10054），在服务端刷一屏无意义的栈。
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 客户端关了页面或点了停止：安静收场

    # ---------- 原文 ----------
    def _原文(self, 任务号: str, 查询: dict) -> None:
        """按 job ＋ 编号取原文。**路径由服务端从任务或落盘消息里取，客户端给不了路径。**"""
        try:
            编号 = int((查询.get("编号") or ["0"])[0])
        except (TypeError, ValueError):
            return self._json(400, {"码": "BAD_REQUEST", "说明": "编号必须是整数"})

        任, 错 = _取任务(任务号)
        检索结果 = 任.get("检索结果") if 任 else None
        if 检索结果:
            命中 = 检索结果.get("结果") or []
            if not (1 <= 编号 <= len(命中)):
                return self._json(404, {"码": "NOT_FOUND",
                                        "说明": f"编号 {编号} 不在该任务的召回里（共 {len(命中)} 条）"})
            h = 命中[编号 - 1]
            来源, 标题 = h, h.get("标题路径", "")
        else:
            # ★ 服务重启后任务表为空 —— 退回**落盘消息**里的出处（第 8 步加）。
            #   否则旧消息点角标一律"取不到原文"，人工验收实测撞到。
            找 = 会话.按任务找消息(任务号)
            if not 找:
                if 错:
                    return self._json(*错)
                return self._json(404, {"码": "NOT_FOUND",
                                        "说明": "任务不存在，会话里也没有这条记录（可能已被删除）"})
            消息 = 找["消息"]
            候选 = ((消息.get("出处") or []) + (消息.get("未采用") or [])
                  + ((消息.get("拒答") or {}).get("最接近") or []))
            h = next((x for x in 候选 if int(x.get("编号") or 0) == 编号), None)
            if not h:
                return self._json(404, {"码": "NOT_FOUND", "说明": f"这条消息里没有编号 {编号} 的出处"})
            标题 = h.get("标题路径", "")

        片段 = 原文.取片段(
            h.get("来源文件", ""), h.get("起始行", 0), h.get("结束行", 0),
            h.get("文本", ""), h.get("内容指纹", ""),
        )
        if "错误" in 片段:
            return self._json(404 if 片段.get("码") == "NOT_FOUND" else 400,
                              {"码": 片段.get("码", "INTERNAL"), "说明": 片段["错误"]})
        片段["编号"] = 编号
        片段["标题路径"] = 标题
        _日志({"类型": "source_open", "job": 任务号, "编号": 编号})
        return self._json(200, 片段)

    def _标注(self, 任务号: str) -> None:
        """用户标注（完整／部分／错）。**只有人能判**，所以这里是唯一的写入点。"""
        try:
            体 = self._体()
        except ValueError as e:
            return self._json(400, {"码": "BAD_REQUEST", "说明": str(e)})
        值 = str(体.get("值") or "")
        if 值 not in ("完整", "部分", "错"):
            return self._json(400, {"码": "BAD_REQUEST", "说明": "值只能是 完整／部分／错"})
        备注 = str(体.get("备注") or "")[:200]
        任, 错 = _取任务(任务号)
        if 错:
            return self._json(*错)

        会话id = 任.get("会话")
        写进会话 = False
        if 会话id:
            存 = 会话.读(会话id)
            if 存:
                for m in reversed(存.get("消息") or []):
                    if m.get("角色") == "assistant" and m.get("任务") == 任务号:
                        m["标注"] = {"值": 值, "备注": 备注,
                                  "时间": datetime.now().isoformat(timespec="seconds")}
                        会话.保存(存)
                        写进会话 = True
                        break
        _日志({"类型": "label", "job": 任务号, "值": 值, "备注": 备注})
        return self._json(200, {"ok": True, "写进会话": 写进会话})

    def _发起(self) -> None:
        try:
            体 = self._体()
        except ValueError as e:
            return self._json(400, {"码": "BAD_REQUEST", "说明": str(e)})

        问题 = str(体.get("问题") or "").strip()
        if not 问题:
            return self._json(400, {"码": "BAD_REQUEST", "说明": "问题不能为空"})
        if len(问题) > 1000:
            return self._json(400, {"码": "BAD_REQUEST", "说明": f"问题过长（{len(问题)} 字，上限 1000）"})

        会话id = str(体.get("会话") or "").strip()
        if 会话id and 会话.读(会话id) is None:
            return self._json(404, {"码": "NOT_FOUND", "说明": f"会话不存在：{会话id}"})

        追问 = bool(体.get("追问"))
        上文 = 会话.上一条用户消息(会话id) if (追问 and 会话id) else ""
        查询 = f"上文：{上文}\n本问：{问题}" if 上文 else 问题
        口径 = ({"值": "带上文", "说明": "连续追问（M7 未评测）", "实际查询": 查询}
              if 上文 else {"值": "独立", "说明": "独立检索（M7 已评测）"})

        if not _状态["就绪"]:
            return self._json(503, {"码": "NO_READY", "说明": "知识库尚未载入完成，请稍等再试"})

        if 密钥信息().get("来源") == "未找到":
            #   契约 §五：NO_KEY 原来只在纸上，这里兑现 —— 缺密钥属于"配好再用"，不可重试
            return self._json(503, {"码": "NO_KEY",
                                    "说明": f"读不到 {配置.密钥环境变量名}，请先配置密钥",
                                    "可重试": False})

        with _任务锁:
            任务号 = "j_" + datetime.now().strftime("%H%M%S") + f"_{len(_任务表) + 1:02d}"
            _任务表[任务号] = {
                "阶段": "排队", "完成": False, "已停": False,
                "开始": time.time(), "消息": None, "错误": "", "会话": 会话id,
            }
            while len(_任务表) > _任务上限:
                最早 = next(iter(_任务表))
                if 最早 == 任务号:
                    break
                _任务表.pop(最早, None)

        # ★ 单飞 → 有界队列：先排队，队满才拒（契约 §七）。位次＝提交时前面还有几单。
        位次 = _取队列().提交(任务号, lambda: _跑(任务号, 查询, 问题, 口径, 会话id))
        if 位次 is None:
            with _任务锁:
                _任务表.pop(任务号, None)
            _日志({"类型": "busy", "job": 任务号})
            return self._json(429, {
                "码": "BUSY", "说明": "队列已满，请稍后重试",
                "可重试": True, "建议等待秒": 3,
            }, 头={"Retry-After": "3"})

        任 = _任务表.get(任务号) or {}
        任["排队位次"] = 位次
        _记事件(任务号, "queued", {"job": 任务号, "位次": 位次})
        if 会话id:
            #   落用户消息放在**入队成功之后**：队列满被拒的那次不留半条记录
            会话.追加消息(会话id, {"角色": "user", "文本": 问题})
        _当前["任务"] = 任务号
        _当前["开始"] = time.time()
        _日志({"类型": "ask", "job": 任务号, "会话": 会话id, "问题": 问题,
               "追问": 追问, "口径": 口径.get("值"), "排队": 位次})
        return self._json(200, {"job": 任务号, "排队": 位次, "口径": 口径})

    def _任务(self, 任务号: str) -> None:
        任, 错 = _取任务(任务号)
        if 错:
            return self._json(*错)
        出 = {
            "job": 任务号,
            "完成": bool(任.get("完成")),
            "阶段": 任.get("阶段", ""),
            "已用秒": round(time.time() - float(任.get("开始") or time.time()), 1),
        }
        if not 任.get("完成"):
            位次 = int(任.get("排队位次") or 0)
            出["排队位次"] = 位次
        if 任.get("消息"):
            出["消息"] = 任["消息"]
        if 任.get("已停止"):
            出["已停止"] = True
        if 任.get("错误"):
            出["错误"] = 任["错误"]
        return self._json(200, 出)

    def _停止(self, 任务号: str) -> None:
        任, 错 = _取任务(任务号)
        if 错:
            return self._json(*错)
        任["已停"] = True
        # ★ 非流式路径无法真正中断已在执行的 HTTP 调用；这里只保证**结果不再交付**。
        return self._json(200, {"ok": True, "说明": "已标记停止；本次调用仍会跑完，但结果不再交付"})
