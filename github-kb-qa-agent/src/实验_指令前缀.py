# -*- coding: utf-8 -*-
"""instruction 前缀实验：对当前检索失败的题，比较「裸查询」 vs 「加 instruction」的金块向量排名。

只算向量阶段（不调重排）：看金块能不能进 top-100 —— 进不去，重排再强也救不回。
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
sys.path.insert(0, str(根 / "02_项目源码与工程" / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as R
import 入库 as K
import 向量化
import 配置
from 缓存 import 归一化

P = 根 / "05_项目验证证据" / "_M7评测"
题 = json.loads((P / "评测集_M7.json").read_text(encoding="utf-8-sig"))
命中 = json.loads((P / "v3_检索命中.json").read_text(encoding="utf-8"))

任务 = "给定一个中文查询，检索能回答该查询的文档段落"
前缀 = f"Instruct: {任务}\nQuery: "

m, 元 = K.载入向量库()
权重 = np.array([R.有效权重(d["来源文件"], d.get("文本", "")) for d in 元])


def 净(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")


# 取严格未命中的题（覆盖集 + 回归集）
坏 = [h for h in 命中 if not h["严格"]]
选 = []
for h in 坏:
    集 = h["集"]
    x = next((y for y in 题[集] if y["编号"] == h["编号"]), None)
    if x:
        选.append(x)
选 = 选[:20]
print(f"拿 {len(选)} 道当前「严格未命中」的题做对比\n")


def 排名(问题, 用前缀):
    查询文本, _ = R.扩展查询(问题.strip())
    if 用前缀:
        查询文本 = 前缀 + 查询文本
    qv = 归一化(向量化.向量化单条(查询文本, 场景="指令实验"))
    分 = (m @ qv) * 权重
    序 = np.argsort(-分)
    return 序


统计 = {"裸查询进100": 0, "加指令进100": 0, "改善": 0, "变差": 0}
for x in 选:
    段们 = [净(t) for t in re.split(r"[；;／/]|…+|——|。", x.get("原文片段", "")) if len(净(t)) >= 6] or [净(x.get("原文片段", ""))]
    结果 = {}
    for 名, 用 in (("裸", False), ("指令", True)):
        序 = 排名(x["问题"], 用)
        位 = next((i + 1 for i, gi in enumerate(序) if all(s in 净(元[int(gi)]["文本"]) for s in 段们)), None)
        结果[名] = 位
    a, b = 结果["裸"], 结果["指令"]
    if a and a <= 100:
        统计["裸查询进100"] += 1
    if b and b <= 100:
        统计["加指令进100"] += 1
    if a and b:
        if b < a:
            统计["改善"] += 1
        elif b > a:
            统计["变差"] += 1
    print(f"  {x['编号']:<8} 裸 {str(a):>5} → 指令 {str(b):>5}   {x['问题'][:34]}")

n = len(选)
print(f"\n金块进 top-100：裸查询 {统计['裸查询进100']}/{n}｜加指令 {统计['加指令进100']}/{n}")
print(f"排名改善 {统计['改善']}｜变差 {统计['变差']}｜其余无变化或找不到")
