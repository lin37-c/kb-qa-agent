# -*- coding: utf-8 -*-
"""换 qwen3-rerank 后重标阈值：232 正 / 79 负，同一套方法。

操作点规则沿用：**误拒上限 10%**（在这个约束下尽量挡负样本）。
负样本随机拆 40 标定 / 39 留出复核。
"""
import json
import random
import sys
from pathlib import Path

import numpy as np

根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
sys.path.insert(0, str(根 / "02_项目源码与工程" / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as R  # noqa: E402

P = 根 / "05_项目验证证据" / "_M7评测"
题 = json.loads((P / "评测集_M7.json").read_text(encoding="utf-8-sig"))
输出 = P / "阈值标定_qwen.json"

组 = [("正·覆盖集", 题["覆盖集"]),
     ("正·G1正题", 题["G组_G1_库中完全没有_正题"]),
     ("正·G2a正题", 题["G组_G2a_编号不存在_正题"]),
     ("正·G2b正题", 题["G组_G2b_前提错误_正题"]),
     ("正·G3正题", 题["G组_G3_超出能力_正题"]),
     ("负·G1反题", 题["G组_G1_库中完全没有_反题"]),
     ("负·G2a反题", 题["G组_G2a_编号不存在_反题"])]

分: dict = {}
for 名, 题们 in 组:
    v = []
    for x in 题们:
        try:
            r = R.检索(x["问题"], 取前=4, 分组=None, 用扩展=True, 自动判房间=True,
                      用重排=True, 重排池="全库", 重排候选数=100)
            v.append(float(r["闸门分"]))
        except Exception as e:  # noqa: BLE001
            print("跳过", x.get("编号"), str(e)[:60])
    分[名] = v
    print(f"{名:<12} n={len(v):>3}｜最低 {min(v):.4f}｜中位 {np.median(v):.4f}｜最高 {max(v):.4f}")

正 = np.array([x for k in 分 if k.startswith("正") for x in 分[k]])
负 = np.array([x for k in 分 if k.startswith("负") for x in 分[k]])
print(f"\n合计：正 {len(正)}｜负 {len(负)}")

random.seed(20261024)
idx = list(range(len(负)))
random.shuffle(idx)
负标, 负复 = 负[idx[:40]], 负[idx[40:]]

print("\n=== 按「误拒上限」定阈值 ===")
for 上限 in (0.05, 0.10, 0.15):
    t = float(np.percentile(正, 上限 * 100))
    print(f"  误拒 ≤{上限*100:>2.0f}% → 阈值 {t:.4f}｜应答过线 {(正>=t).mean()*100:5.1f}%"
          f"｜标定负被挡 {(负标<t).mean()*100:5.1f}%｜★复核负被挡 {(负复<t).mean()*100:5.1f}%")

最优 = None
for t in np.linspace(float(min(正.min(), 负.min())), float(max(正.max(), 负.max())), 600):
    b = ((正 >= t).mean() + (负标 < t).mean()) / 2
    if 最优 is None or b > 最优[1]:
        最优 = (float(t), float(b))
print(f"\n平衡最优：阈值 {最优[0]:.4f}｜平衡 {最优[1]*100:.1f}%"
      f"｜应答过线 {(正>=最优[0]).mean()*100:.1f}%｜复核负被挡 {(负复<最优[0]).mean()*100:.1f}%")

输出.write_text(json.dumps({"分组": {k: [round(float(x), 6) for x in v] for k, v in 分.items()},
                           "正": [round(float(x), 6) for x in 正],
                           "负40": [round(float(x), 6) for x in 负标],
                           "负39": [round(float(x), 6) for x in 负复]},
                          ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n分数存档 → {输出}")
