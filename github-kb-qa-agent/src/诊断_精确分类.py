# -*- coding: utf-8 -*-
"""精确分类：用 `检索.精确分组` 的前缀表判"走错房间"。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

本文件 = Path(__file__).resolve()
SRC = 本文件.parent
根 = SRC.parent.parent
sys.path.insert(0, str(SRC))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as 检  # noqa: E402

题集 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
明细 = 根 / "05_项目验证证据" / "_M7评测" / "命中率_第1步.json"
块 = [json.loads(l) for l in (根 / "data/向量库/切片.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
前 = 检.精确分组


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


d = json.loads(题集.read_text(encoding="utf-8-sig"))
r = json.loads(明细.read_text(encoding="utf-8-sig"))
题 = {x["编号"]: x for x in d["覆盖集"]}
未 = [t["编号"] for t in r["覆盖集"] if "异常" not in t and not t.get("严格")]

类 = {}
for 号 in 未:
    x = 题[号]
    段们 = 分段(x["原文片段"])
    同块 = [b for b in 块 if all(s in 净(b["文本"]) for s in 段们)]
    try:
        q = 检.检索(x["问题"], 取前=50, 分组=None, 用扩展=True, 自动判房间=True)
    except Exception:  # noqa: BLE001
        continue
    分组 = q.get("分组", "")
    组长 = 分组.replace("并集:", "")
    覆盖 = 前.get(组长, ())
    if not 覆盖:
        覆盖 = 前.get("全库", ())
    位 = None
    for i, h in enumerate(q["结果"], 1):
        if all(s in 净(h.get("文本", "")) for s in 段们):
            位 = i
            break
    #   判类
    if not 同块:
        类.setdefault("B 片段跨块（结构上不可能同块命中）", []).append((号, len(段们)))
        continue
    源 = 同块[0]["来源文件"]
    在组内 = any(源.startswith(p) for p in 覆盖) if 覆盖 else True
    if not 在组内:
        类.setdefault("A 走错房间（正确答案不在本次分组内）", []).append((号, 源.split("/")[0], 分组, 位))
    elif 位 is None:
        类.setdefault("C 同房间但 50 名外（片段语义不匹配）", []).append((号, 源.split("/")[0], 分组))
    elif 位 > 10:
        类.setdefault("C 同房间但排名靠后（11~50 名）", []).append((号, 位))
    else:
        类.setdefault("D 只差一点（6~10 名）", []).append((号, 位))

for k in sorted(类):
    v = 类[k]
    print(f"\n  ★ {k}：{len(v)} 道")
    for it in v:
        print(f"      {it}")
    if k.startswith("A"):
        print(f"      → 改法：**修「自动判房间」或改题面加前缀**（不是片段问题）")
    elif k.startswith("B"):
        print(f"      → 改法：**换片段**（选一段连续文本，不要跨块）")
    elif k.startswith("C"):
        print(f"      → 改法：**换片段**（选真正回答问题的句子）")
    elif k.startswith("D"):
        print(f"      → 改法：**报 Top-10 口径**（Top-5 天然吃亏）")
