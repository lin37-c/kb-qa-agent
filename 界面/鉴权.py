# -*- coding: utf-8 -*-
"""M9 第 4 步：鉴权（用户 2026-10-26 选定的「乙」方案）。

规则（写进《服务契约 v1》§二）：
    1. **本机环回免 token**：127.0.0.1／::1 来的请求放行 —— 界面脚本零摩擦；
    2. **非本机必须带 token**：`Authorization: Bearer <token>`，否则 401 UNAUTHORIZED；
    3. **跨站来源一律 403**：浏览器会自动带 `Origin`，而本机脚本/界面不带 ——
       只要 `Origin` 与 `Host` 不同源，就拒。这条挡的是"你随便开的网页偷偷 POST 你的端口"：
       实测服务端**不校验 Content-Type**，页面用 `text/plain` 塞 JSON 也能打进来，花你的钱。
    4. `health` 免鉴权（探活不需要凭据）。

token 从哪来（按优先级）：
    · 环境变量 `M9_TOKEN`（不落盘）；
    · 文件 `data\\服务\\token.txt`（本机文件，权限靠系统账户）；
    · 都没有 ⇒ **自动生成一次并落盘**。只打印**路径与长度**，永不打印内容（同 AGENTS.md 风险区域 1）。
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import 配置

令牌环境变量名 = "M9_TOKEN"
令牌文件 = 配置.数据目录 / "服务" / "token.txt"
回环地址 = {"127.0.0.1", "::1", "localhost", ""}
免鉴权路径 = {"/api/health", "/api/v1/health"}


def 取令牌() -> str:
    值 = (os.environ.get(令牌环境变量名) or "").strip()
    if 值:
        return 值
    try:
        if 令牌文件.is_file():
            值 = 令牌文件.read_text(encoding="utf-8").strip()
            if 值:
                return 值
    except OSError:
        pass
    值 = secrets.token_urlsafe(24)
    令牌文件.parent.mkdir(parents=True, exist_ok=True)
    令牌文件.write_text(值 + "\n", encoding="utf-8")
    return 值


def 令牌信息() -> dict:
    """只报来源与长度，不报内容（与 /api/health 的「密钥」同一口径）。"""
    if (os.environ.get(令牌环境变量名) or "").strip():
        return {"来源": "环境变量", "长度": len(os.environ[令牌环境变量名].strip())}
    try:
        if 令牌文件.is_file():
            值 = 令牌文件.read_text(encoding="utf-8").strip()
            if 值:
                return {"来源": "文件", "长度": len(值), "路径": str(令牌文件)}
    except OSError:
        pass
    return {"来源": "未配置", "长度": 0, "路径": str(令牌文件)}


def 判定(客户端地址: str, 路径: str, 头) -> tuple[int, dict] | None:
    """None＝放行；否则返回 (状态码, 响应体)。"""
    if 路径 in 免鉴权路径:
        return None
    if not 路径.startswith("/api/"):
        return None                     # 静态页面：本机使用，不鉴权

    #   ★ 先判来源，再判 token：跨站请求哪怕带了正确 token 也拒（防被网页窃用）
    来源 = (头.get("Origin") or "").strip()
    if 来源:
        主机 = (头.get("Host") or "").strip()
        规范 = 来源.split("://", 1)[-1].rstrip("/")
        if 来源 == "null" or 规范 != 主机:
            return 403, {"码": "FORBIDDEN", "说明": f"不接受跨站来源：{来源}",
                         "可重试": False}

    if 客户端地址 in 回环地址:
        return None                     # 乙：本机环回免 token

    授权 = (头.get("Authorization") or "").strip()
    if not 授权.lower().startswith("bearer "):
        return 401, {"码": "UNAUTHORIZED",
                     "说明": "非本机访问需要 Authorization: Bearer <token>",
                     "可重试": False}
    给 = 授权[7:].strip()
    #   ★ 必须比 bytes：`compare_digest` 对含非 ASCII 的 str 会直接抛 TypeError
    #     （拿一个中文假 token 打就会 500 —— 实测撞到）。token 本身是 ASCII，但输入不可信。
    if not secrets.compare_digest(给.encode("utf-8"), 取令牌().encode("utf-8")):
        return 401, {"码": "UNAUTHORIZED", "说明": "token 不对", "可重试": False}
    return None
