# -*- coding: utf-8 -*-
"""会话存储（M8 第 6 步）：一个会话一个 JSON，落在 `data\\界面\\会话\\`。

为什么放服务端而不是浏览器：
    ① 刷新、换标签页都还在（浏览器存储会随清理消失）；
    ② M9 服务化时这份就是现成的数据层；
    ③ 界面与数据分开，界面状态坏了不影响问答记录。

三条硬规则：
    · **id 白名单**：只接受 `s_…` 形态，非法 id 一律拒（防路径穿越）；
    · **原子写**：先写 `.tmp` 再 `os.replace`，断电不会留下半截 JSON；
    · **只增不改**：消息只追加；删除会话＝删整个文件。
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

import 配置

会话目录 = 配置.界面数据目录 / "会话"
_id白名单 = re.compile(r"^s_[A-Za-z0-9_\-]{1,40}$")

#   ★ 同一个会话的「读—改—写」必须串行：否则并发追加会互相覆盖（丢消息）。
#     锁按会话 id 分，不同会话之间互不阻塞。
_锁表: dict[str, threading.RLock] = {}
_锁表锁 = threading.Lock()


def _取锁(会话id: str) -> threading.RLock:
    with _锁表锁:
        return _锁表.setdefault(会话id, threading.RLock())


def _路(会话id: str) -> Path:
    if not _id白名单.match(会话id or ""):
        raise ValueError(f"会话 id 不合法：{会话id!r}")
    路径 = (会话目录 / f"{会话id}.json").resolve()
    if 会话目录.resolve() not in 路径.parents:
        raise ValueError("会话路径越界")
    return 路径


def _原子写(路径: Path, 数据: dict) -> None:
    """原子写；**临时文件名必须唯一**。

    ★ M9 第 7 步实测：并发 5 路提问同一个会话时，原先固定的 `.json.tmp` 会被多个线程
      同时写；Windows 下 `os.replace` 抛 `WinError 32（另一个程序正在使用此文件）`，
      接口直接 500 —— M8 单飞时从没暴露。⇒ 临时名带 pid／线程／随机串，失败也清理干净。
    """
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时 = 路径.with_name(
        f"{路径.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:6]}.tmp")
    try:
        临时.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(临时, 路径)
    finally:
        if 临时.exists():
            try:
                临时.unlink()
            except OSError:
                pass


def 新建() -> dict:
    会话目录.mkdir(parents=True, exist_ok=True)
    会话id = "s_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    会话 = {"id": 会话id, "标题": "新对话",
            "创建": datetime.now().isoformat(timespec="seconds"), "消息": []}
    with _取锁(会话id):
        _原子写(_路(会话id), 会话)
    return 会话


def 读(会话id: str) -> dict | None:
    try:
        路径 = _路(会话id)
    except ValueError:
        return None
    if not 路径.is_file():
        return None
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def 保存(会话: dict) -> None:
    with _取锁(会话["id"]):
        _原子写(_路(会话["id"]), 会话)


def 列表() -> list[dict]:
    if not 会话目录.is_dir():
        return []
    出 = []
    for 文件 in 会话目录.glob("s_*.json"):
        try:
            会话 = json.loads(文件.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        出.append({
            "id": 会话.get("id", 文件.stem),
            "标题": 会话.get("标题") or "新对话",
            "创建": 会话.get("创建", ""),
            "条数": len(会话.get("消息") or []),
        })
    出.sort(key=lambda x: x.get("创建") or "", reverse=True)
    return 出


def 删除(会话id: str) -> bool:
    try:
        路径 = _路(会话id)
    except ValueError:
        return False
    with _取锁(会话id):
        if 路径.is_file():
            路径.unlink()
            return True
    return False


def 追加消息(会话id: str, 消息: dict) -> dict | None:
    #   ★ 整个「读→改→写」在同一把会话锁里：5 路并发时不会互相覆盖（第 7 步实测过丢写）
    with _取锁(会话id):
        会话 = 读(会话id)
        if 会话 is None:
            return None
        消息 = dict(消息)
        消息.setdefault("时间", datetime.now().isoformat(timespec="seconds"))
        会话.setdefault("消息", []).append(消息)
        if 消息.get("角色") == "user" and (会话.get("标题") in (None, "", "新对话")):
            会话["标题"] = str(消息.get("文本") or "新对话")[:20]
        保存(会话)
        return 会话


def 上一条用户消息(会话id: str) -> str:
    会话 = 读(会话id)
    if not 会话:
        return ""
    for 消息 in reversed(会话.get("消息") or []):
        if 消息.get("角色") == "user":
            return str(消息.get("文本") or "")
    return ""


def 按任务找消息(任务号: str) -> dict | None:
    """服务重启后任务表就空了，但消息还在盘上 —— 按 `任务` 字段把它找回来。

    用途：旧消息点角标取原文。找不到文件就返回 None（不猜）。
    """
    if not 会话目录.is_dir():
        return None
    for 文件 in 会话目录.glob("s_*.json"):
        try:
            会话 = json.loads(文件.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for 消息 in 会话.get("消息") or []:
            if 消息.get("任务") == 任务号:
                return {"会话": 会话, "消息": 消息}
    return None
