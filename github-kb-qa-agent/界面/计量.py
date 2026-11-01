# -*- coding: utf-8 -*-
"""M9 第 4 步：生成计量（**估算**，不是账单）。

为什么要它：
    `/api/ledger` 原来只记账向量与重排，并自述「生成未记账」——
    多调用方时，谁花了多少钱根本算不出来。这里补上。

口径（必须如实）：
    · 单价取**阿里云百炼 qwen-max 华北2 官网原价**：输入 2.4 元／百万 token、
      输出 9.6 元／百万 token（2026-10 查得；缓存命中价 0.48 不单独建模）；
    · 费用＝输入×2.4/M ＋ 输出×9.6/M，**四舍五入到 1e-6 元**；
    · 这是**估算**：实际账单还受缓存命中、Batch 折扣、限时优惠影响 —— 报告里不许说成"账单"。

落点：`data\缓存\生成账本.jsonl`（与用量账本、重排账本同目录；已被 gitignore）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import 配置

单价_输入_元每百万token = 2.4
单价_输出_元每百万token = 9.6
账本文件 = 配置.缓存目录 / "生成账本.jsonl"


def 算费用(输入: int, 输出: int) -> float:
    return (输入 * 单价_输入_元每百万token + 输出 * 单价_输出_元每百万token) / 1_000_000


def 记(任务号: str, 用量: dict, 模型: str) -> dict | None:
    """把一次生成的用量记进账本；没有 token 数就不记（不编造）。"""
    输 = int((用量 or {}).get("prompt_tokens") or 0)
    出 = int((用量 or {}).get("completion_tokens") or 0)
    if not 输 and not 出:
        return None
    记录 = {
        "任务": 任务号, "模型": 模型, "输入": 输, "输出": 出,
        "费用_元": round(算费用(输, 出), 6), "t": time.time(),
    }
    账本文件.parent.mkdir(parents=True, exist_ok=True)
    with 账本文件.open("a", encoding="utf-8") as f:
        f.write(json.dumps(记录, ensure_ascii=False) + "\n")
    return 记录


def 汇总() -> dict:
    if not 账本文件.exists():
        return {"次数": 0, "费用_元": 0.0, "输入token": 0, "输出token": 0}
    次数 = 0
    费用 = 0.0
    输 = 0
    出 = 0
    for 行 in 账本文件.read_text(encoding="utf-8", errors="replace").splitlines():
        行 = 行.strip()
        if not 行:
            continue
        try:
            记录 = json.loads(行)
        except Exception:  # noqa: BLE001
            continue
        次数 += 1
        费用 += float(记录.get("费用_元") or 0)
        输 += int(记录.get("输入") or 0)
        出 += int(记录.get("输出") or 0)
    return {"次数": 次数, "费用_元": round(费用, 6), "输入token": 输, "输出token": 出}
