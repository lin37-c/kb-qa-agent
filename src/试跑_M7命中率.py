# -*- coding: utf-8 -*-
"""M7 第 1 步 · 检索层命中率（★ 片段判据 ＋ 按题型取 N，2026-10-18 修订）。

★ 口径（`M7_指标口径.md` §二）：
    命中 = 取前 N 的块里，**某一块的文本包含该题的「原文片段」**（只比汉字/字母/数字）。
★ N 的来源：**直接调 `生成.判类型()` ＋ `生成.取前条数()`** —— 与下游一致（对比 8／说明 5／事实 4）。
★ 同时报 Top-4／Top-5／Top-10 四档，便于对照。

用法： python 试跑_M7命中率.py [--冒烟]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
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
输出路径 = 根 / "05_项目验证证据" / "_M7评测" / "命中率_第1步.json"
取前 = 50          # 一次多取，各档在本地切


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


def 跑一题(问题: str) -> list[dict]:
    try:
        r = 检.检索(问题, 取前=取前, 分组=None, 用扩展=True, 自动判房间=True)
    except Exception as e:  # noqa: BLE001
        return [{"_异常": f"{type(e).__name__}: {e}"}]
    return r.get("结果") or []


def _算命中(h: dict, 段们: list[str], 可接受: tuple = ()) -> bool:
    """这一块算不算命中。

    ★ 判据 v2（2026-10-18）：含原文片段 **或** 命中该题的任一「可接受块」。
      为什么加后半句：答案常被切片拆成多块，只认一句会把「答对了」判成「未命中」。
      而偏窄只会假失败、不会假通过 ⇒ 只需在未命中题上补，不会虚高。
    按 来源文件 ＋ 起始行 匹配（起始行在库内唯一标识一块）。
    """
    if all(seg in 净(h.get("文本", "")) for seg in 段们):
        return True
    for a in 可接受:
        if h.get("来源文件") == a.get("来源文件") and int(h.get("起始行", -1)) == int(a.get("起始行", -2)):
            return True
    return False


def 判(命中: list[dict], 片段: str, n: int, 可接受: tuple = ()) -> dict:
    段们 = 分段(片段)
    中 = any(_算命中(h, 段们, 可接受) for h in 命中[:n])
    位 = None
    for i, h in enumerate(命中, 1):
        if _算命中(h, 段们, 可接受):
            位 = i
            break
    return {"中": 中, "位次": 位}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--冒烟", action="store_true")
    a = ap.parse_args()

    d = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    集s = {"覆盖集": d["覆盖集"], "回归集": d["回归集_B_改写配对"]}
    if a.冒烟:
        集s = {k: v[:2] for k, v in 集s.items()}

    t0 = time.time()
    print("=== M7 第 1 步 · 检索层命中率（片段判据 · 按题型取 N）===")
    print(f"  现网口径（第 5 档）｜取前 {取前} 再按题型切｜N 来自 生成.取前条数()")
    print()

    结果 = {"元": {"口径": "第5档", "取前上限": 取前, "生成时间": time.strftime("%Y-%m-%d %H:%M:%S")}}
    题型计 = Counter()

    for 名, 题们 in 集s.items():
        逐 = []
        for x in 题们:
            型 = 生.判类型(x["问题"])
            n = 生.取前条数(型)
            题型计[型] += 1
            命中 = 跑一题(x["问题"])
            if 命中 and "_异常" in 命中[0]:
                逐.append({"编号": x["编号"], "异常": 命中[0]["_异常"]})
                continue
            r = {"编号": x["编号"], "区域": x.get("期望区域", ""), "题型": 型, "N": n}
            可 = tuple(x.get("可接受块") or ())
            r["按题型"] = 判(命中, x["原文片段"], n, 可)["中"]
            r["Top4"] = 判(命中, x["原文片段"], 4, 可)["中"]
            r["Top5"] = 判(命中, x["原文片段"], 5, 可)["中"]
            r["Top10"] = 判(命中, x["原文片段"], 10, 可)["中"]
            r["位次"] = 判(命中, x["原文片段"], 取前, 可)["位次"]
            逐.append(r)
        结果[名] = 逐

        v = [t for t in 逐 if "异常" not in t]
        n = len(v)
        if not n:
            continue
        print(f"【{名}】{n} 道")
        for 键, 标 in (("按题型", "★ 按题型 N（与下游一致）"), ("Top4", "Top-4"), ("Top5", "Top-5"), ("Top10", "Top-10")):
            k = sum(1 for t in v if t[键])
            print(f"  {标:<26}：{k}/{n} = {k / n * 100:.2f}%")
        #   分区（只覆盖集）
        if 名 == "覆盖集":
            for 区 in ("规则", "维护", "技能", "技能目录", "维护工具", "插件"):
                子 = [t for t in v if t["区域"] == 区]
                if 子:
                    k = sum(1 for t in 子 if t["按题型"])
                    print(f"    {区:<6}：{k}/{len(子)} = {k / len(子) * 100:.0f}%")
        未 = [t["编号"] for t in v if not t["按题型"]]
        if 未:
            print(f"    ★ 按题型未命中 {len(未)} 道：{未}")
        print()

    print(f"  题型分布：{dict(题型计)}")
    #   改写影响（用配对原题字段）
    覆 = {t["编号"]: t for t in 结果.get("覆盖集", []) if "异常" not in t}
    配 = [t for t in 结果.get("回归集", []) if "异常" not in t]
    号配 = {x["编号"]: x["配对原题"] for x in d["回归集_B_改写配对"]}
    对 = [(覆[号配[t["编号"]]], t) for t in 配 if 号配.get(t["编号"]) in 覆]
    if 对:
        a1 = sum(1 for x, _ in 对 if x["按题型"])
        a2 = sum(1 for _, y in 对 if y["按题型"])
        print(f"【改写影响】配对 {len(对)} 对｜原题 {a1}｜改写后 {a2}｜★ 影响 {a2 - a1:+d} 道")

    print(f"\n  耗时 {time.time() - t0:.1f} 秒")
    输出路径.write_text(json.dumps(结果, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  明细：{输出路径}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
