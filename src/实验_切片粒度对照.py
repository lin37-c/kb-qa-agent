# -*- coding: utf-8 -*-
"""小样对照实验：切片粒度对检索效果的影响（只切 02_规则，不碰现有索引）。

做法：
  ① 用**当前参数**（最小 300 / 最大 900）切 `02_规则` 的 md；
  ② 用**小参数**（最小 120 / 最大 380）切同一批；
  ③ 两种各向量化（有缓存，重复块不花钱）；
  ④ 对「规则区」的题，算**正确块的最高相似度**，对比。

判据：相似度提升 ⇒ 排序会前移 ⇒ 切小有效。
"""
from __future__ import annotations

import importlib
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

切片 = importlib.import_module("切片")
向量化 = importlib.import_module("向量化")

A = Path(r"<asset-root>")
题集 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


#   规则区的 md 文件（02_规则 下全部）
文件们 = sorted((A / "02_规则").rglob("*.md"))
print(f"  `02_规则` 下 md 文件：{len(文件们)} 个")

原最小, 原最大 = 切片.最小块字符, 切片.最大块字符


def 切一组(小: int, 大: int):
    切片.最小块字符, 切片.最大块字符 = 小, 大
    出 = []
    for p in 文件们:
        try:
            出.extend(切片.切文件(p, A))
        except Exception:  # noqa: BLE001
            pass
    return 出


组 = {}
for 名, (小, 大) in (("当前 300/900", (原最小, 原最大)), ("小切 120/380", (120, 380))):
    块 = 切一组(小, 大)
    字 = [b.字符数 for b in 块]
    print(f"  {名}：{len(块)} 块｜中位 {sorted(字)[len(字) // 2]} 字｜总 {sum(字):,} 字符")
    组[名] = 块
切片.最小块字符, 切片.最大块字符 = 原最小, 原最大

#   向量化
d = json.loads(题集.read_text(encoding="utf-8-sig"))
规则题 = [x for x in d["覆盖集"] if x["期望区域"] in ("规则", "维护")]

for 名, 块 in 组.items():
    print(f"\n  向量化「{名}」…（{len(块)} 块）")
    文本s = [b.文本 for b in 块]
    向 = 向量化.向量化(文本s, 场景="小样实验")
    组[名] = (块, 向)

print()
print(f"{'题':<8}{'当前切法':<12}{'小切法':<12}{'★ 变化':<10}问题")
print("-" * 92)
import numpy as np  # noqa: E402

汇总 = {"当前 300/900": [], "小切 120/380": []}
for x in 规则题:
    段们 = 分段(x["原文片段"])
    行 = [x["编号"]]
    for 名 in ("当前 300/900", "小切 120/380"):
        块, 向 = 组[名]
        qv = 向量化.向量化单条(x["问题"], 场景="小样实验")
        qv = qv / (np.linalg.norm(qv) + 1e-9)
        分 = []
        for i, b in enumerate(块):
            if all(s in 净(b.文本) for s in 段们):
                v = 向[i] / (np.linalg.norm(向[i]) + 1e-9)
                分.append(float(qv @ v))
        顶 = max(分) if 分 else None
        行.append(顶)
        汇总[名].append(顶)
    a, b = 行[1], 行[2]
    dlt = f"{b - a:+.4f}" if (a and b) else "—"
    print(f"{行[0]:<8}{(f'{a:.4f}' if a else '找不到'):<12}{(f'{b:.4f}' if b else '找不到'):<12}{dlt:<10}{x['问题'][:28]}")

print()
for 名, v in 汇总.items():
    有 = [x for x in v if x]
    if 有:
        print(f"  {名}：找到答案块 {len(有)}/{len(v)}｜平均相似度 {sum(有) / len(有):.4f}")
