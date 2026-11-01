# -*- coding: utf-8 -*-
"""M7 阶段 C · 生成层：对 G 组 339 道跑生产链路，落逐题结果（不做判定）。

★ 断点：每 20 道落一次盘，重跑自动跳过已完成（F-103 的教训）。
★ 生产链路 = 生成.回答()（内部已固定 全库池 + 重排 100 + 重排尺度判定）。

用法：python 试跑_M7生成层.py [--限 N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

本文件 = Path(__file__).resolve()
根 = 本文件.parent.parent.parent
sys.path.insert(0, str(本文件.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 生成 as G  # noqa: E402

P = 根 / "05_项目验证证据" / "_M7评测"
题集路径 = P / "评测集_M7.json"
结果路径 = P / "生成层_逐题.json"
用量路径 = P / "生成层_进度.json"

组键 = [
    ("G1_库中完全没有_反题", "反题"), ("G1_库中完全没有_正题", "正题"),
    ("G2a_编号不存在_反题", "反题"), ("G2a_编号不存在_正题", "正题"),
    ("G2b_前提错误_反题", "反题"), ("G2b_前提错误_正题", "正题"),
    ("G3_超出能力_反题", "反题"), ("G3_超出能力_正题", "正题"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--限", type=int, default=0)
    a = ap.parse_args()

    题集 = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    全部 = []
    for 键, 类 in 组键:
        for x in 题集[f"G组_{键}"]:
            全部.append((键, 类, x))
    if a.限:
        全部 = 全部[: a.限]

    已 = {}
    if 结果路径.exists():
        旧 = json.loads(结果路径.read_text(encoding="utf-8"))
        已 = {r["编号"]: r for r in 旧}
        print(f"♻️ 已有 {len(已)} 道结果，跳过")

    t0 = time.time()
    行 = list(已.values())
    for i, (键, 类, x) in enumerate(全部):
        if x["编号"] in 已:
            continue
        try:
            g = G.回答(x["问题"])
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {x['编号']} {type(e).__name__}: {str(e)[:90]}")
            continue
        行.append({
            "编号": x["编号"], "组": 键, "类": 类, "问题": x["问题"],
            "原文片段": x.get("原文片段", ""),
            "判定": g["检索判定"], "闸门分": g.get("闸门分"), "闸门尺度": g.get("闸门尺度"),
            "是否作答": g["是否作答"], "答案": g["答案"], "出处": g["出处"],
            "拒答原因": g.get("拒答原因", ""),
        })
        if (i + 1) % 20 == 0:
            结果路径.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
            用量路径.write_text(json.dumps({"完成": len(行), "总": len(全部),
                                            "时间": time.strftime("%F %T")}, ensure_ascii=False),
                             encoding="utf-8")
            print(f"  💾 {len(行)}/{len(全部)}｜{time.time()-t0:.0f} 秒")

    结果路径.write_text(json.dumps(行, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 完成 {len(行)} 道｜耗时 {time.time()-t0:.0f} 秒｜{结果路径}")
    try:
        import 检索 as R
        print("重排账本：", json.dumps(R.读重排账本(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print("账本读取失败：", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
