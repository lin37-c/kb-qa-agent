# -*- coding: utf-8 -*-
"""用「含标题路径」的新库做检索命中评测（124 道），与现用库同口径对比。

★ 不动生产配置：直接读新库矩阵 + 切片元数据，自己算向量分，再调 `检索.重排`。
★ 断点：每道题后落盘，重跑自动跳过。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
sys.path.insert(0, str(根 / "02_项目源码与工程" / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as R          # noqa: E402
import 向量化              # noqa: E402
import 配置                # noqa: E402
from 缓存 import 归一化     # noqa: E402

P = 根 / "05_项目验证证据" / "_M7评测"
新库 = 根 / "data" / "向量库_v4_2048_t"
输出 = P / "含标题_检索命中.json"
题 = json.loads((P / "评测集_M7.json").read_text(encoding="utf-8-sig"))


def 净(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")


def 分段(f):
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", f)]
    return [x for x in 段 if len(x) >= 6] or [净(f)]


def 题型N(q):
    对比 = ("区别", "差异", "不同", "对比", "相比", "vs", "VS", "与…的差别", "有什么不一样")
    说明 = ("为什么", "原因", "是怎么", "如何保证", "原理")
    return 8 if any(m in q for m in 对比) else (5 if any(m in q for m in 说明) else 4)


m = np.load(新库 / "向量.npy").astype(np.float32)
m = m / np.linalg.norm(m, axis=1, keepdims=True)
元 = [json.loads(l) for l in (新库 / "元数据.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
assert len(元) == m.shape[0], f"元数据 {len(元)} 与矩阵 {m.shape[0]} 不一致"
权重 = np.array([R.有效权重(d["来源文件"], d.get("文本", "")) for d in 元])
print(f"新库 {m.shape}｜块 {len(元)}")

题们 = [(集, x) for 集 in ("覆盖集", "回归集_B_改写配对") for x in 题[集]]
已 = {}
if 输出.exists():
    已 = {r["编号"]: r for r in json.loads(输出.read_text(encoding="utf-8"))}
print(f"共 {len(题们)} 道（已有 {len(已)}）", flush=True)

行 = list(已.values())
t0 = time.time()
for i, (集, x) in enumerate(题们):
    if x["编号"] in 已:
        continue
    Nq = 题型N(x["问题"])
    段们, 可 = 分段(x.get("原文片段", "")), tuple(x.get("可接受块") or ())
    查询文本, _ = R.扩展查询(x["问题"].strip())
    qv = 归一化(向量化.向量化单条(查询文本, 场景="含标题检索"))
    分 = (m @ qv) * 权重
    序 = np.argsort(-分)[:100]
    候选 = []
    for gi in 序:
        d = dict(元[int(gi)])
        d["相似度"] = round(float(分[int(gi)]), 4)
        候选.append(d)
    try:
        命中, 用量 = R.重排(x["问题"].strip(), 候选, 取前=len(候选), 场景="含标题重排")
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
    行.append({"编号": x["编号"], "集": 集, "N": Nq,
               "严格": bool(位段 and 位段 <= Nq), "严格位": 位段,
               "含块": bool(位块 and 位块 <= Nq), "含块位": 位块,
               "闸门分": round(max(float(b.get("重排分", 0)) for b in 命中), 4) if 命中 else 0.0})
    输出.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
    if (len(行)) % 20 == 0:
        print(f"  💾 {len(行)}/{len(题们)}｜{time.time()-t0:.0f} 秒", flush=True)

for 集 in ("覆盖集", "回归集_B_改写配对"):
    子 = [r for r in 行 if r["集"] == 集]
    n = len(子)
    a = sum(1 for r in 子 if r["严格"])
    b = sum(1 for r in 子 if r["含块"])
    print(f"{集}：{n} 道｜严格 {a} = {a/max(n,1)*100:.2f}%｜含块 {b} = {b/max(n,1)*100:.2f}%")
print(f"\n耗时 {time.time()-t0:.0f} 秒｜结果 → {输出}")
