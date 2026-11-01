# -*- coding: utf-8 -*-
"""M7 · 判据 v2 重判（2026-10-18）。

一次跑完三套配置，并把**每个结果的块身份**（来源文件＋起始行＋内容指纹）存下来，
然后用**两把尺子**对同一批结果各判一次：

    旧判据 = 含该题「原文片段」
    新判据 = 含「原文片段」**或**命中该题「可接受块」

为什么要一次跑、两把尺子：
  1. 旧判据必须能复现原数（28／27／32／34／41／40）—— 复现不出就说明有别的东西变了；
  2. 两把尺子量的是**同一批检索结果**，差异只来自判据，不来自运气。

用法：
    python 试跑_M7重判.py
    python 试跑_M7重判.py --冒烟
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
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

题集路径 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
旧结果路径 = 根 / "05_项目验证证据" / "_M7评测" / "重排对照_第1步.json"
明细路径 = 根 / "05_项目验证证据" / "_M7评测" / "重判_明细.json"
结果路径 = 根 / "05_项目验证证据" / "_M7评测" / "重判_结果.json"
取前 = 50

配置们 = [
    ("基线", {"用重排": False}),
    ("②房间内+重排", {"用重排": True, "重排池": "分组"}),
    ("③全库+重排", {"用重排": True, "重排池": "全库"}),
]


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


def _算命中(块: dict, 段们: list[str], 可接受: tuple) -> bool:
    if all(seg in 块["_净"] for seg in 段们):
        return True
    for a in 可接受:
        if 块["来源文件"] == a.get("来源文件") and int(块["起始行"]) == int(a.get("起始行", -2)):
            return True
    return False


def 判(块们: list[dict], 片段: str, n: int, 可接受: tuple) -> dict:
    段们 = 分段(片段)
    中 = any(_算命中(b, 段们, 可接受) for b in 块们[:n])
    位 = None
    for i, b in enumerate(块们, 1):
        if _算命中(b, 段们, 可接受):
            位 = i
            break
    return {"中": 中, "位次": 位}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--冒烟", action="store_true")
    a = ap.parse_args()

    题集 = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    集s = {"覆盖集": 题集["覆盖集"], "回归集": 题集["回归集_B_改写配对"]}
    if a.冒烟:
        集s = {k: v[:2] for k, v in 集s.items()}

    旧记 = json.loads(旧结果路径.read_text(encoding="utf-8-sig")) if 旧结果路径.exists() else {}

    t0 = time.time()
    print("=== M7 · 判据 v2 重判（三套配置 × 两把尺子）===")
    print(f"  一次召回 {取前} 条；旧判据／新判据量的是同一批结果\n")

    明细: dict = {"元": {"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "取前上限": 取前,
                       "重排模型": "rerank (raw scores)"},
                  "配置": [c[0] for c in 配置们], "题": {}}
    汇总: dict = {"元": 明细["元"], "配置": {}}

    for 配名, 参 in 配置们:
        print(f"───── 配置 {配名} ─────")
        该配 = {}
        tokens = 0
        for 集, 题们 in 集s.items():
            逐旧, 逐新 = [], []
            for x in 题们:
                型 = 生.判类型(x["问题"])
                n = 生.取前条数(型)
                可 = tuple(x.get("可接受块") or ())
                try:
                    r = 检.检索(x["问题"], 取前=取前, 分组=None, 用扩展=True, 自动判房间=True, **参)
                    命中 = r.get("结果") or []
                except Exception as e:  # noqa: BLE001
                    print(f"  ❌ {x['编号']} {type(e).__name__}: {e}")
                    continue
                tokens += (r.get("重排用量") or {}).get("tokens", 0)
                块们 = [{"来源文件": h["来源文件"], "起始行": h["起始行"], "结束行": h.get("结束行"),
                        "内容指纹": h.get("内容指纹", ""), "相似度": h.get("相似度"),
                        "重排前位次": h.get("重排前位次"), "重排分": h.get("重排分"),
                        "_净": 净(h.get("文本", ""))} for h in 命中]
                旧 = 判(块们, x["原文片段"], n, ())
                新 = 判(块们, x["原文片段"], n, 可)
                逐旧.append({"编号": x["编号"], "N": n, **旧})
                逐新.append({"编号": x["编号"], "N": n, **新})
                明细["题"].setdefault(x["编号"], {})[配名] = {
                    "集": 集, "分组": r.get("分组"), "候选池": r.get("候选池"),
                    "块": [{k: v for k, v in b.items() if k != "_净"} for b in 块们]}
            n2 = len(逐旧)
            旧中 = sum(1 for t in 逐旧 if t["中"])
            新中 = sum(1 for t in 逐新 if t["中"])
            该配[集] = {"旧": 逐旧, "新": 逐新}
            print(f"  【{集}】{n2} 道")
            print(f"    旧判据：{旧中}/{n2} = {旧中 / n2 * 100:.2f}%")
            print(f"    新判据：{新中}/{n2} = {新中 / n2 * 100:.2f}%")
            翻 = [t["编号"] for t in 逐新 if t["中"] and not next(u for u in 逐旧 if u["编号"] == t["编号"])["中"]]
            掉 = [t["编号"] for t in 逐旧 if t["中"] and not next(u for u in 逐新 if u["编号"] == t["编号"])["中"]]
            if 翻:
                print(f"    ★ 旧判未中、新判命中：{翻}")
            if 掉:
                print(f"    ⚠️ 旧判命中、新判未中（不应发生）：{掉}")
        print(f"  重排 token：{tokens:,}\n")
        汇总["配置"][配名] = 该配

    # 与上次记录对账（旧判据）
    print("=== 旧判据复现核对（与上一轮记录对账）===")
    应 = {"基线": {"覆盖集": 28, "回归集": 27}, "②房间内+重排": {"覆盖集": 32, "回归集": 34},
         "③全库+重排": {"覆盖集": 41, "回归集": 40}}
    for 配名, 参 in 配置们:
        for 集 in ("覆盖集", "回归集"):
            v = 汇总["配置"].get(配名, {}).get(集, {}).get("旧", [])
            if not v:
                continue
            k = sum(1 for t in v if t["中"])
            w = 应.get(配名, {}).get(集)
            print(f"  {配名:<12}【{集}】本次 {k}/{len(v)}　记录 {w}　{'✅ 一致' if k == w else '❌ 不一致'}")

    print(f"\n  总耗时 {time.time() - t0:.1f} 秒")
    try:
        print(f"  重排账本：{json.dumps(检.读重排账本(), ensure_ascii=False)}")
    except Exception as e:  # noqa: BLE001
        print(f"  重排账本读取失败：{e}")

    明细路径.write_text(json.dumps(明细, ensure_ascii=False), encoding="utf-8")
    结果路径.write_text(json.dumps(汇总, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  明细：{明细路径}")
    print(f"  结果：{结果路径}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
