# -*- coding: utf-8 -*-
"""实验：查询改写 ＋ 双查询并集（不改生产代码）。

做法（每题）：
  ① 原问题 → 向量 top-100
  ② qwen-flash 把问题改写成"检索式查询" → 向量 top-100
  ③ 两路按块取「分数最大值」合并 → 取前 100 → 交给 qwen3-rerank
  ④ 与基线同口径判命中（严格／含块）

★ 断点：每题后落盘，重跑跳过。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests

根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
sys.path.insert(0, str(根 / "02_项目源码与工程" / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as R          # noqa: E402
import 向量化              # noqa: E402
import 配置                # noqa: E402
import 入库 as K           # noqa: E402
from 缓存 import 归一化     # noqa: E402

P = 根 / "05_项目验证证据" / "_M7评测"
输出 = P / "查询改写_检索命中.json"
题 = json.loads((P / "评测集_M7.json").read_text(encoding="utf-8-sig"))
改写模型 = "qwen-flash"
改写地址 = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

改写系统 = """你是检索查询改写器。把用户的口语问题改写成**适合在技术文档库里检索的查询**。
要求：
1. 保留原问题里的关键词；
2. 补充这类问题在技术文档里可能用的术语（例如"落地"→"实施 配置 执行步骤"）；
3. 只输出一行查询词，不要解释、不要标点装饰；
4. 若原问题已经很具体，原样返回即可。"""


def 净(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")


def 分段(f):
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", f)]
    return [x for x in 段 if len(x) >= 6] or [净(f)]


def 题型N(q):
    对比 = ("区别", "差异", "不同", "对比", "相比", "vs", "VS", "与…的差别", "有什么不一样")
    说明 = ("为什么", "原因", "是怎么", "如何保证", "原理")
    return 8 if any(m in q for m in 对比) else (5 if any(m in q for m in 说明) else 4)


def 改写(问题, key):
    try:
        r = requests.post(改写地址,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": 改写模型,
                                "messages": [{"role": "system", "content": 改写系统},
                                             {"role": "user", "content": 问题}],
                                "max_tokens": 80, "temperature": 0.2},
                          timeout=30)
        if r.status_code != 200:
            return "", f"HTTP {r.status_code}"
        文 = (r.json()["choices"][0]["message"]["content"] or "").strip().splitlines()
        出 = 文[0].strip() if 文 else ""
        if not 出 or len(出) > 80 or 出 == 问题:
            return "", "改写为空/过长/无变化"
        return 出, ""
    except Exception as e:  # noqa: BLE001
        return "", f"{type(e).__name__}: {str(e)[:40]}"


key = os.environ.get("QWEN_KEY", "") or 向量化.取密钥()
m, 元 = K.载入向量库()
m = m / np.linalg.norm(m, axis=1, keepdims=True)
权重 = np.array([R.有效权重(d["来源文件"], d.get("文本", "")) for d in 元])

题们 = [(集, x) for 集 in ("覆盖集", "回归集_B_改写配对") for x in 题[集]]
已 = {}
if 输出.exists():
    已 = {r["编号"]: r for r in json.loads(输出.read_text(encoding="utf-8"))}
print(f"共 {len(题们)} 道（已有 {len(已)}）", flush=True)

行 = list(已.values())
t0 = time.time()
n改 = 0
for i, (集, x) in enumerate(题们):
    if x["编号"] in 已:
        continue
    Nq = 题型N(x["问题"])
    段们, 可 = 分段(x.get("原文片段", "")), tuple(x.get("可接受块") or ())

    查询文本, _ = R.扩展查询(x["问题"].strip())
    qv = 归一化(向量化.向量化单条(查询文本, 场景="改写实验-原"))
    分1 = (m @ qv) * 权重

    改, 错 = 改写(x["问题"], key)
    分2 = None
    if 改:
        n改 += 1
        qv2 = 归一化(向量化.向量化单条(改, 场景="改写实验-改"))
        分2 = (m @ qv2) * 权重
    分 = 分1 if 分2 is None else np.maximum(分1, 分2)

    序 = np.argsort(-分)[:100]
    候选 = []
    for gi in 序:
        d = dict(元[int(gi)])
        d["相似度"] = round(float(分[int(gi)]), 4)
        候选.append(d)
    try:
        命中, _ = R.重排(x["问题"].strip(), 候选, 取前=len(候选), 场景="改写实验-重排")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {x['编号']} {str(e)[:60]}", flush=True)
        continue

    def 中(b):
        if all(s in 净(b.get("文本", "")) for s in 段们):
            return True
        return any((a.get("内容指纹") and b.get("内容指纹") == a["内容指纹"]) or
                   (b.get("来源文件") == a.get("来源文件") and int(b.get("起始行", -1)) == int(a.get("起始行", -2)))
                   for a in 可)

    位段 = next((j for j, b in enumerate(命中, 1) if all(s in 净(b.get("文本", "")) for s in 段们)), None)
    位块 = next((j for j, b in enumerate(命中, 1) if 中(b)), None)
    行.append({"编号": x["编号"], "集": 集, "N": Nq, "改写": 改, "改写失败": 错,
               "严格": bool(位段 and 位段 <= Nq), "含块": bool(位块 and 位块 <= Nq)})
    输出.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(行) % 20 == 0:
        print(f"  💾 {len(行)}/{len(题们)}｜已改写 {n改}｜{time.time()-t0:.0f} 秒", flush=True)

for 集 in ("覆盖集", "回归集_B_改写配对"):
    子 = [r for r in 行 if r["集"] == 集]
    n = len(子)
    a = sum(1 for r in 子 if r["严格"])
    b = sum(1 for r in 子 if r["含块"])
    print(f"{集}：{n} 道｜严格 {a} = {a/max(n,1)*100:.2f}%｜含块 {b} = {b/max(n,1)*100:.2f}%")
print(f"\n成功改写 {n改}/{len(行)}｜耗时 {time.time()-t0:.0f} 秒")
