# -*- coding: utf-8 -*-
"""诊断：36 道未命中题，正确块在 50 名里排第几 —— 区分「差一点」和「真不行」。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

本文件 = Path(__file__).resolve()
SRC = 本文件.parent
根 = SRC.parent.parent
sys.path.insert(0, str(SRC if (SRC / "检索.py").exists() else 根 / "02_项目源码与工程" / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as 检  # noqa: E402

题集 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
明细 = 根 / "05_项目验证证据" / "_M7评测" / "命中率_第1步.json"


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


d = json.loads(题集.read_text(encoding="utf-8-sig"))
r = json.loads(明细.read_text(encoding="utf-8-sig"))
未 = [t["编号"] for t in r["覆盖集"] if "异常" not in t and not t.get("严格")]
题 = {x["编号"]: x for x in d["覆盖集"]}

print(f"  诊断 {len(未)} 道未命中题（取前 50）…")
桶 = {"6~10 名": [], "11~20 名": [], "21~50 名": [], "50 名内没有": []}
for 号 in 未:
    x = 题[号]
    段们 = 分段(x["原文片段"])
    try:
        q = 检.检索(x["问题"], 取前=50, 分组=None, 用扩展=True, 自动判房间=True)
    except Exception:  # noqa: BLE001
        continue
    位 = None
    for i, h in enumerate(q["结果"], 1):
        b = 净(h.get("文本", ""))
        if all(seg in b for seg in 段们):
            位 = i
            break
    if 位 is None:
        桶["50 名内没有"].append((号, x["原文片段"][:40]))
    elif 位 <= 10:
        桶["6~10 名"].append((号, 位, x["原文片段"][:40]))
    elif 位 <= 20:
        桶["11~20 名"].append((号, 位, x["原文片段"][:40]))
    else:
        桶["21~50 名"].append((号, 位, x["原文片段"][:40]))

for k, v in 桶.items():
    print(f"\n  ★ {k}：{len(v)} 道")
    for it in v:
        print(f"      {it[0]}｜排第 {it[1]}" if len(it) == 3 else f"      {it[0]}｜「{it[1]}」")
