# -*- coding: utf-8 -*-
"""手工并集验证：把「现网判的房间」与「正确区」的检索结果合并，看命中能不能回来。

★ 不改任何代码 —— 只是分别调两次 `检索()`，再按相似度合并、取前 N。
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
import 生成 as 生  # noqa: E402

题集 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
d = json.loads(题集.read_text(encoding="utf-8-sig"))
题 = {x["编号"]: x for x in d["覆盖集"]}

#   走错房间的 17 道 → 各自的正确定区
对 = {
    "CV-10": "规则体系", "CV-19": "规则体系", "RL-01": "规则体系", "RL-03": "规则体系",
    "SD-03": "技能目录", "SD-05": "技能目录", "SD-06": "技能目录", "SD-08": "技能目录",
    "SD-09": "技能目录", "SD-10": "技能目录",
    "PL-03": "插件", "PL-05": "插件",
    "MT-02": "维护工具", "MT-03": "维护工具", "MT-05": "维护工具",
    "MT-06": "维护工具", "MT-07": "维护工具",
}


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


print(f"{'题':<8}{'N':<4}{'现网位次':<10}{'并集位次':<10}{'★ 结果':<8}正确定区")
print("-" * 84)
救回 = 0
for 号, 区 in 对.items():
    x = 题[号]
    段们 = 分段(x["原文片段"])
    n = 生.取前条数(生.判类型(x["问题"]))

    #   ① 现网（自动判房间）
    a = 检.检索(x["问题"], 取前=50, 分组=None, 用扩展=True, 自动判房间=True)
    位A = next((i for i, h in enumerate(a["结果"], 1) if all(s in 净(h.get("文本", "")) for s in 段们)), None)

    #   ② 正确定区
    b = 检.检索(x["问题"], 取前=50, 分组=区, 用扩展=True, 自动判房间=False)
    #   ③ 合并（按问题+来源+行号去重，按相似度降序）
    池 = {}
    for h in a["结果"] + b["结果"]:
        k = (h.get("来源文件"), h.get("起始行"), h.get("结束行"))
        池[k] = max(池.get(k, 0.0), h.get("相似度", 0.0))
    排 = sorted(池.items(), key=lambda kv: -kv[1])
    #   ④ 并集后的位次
    位U = None
    for i, (k, _) in enumerate(排, 1):
        块 = next((h for h in b["结果"] + a["结果"] if (h.get("来源文件"), h.get("起始行"), h.get("结束行")) == k), None)
        if 块 and all(s in 净(块.get("文本", "")) for s in 段们):
            位U = i
            break
    救 = "★ 救回" if (位U and 位U <= n) else "没救回"
    if 位U and 位U <= n:
        救回 += 1
    print(f"{号:<8}{n:<4}{str(位A) if 位A else '50+':<10}{str(位U) if 位U else '50+':<10}{救:<8}{区}")

print(f"\n  ★ 并集能救回：{救回}/{len(对)} 道")
print(f"  ★ 若救回，覆盖集命中 = 28 + {救回} = {28 + 救回}/62 = {(28 + 救回) / 62 * 100:.2f}%")
