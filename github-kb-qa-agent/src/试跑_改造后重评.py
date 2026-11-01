# -*- coding: utf-8 -*-
"""降幻觉改造后重评：G 组 169 反题 ＋ 覆盖集 62 道。

输出：生成层_逐题_v2.json / 覆盖集_生成_v2.json（**不覆盖改造前的数据**）
断点：每 20 道落盘。
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

任务 = [
    ("G组", ["G1_库中完全没有", "G2a_编号不存在", "G2b_前提错误", "G3_超出能力"],
     P / "生成层_逐题_v2.json"),
    ("覆盖集", ["覆盖集"], P / "覆盖集_生成_v2.json"),
]


def 跑(键前缀, 输出路径, 限=0):
    if 键前缀 == "覆盖集":
        题们 = [(x["编号"], x, "正题") for x in 题["覆盖集"]]
    else:
        题们 = []
        for k, v in 题.items():
            if k.startswith("G组_"):
                for x in v:
                    题们.append((x["编号"], x, "反题" if "反题" in k else "正题"))
    if 限:
        题们 = 题们[:限]
    已 = {}
    if 输出路径.exists():
        已 = {r["编号"]: r for r in json.loads(输出路径.read_text(encoding="utf-8"))}
    print(f"\n=== {键前缀}：{len(题们)} 道（已有 {len(已)}）===")
    行 = list(已.values())
    t0 = time.time()
    for i, (号, x, 类) in enumerate(题们):
        if 号 in 已:
            continue
        try:
            g = G.回答(x["问题"])
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {号} {str(e)[:70]}")
            continue
        行.append({"编号": 号, "类": 类, "问题": x["问题"],
                   "原文片段": x.get("原文片段", ""), "可接受块": x.get("可接受块") or [],
                   "判定": g["检索判定"], "闸门分": g.get("闸门分"), "是否作答": g["是否作答"],
                   "答案": g["答案"], "出处": g["出处"], "拒答原因": g.get("拒答原因", "")})
        if (i + 1) % 20 == 0:
            输出路径.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  💾 {len(行)}/{len(题们)}｜{time.time()-t0:.0f} 秒")
    输出路径.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {键前缀} 完成 {len(行)} 道｜{time.time()-t0:.0f} 秒")


for 前缀, _, 路径 in 任务:
    跑(前缀, 路径)
try:
    import 检索 as R
    print("\n重排账本：", json.dumps(R.读重排账本(), ensure_ascii=False))
except Exception as e:  # noqa: BLE001
    print(e)
