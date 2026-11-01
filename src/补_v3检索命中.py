# -*- coding: utf-8 -*-
"""补 v3 检索命中率：124 道（覆盖集 62 ＋ 回归集 62），双口径判定。

判定与 M7 定稿一致：
  严格 —— Top-N 内是否有块含「原文片段」
  含块 —— 再加上该题已裁决的「可接受块」（按内容指纹或 来源文件+起始行）
N 按题型：事实 4 / 说明 5 / 对比 8
"""
import json
import re
import sys
import time
from pathlib import Path

根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
sys.path.insert(0, str(根 / "02_项目源码与工程" / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as R  # noqa: E402

P = 根 / "05_项目验证证据" / "_M7评测"
题 = json.loads((P / "评测集_M7.json").read_text(encoding="utf-8-sig"))
输出 = P / "v3_检索命中.json"


def 净(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")


def 分段(f):
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", f)]
    return [x for x in 段 if len(x) >= 6] or [净(f)]


def 题型N(q):
    对比 = ("区别", "差异", "不同", "对比", "相比", "vs", "VS", "与…的差别", "有什么不一样")
    说明 = ("为什么", "原因", "是怎么", "如何保证", "原理")
    return 8 if any(m in q for m in 对比) else (5 if any(m in q for m in 说明) else 4)


行 = []
t0 = time.time()
for 集 in ("覆盖集", "回归集_B_改写配对"):
    for x in 题[集]:
        Nq = 题型N(x["问题"])
        段们, 可 = 分段(x.get("原文片段", "")), tuple(x.get("可接受块") or ())
        r = R.检索(x["问题"], 取前=Nq, 分组=None, 用扩展=True, 自动判房间=True,
                  用重排=True, 重排池="全库", 重排候选数=100)
        命中 = r["结果"]

        def 中(b):
            if all(s in 净(b.get("文本", "")) for s in 段们):
                return True
            return any((a.get("内容指纹") and b.get("内容指纹") == a["内容指纹"]) or
                       (b.get("来源文件") == a.get("来源文件") and int(b.get("起始行", -1)) == int(a.get("起始行", -2)))
                       for a in 可)

        位段 = next((i for i, b in enumerate(命中, 1) if all(s in 净(b.get("文本", "")) for s in 段们)), None)
        位块 = next((i for i, b in enumerate(命中, 1) if 中(b)), None)
        行.append({"编号": x["编号"], "集": 集, "N": Nq,
                   "严格": bool(位段 and 位段 <= Nq), "严格位": 位段,
                   "含块": bool(位块 and 位块 <= Nq), "含块位": 位块})
        输出.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")

for 集 in ("覆盖集", "回归集_B_改写配对"):
    子 = [r for r in 行 if r["集"] == 集]
    n = len(子)
    a = sum(1 for r in 子 if r["严格"])
    b = sum(1 for r in 子 if r["含块"])
    print(f"{集}：{n} 道｜严格 {a} = {a/n*100:.2f}%｜含块 {b} = {b/n*100:.2f}%")
print(f"\n耗时 {time.time()-t0:.0f} 秒")
try:
    print("重排账本：", json.dumps(R.读重排账本(), ensure_ascii=False))
except Exception as e:  # noqa: BLE001
    print(e)
