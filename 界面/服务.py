# -*- coding: utf-8 -*-
"""本地服务入口（M8 第 3 步）。

用法：
    .venv\\Scripts\\python.exe -X utf8 界面\\服务.py
    .venv\\Scripts\\python.exe -X utf8 界面\\服务.py --端口 8765 --开浏览器

只绑 127.0.0.1。端口从 8765 起顺延（最多试 20 个），打印真实 URL。
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

界面目录 = Path(__file__).resolve().parent


def 找源码目录() -> Path:
    """找 `02_项目源码与工程\\src`。

    不能写死 `parents[n]`：同一份代码在**候选区**和**发布后的正式位置**层级不同，
    写死层级必然在某一处失效（本步实测撞到）。按「候选路径 → 向上逐级 → 环境变量」找。
    """
    候选: list[Path] = [界面目录.parent / "src"]
    for 上 in 界面目录.parents:
        候选.append(上 / "02_项目源码与工程" / "src")

    环境 = os.environ.get("M8_项目根")
    if 环境:
        候选.append(Path(环境) / "02_项目源码与工程" / "src")

    for 处 in 候选:
        if (处 / "配置.py").is_file():
            return 处
    raise SystemExit(
        "找不到项目源码目录（含 配置.py 的 02_项目源码与工程\\src）。\n"
        "发布后正常在项目内，会自动找到；在候选区调试时请设置环境变量：\n"
        '    $env:M8_项目根 = "<workspace>\\01_项目\\DeepSeek Harness专用\\LLM知识库检索与工具调用"'
    )


源码目录 = 找源码目录()
for p in (str(源码目录), str(界面目录)):
    if p not in sys.path:
        sys.path.insert(0, p)

import 路由  # noqa: E402


def 选端口(起: int = 8765, 次数: int = 20, 地址: str = "127.0.0.1") -> int:
    for 端口 in range(起, 起 + 次数):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((地址, 端口))
                return 端口
            except OSError:
                continue
    raise SystemExit(f"{起}~{起 + 次数 - 1} 都被占用，请用 --端口 指定")


def 建服务(端口: int, 地址: str = "127.0.0.1") -> ThreadingHTTPServer:
    服务 = ThreadingHTTPServer((地址, 端口), 路由.处理器)
    服务.daemon_threads = True
    return 服务


def main() -> int:
    解释 = argparse.ArgumentParser(description="M9 知识库服务（界面 ＋ v1 接口）")
    解释.add_argument("--端口", type=int, default=0, help="默认从 8765 起自动选")
    解释.add_argument("--地址", default="", help="绑定地址；默认 127.0.0.1（只本机）")
    解释.add_argument("--开浏览器", action="store_true", help="起来后自动打开默认浏览器")
    a = 解释.parse_args()

    # ★ M9 第 4 步：绑定可配，但**放开到局域网必须显式同意**（环境变量 M9_允许外部=1），
    #   否则启动直接拒绝 —— 免得多打一个 --地址 就把服务暴露给整个 WiFi。
    地址 = (a.地址 or os.environ.get("M9_绑定") or "127.0.0.1").strip()
    外部 = 地址 not in ("127.0.0.1", "localhost", "::1")
    if 外部 and os.environ.get("M9_允许外部") != "1":
        raise SystemExit(
            f"❌ 绑定 {地址} 会把服务暴露给同网段。\n"
            "   确认要这么做，请先设环境变量：\n"
            "       $env:M9_允许外部 = \"1\"\n"
            "   并用带 Bearer token 的请求访问（非本机一律要 token）。\n"
            f"   token 位置：{路由.鉴权.令牌信息().get('路径', '（环境变量或尚未生成）')}"
        )

    端口 = a.端口 or 选端口(地址=地址)
    服务 = 建服务(端口, 地址)
    路由.启动预热()

    显示地址 = "127.0.0.1" if 地址 in ("0.0.0.0", "::") else 地址
    url = f"http://{显示地址}:{端口}/"
    print(f"M9 服务已起：{url}")
    令牌 = 路由.鉴权.令牌信息()
    print(f"鉴权：{令牌.get('来源')}｜长度 {令牌.get('长度')}｜文件 {令牌.get('路径', '—')}")
    print("本机环回免 token；非本机需 Authorization: Bearer <token>")
    if 外部:
        print("=" * 72)
        print(f"⚠️  正在对外监听 {地址}：同网段设备可访问。")
        print("    跨站来源一律 403；非本机请求必须带 token。")
        print("=" * 72)
    print("Ctrl+C 结束")
    if a.开浏览器:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()

    try:
        服务.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        服务.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
