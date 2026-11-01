# -*- coding: utf-8 -*-
"""回归集 80 道：跑生产链路（v5 配置），落逐题结果。

三组判法不同（见输出后的判定脚本）：
  A 语义改写 12 —— 无金标准片段，按「金标准出处」是否被引用判
  B 陷阱     6 —— 按是否拒答判
  B 改写配对 62 —— 有原文片段，按片段覆盖判（并用人工抽样核）
"""
import json
import sys
import time
from pathlib import Path

根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
sys.path.insert(0, str(根 / "02_项目源码与工程" / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 生成 as G  # noqa: E402

P = 根 / "05_项目验证证据" / "_M7评测"
题 = json.loads((P / "评测集_M7.json").read_text(encoding="utf-8-sig"))
输出 = P / "回归集_生成_v5.json"

组 = [("A_语义改写", "回归集_A_语义改写"), ("B_陷阱", "回归集_B_陷阱"), ("B_改写配对", "回归集_B_改写配对")]
题们 = [(x["编号"], x, 名) for 名, k in 组 for x in 题[k]]

已 = {}
if 输出.exists():
    已 = {r["编号"]: r for r in json.loads(输出.read_text(encoding="utf-8"))}
print(f"共 {len(题们)} 道（已有 {len(已)}）", flush=True)

行 = list(已.values())
t0 = time.time()
for i, (号, x, 名) in enumerate(题们):
    if 号 in 已:
        continue
    try:
        g = G.回答(x["问题"])
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {号} {str(e)[:70]}", flush=True)
        continue
    行.append({"编号": 号, "组": 名, "问题": x["问题"],
               "原文片段": x.get("原文片段", ""), "可接受块": x.get("可接受块") or [],
               "期望行为": x.get("期望行为", ""), "金标准出处": x.get("金标准出处", ""),
               "期望来源前缀": x.get("期望来源前缀", ""),
               "判定": g["检索判定"], "闸门分": g.get("闸门分"), "是否作答": g["是否作答"],
               "答案": g["答案"], "出处": g["出处"], "拒答原因": g.get("拒答原因", "")})
    if (i + 1) % 20 == 0:
        输出.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  💾 {len(行)}/{len(题们)}｜{time.time()-t0:.0f} 秒", flush=True)

输出.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"✅ {len(行)} 道｜{time.time()-t0:.0f} 秒")
