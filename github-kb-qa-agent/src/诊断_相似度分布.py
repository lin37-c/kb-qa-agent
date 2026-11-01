# -*- coding: utf-8 -*-
"""细查：命中题 vs 未命中题的相似度分布 —— 定位问题在哪一层。

三个要看的量：
  ① 该题 Top-1 的相似度（问题的"最好匹配有多像"）
  ② 正确块的相似度（答案块有多像）
  ③ 正确块位次
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


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


d = json.loads(题集.read_text(encoding="utf-8-sig"))
r = json.loads(明细.read_text(encoding="utf-8-sig"))
题 = {x["编号"]: x for x in d["覆盖集"]}
m = {t["编号"]: t for t in r["覆盖集"] if "异常" not in t}

中 = [k for k, v in m.items() if v["按题型"]][:8]
未 = [k for k, v in m.items() if not v["按题型"]][:10]

print(f"{'编号':<8}{'中?':<4}{'问题长度':<8}{'Top1分':<9}{'正确块分':<10}{'位次':<8}{'问题'}")
print("-" * 100)
for 组, 标 in ((中, "✅"), (未, "❌")):
    for 号 in 组:
        x = 题[号]
        段们 = 分段(x["原文片段"])
        q = 检.检索(x["问题"], 取前=50, 分组=None, 用扩展=True, 自动判房间=True)
        结果 = q["结果"]
        顶 = 结果[0].get("相似度") if 结果 else None
        正分, 位 = None, None
        for i, h in enumerate(结果, 1):
            if all(s in 净(h.get("文本", "")) for s in 段们):
                正分, 位 = h.get("相似度"), i
                break
        print(
            f"{号:<8}{标:<4}{len(x['问题']):<8}"
            f"{(f'{顶:.4f}' if 顶 else '-'):<9}"
            f"{(f'{正分:.4f}' if 正分 else '-'):<10}"
            f"{(str(位) if 位 else '50+'):<8}{x['问题'][:34]}"
        )
