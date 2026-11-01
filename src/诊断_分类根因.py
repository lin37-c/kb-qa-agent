# -*- coding: utf-8 -*-
"""分类诊断：36 道未命中题，逐题判根因。

四类：
  A 走错房间   —— 正确块所在顶层目录 ≠ 本次检索的分组范围
  B 片段跨块   —— 片段分段后，仍无任何单块含全部段（结构上不可能同块命中）
  C 语义不匹配 —— 正确块能找到，但排不进 Top-5（问题与片段的语义不接近）
  D 判据问题   —— 片段按 `／` 切段后本可同块命中（归一化粘连）
"""
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


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


d = json.loads(题集.read_text(encoding="utf-8-sig"))
r = json.loads(明细.read_text(encoding="utf-8-sig"))
题 = {x["编号"]: x for x in d["覆盖集"]}
未 = [t["编号"] for t in r["覆盖集"] if "异常" not in t and not t.get("严格")]

分类 = {"A 走错房间": [], "B 片段跨块": [], "C 语义不匹配": [], "D 判据问题": []}

for 号 in 未:
    x = 题[号]
    段们 = 分段(x["原文片段"])
    #   全库里有没有单块含全部段
    同块 = [b for b in 块 if all(s in 净(b["文本"]) for s in 段们)]
    #   检索
    try:
        q = 检.检索(x["问题"], 取前=50, 分组=None, 用扩展=True, 自动判房间=True)
    except Exception:  # noqa: BLE001
        continue
    分组 = q.get("分组", "")
    区 = (x["金标准出处"] or "").split("\\")[0].split("/")[0]
    #   正确块在 Top-50 的名次
    位 = None
    for i, h in enumerate(q["结果"], 1):
        if all(s in 净(h.get("文本", "")) for s in 段们):
            位 = i
            break
    #   D：按 ／ 切段后能同块命中，但原文整体（含／）归一化后粘连 → 说明是判据问题
    if not 同块:
        #   再试：按 ／ 切段，看有没有块含"每一段"
        if any(all(s in 净(b["文本"]) for s in 段们) for b in 块) or len(段们) > 1 and any(
            all(s in 净(b["文本"]) for s in 段们) for b in 块
        ):
            pass
        if 位 is None:
            分类["B 片段跨块"].append((号, len(段们), 区))
            continue
    #   A：正确块的来源文件顶层 ≠ 分组覆盖范围
    if 同块:
        源 = 同块[0]["来源文件"]
        if 区 and 区 not in 分组 and "并集" not in 分组 and 分组 not in ("", "全库"):
            分类["A 走错房间"].append((号, 区, 分组, 位))
            continue
    #   C：能找到但排名靠后
    if 位 is not None and 位 > 5:
        分类["C 语义不匹配"].append((号, 位))
        continue
    分类["D 判据问题"].append((号, 位))

for k, v in 分类.items():
    print(f"\n  ★ {k}：{len(v)} 道")
    for it in v:
        print(f"      {it}")
