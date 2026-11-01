# -*- coding: utf-8 -*-
"""向量化：把一段文字变成一串数字（embedding）。

这个模块负责三件事：
    1. 取密钥（从环境变量；取不到就去 Windows 注册表读「用户级环境变量」）
    2. 调用智谱 embedding-3，拿到向量
    3. 记录真实用量，供成本核算

注意：向量是"算"出来的，不是"查"出来的。同一段文字每次算结果都一样（确定性），
      所以我们能用「内容哈希」做缓存，避免重复付费。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

import 配置


# ---------- 密钥 ----------
def 取密钥() -> str:
    """优先读进程环境变量；读不到则从 Windows 注册表读用户级环境变量。

    为什么要读注册表：
        DSH 是在设置环境变量之前启动的，它的子进程继承的是旧环境，读不到新变量。
        而用户级环境变量本身已经写进注册表 HKCU\\Environment，新进程可以直接读取。
    """
    k = os.environ.get(配置.密钥环境变量名)
    if k:
        return k
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
            v, _ = winreg.QueryValueEx(h, 配置.密钥环境变量名)
            return v
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"读不到 {配置.密钥环境变量名}。请确认已设置为 Windows 用户级环境变量。({e})"
        ) from e


# ---------- 用量账本 ----------
账本路径 = 配置.缓存目录 / "用量账本.jsonl"


def _记用量(场景: str, tokens: int) -> None:
    """把每次调用的真实 token 用量追加进账本（jsonl = 一行一条 JSON）。

    为什么要记账：
        embedding 是按 token 付费的。没有账本，就只能"感觉"花了多少钱；
        有账本，才能说清"这一步入库花了多少"。这也是可写进简历的工程习惯。
    """
    账本路径.parent.mkdir(parents=True, exist_ok=True)
    条目 = {
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "场景": 场景,
        "模型": 配置.向量模型,
        "tokens": tokens,
        "费用_元": round(tokens / 1_000_000 * 配置.向量单价_元每百万token, 8),
    }
    with 账本路径.open("a", encoding="utf-8") as f:
        f.write(json.dumps(条目, ensure_ascii=False) + "\n")


def 读账本() -> dict:
    """汇总账本：总 token、总费用、调用次数。"""
    if not 账本路径.exists():
        return {"次数": 0, "tokens": 0, "费用_元": 0.0}
    次数 = tokens = 0
    for line in 账本路径.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        次数 += 1
        tokens += d.get("tokens", 0)
    return {
        "次数": 次数,
        "tokens": tokens,
        "费用_元": round(tokens / 1_000_000 * 配置.向量单价_元每百万token, 6),
    }


# ---------- 内容哈希 ----------
def 内容指纹(文本: str) -> str:
    """算一段文字的"指纹"（sha256 前 16 位）。

    用途：判断这段文字是不是已经算过。内容没变 → 指纹不变 → 直接用缓存，不再付费。

    ★ 注意：这个指纹是**块的身份**，全项目（切片、评测集、可接受块、证据 json）都在用，
       **不能为了换模型去改它**，否则所有历史证据都会对不上。
       换模型的隔离在 `_缓存键()` 里做。
    """
    return hashlib.sha256(文本.encode("utf-8")).hexdigest()[:16]


def _缓存键(文本: str) -> str:
    """缓存键 = 模型 + 维度 + 内容指纹。

    ★ 为什么必须带模型（2026-10-24 换阿里时发现）：缓存原来只按文本记，
      换模型后同一段文字会命中旧模型算出的向量 —— 维度不同（1024 vs 2048）、
      语义空间也不同，检索会**静默变烂**，而且不报错。
    """
    return f"{配置.向量模型}@{配置.向量维度}|{内容指纹(文本)}"


# ---------- 核心：调用 embedding ----------
def _请求(texts: list[str], 场景: str, 重试: int = 3) -> list[list[float]]:
    """真正发 HTTP 请求。失败会重试（网络抖动、限流都可能发生）。"""
    key = 取密钥()
    url = f"{配置.服务地址}/embeddings"
    payload = {
        "model": 配置.向量模型,
        "input": texts,
        "dimensions": 配置.向量维度,
    }
    last_err = None
    for i in range(重试):
        try:
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            _记用量(场景, j.get("usage", {}).get("total_tokens", 0))
            # 返回顺序与输入顺序一致（API 约定 data[i] 对应 input[i]）
            return [d["embedding"] for d in j["data"]]
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < 重试 - 1:
                time.sleep(1.5 * (i + 1))   # 退避：失败后等一会儿再试
    raise RuntimeError(f"embedding 连续 {重试} 次失败：{last_err}")


def 向量化(texts: list[str], 场景: str = "未命名") -> list[list[float]]:
    """对外主函数：把一批文字变成一批向量。

    流程：先按内容指纹查缓存 → 只把没算过的送去调接口 → 结果写回缓存。
    这样重跑时只要内容没变，费用就是 0。
    """
    if not texts:
        return []

    from 缓存 import 向量缓存          # 延迟导入，避免循环依赖

    if _缓存实例[0] is None:
        _缓存实例[0] = 向量缓存()
    缓存 = _缓存实例[0]

    结果: list[list[float] | None] = [None] * len(texts)
    待算: list[tuple[int, str, str]] = []      # (位置, 文本, 指纹)

    for i, t in enumerate(texts):
        指纹 = _缓存键(t)
        v = 缓存.取(指纹)
        if v is not None:
            结果[i] = v
        else:
            待算.append((i, t, 指纹))

    # 只把未命中的送去算
    for i in range(0, len(待算), 配置.批次大小):
        批 = 待算[i : i + 配置.批次大小]
        新向量 = _请求([t for _, t, _ in 批], 场景)
        for (pos, _t, 指纹), v in zip(批, 新向量):
            缓存.存(指纹, v)
            结果[pos] = v

    return [v for v in 结果 if v is not None]      # type: ignore[misc]


_缓存实例: list = [None]


def 缓存实例():
    """给外部（如演示脚本）查看缓存统计用。"""
    return _缓存实例[0]


def 向量化单条(text: str, 场景: str = "单条") -> list[float]:
    return 向量化([text], 场景)[0]
