# -*- coding: utf-8 -*-
"""M7 阶段 A · rerank 对照实验（2026-10-18，未决 U-52）。

跑两种配置，与**已出的基线**（`命中率_第1步.json`，45.16%/43.55%）对比：

    ② 房间内 top-50 + 重排   —— 接手卡 A3 的原方案（改动最小）
    ③ 全库   top-50 + 重排   —— 候选池不按房间过滤（M7 实测上限高 19 个百分点）

★ 为什么两桶都跑：只跑②，涨了也分不清是「重排的功劳」还是「换池子的功劳」；
  两桶一起跑，判据才成立（涨 ≥5 道才留）。

★ 判据与 `试跑_M7命中率.py` **逐字一致**：命中 = 取前 N 中某块**文本包含该题的原文片段**
  （只比汉字/字母/数字）；N 来自 `生成.取前条数()`（对比 8／说明 5／事实 4）。

用法：
    python 试跑_重排.py              # 全量 124 道
    python 试跑_重排.py --冒烟        # 每集前 2 道，只验通路
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
基线路径 = 根 / "05_项目验证证据" / "_M7评测" / "命中率_第1步.json"
输出路径 = 根 / "05_项目验证证据" / "_M7评测" / "重排对照_第1步.json"
取前 = 50

配置们 = [
    ("②房间内+重排", {"用重排": True, "重排池": "分组"}),
    ("③全库+重排", {"用重排": True, "重排池": "全库"}),
]


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


def _算命中(h: dict, 段们: list[str], 可接受: tuple = ()) -> bool:
    """这一块算不算命中：含原文片段 **或** 命中该题任一「可接受块」（判据 v2，2026-10-18）。"""
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


def 跑一题(问题: str, 参: dict) -> tuple[list[dict], dict]:
    try:
        r = 检.检索(问题, 取前=取前, 分组=None, 用扩展=True, 自动判房间=True, **参)
    except Exception as e:  # noqa: BLE001
        return [{"_异常": f"{type(e).__name__}: {e}"}], {}
    return (r.get("结果") or []), r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--冒烟", action="store_true")
    ap.add_argument("--题数", type=int, default=0, help="每集只跑前 N 道（0=全量）")
    a = ap.parse_args()

    d = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    集s = {"覆盖集": d["覆盖集"], "回归集": d["回归集_B_改写配对"]}
    if a.冒烟:
        集s = {k: v[:2] for k, v in 集s.items()}
    elif a.题数:
        集s = {k: v[: a.题数] for k, v in 集s.items()}

    基线 = json.loads(基线路径.read_text(encoding="utf-8-sig")) if 基线路径.exists() else {}
    基线键 = {"覆盖集": "覆盖集", "回归集": "回归集"}
    基线率 = {}
    for 名, 键 in 基线键.items():
        v = [x for x in 基线.get(键, []) if "异常" not in x]
        if v:
            基线率[名] = sum(1 for x in v if x["按题型"]) / len(v)

    t0 = time.time()
    print("=== M7 阶段 A · rerank 对照（②房间内 vs ③全库）===")
    print(f"  口径：按题型 N（对比 8／说明 5／事实 4）｜一次召回 {取前} 条｜重排用智谱 `rerank`（raw scores）")
    print()

    输出 = {"元": {"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "取前上限": 取前,
                 "重排模型": "rerank", "配置": [x[0] for x in 配置们]}}

    for 名, 参 in 配置们:
        print(f"───── 配置 {名} ─────")
        该配 = {}
        for 集, 题们 in 集s.items():
            逐 = []
            该tokens = 0
            for x in 题们:
                型 = 生.判类型(x["问题"])
                n = 生.取前条数(型)
                命中, r = 跑一题(x["问题"], 参)
                if 命中 and "_异常" in 命中[0]:
                    逐.append({"编号": x["编号"], "异常": 命中[0]["_异常"]})
                    continue
                该tokens += (r.get("重排用量") or {}).get("tokens", 0)
                rr = {"编号": x["编号"], "区域": x.get("期望区域", ""), "题型": 型, "N": n,
                      "分组": r.get("分组", ""), "重排前位次": (r.get("结果") or [{}])[0].get("重排前位次")}
                可 = tuple(x.get("可接受块") or ())
                for 档, k in (("按题型", n), ("Top4", 4), ("Top5", 5), ("Top10", 10)):
                    rr[档] = 判(命中, x["原文片段"], k, 可)["中"]
                rr["位次"] = 判(命中, x["原文片段"], 取前, 可)["位次"]
                逐.append(rr)
            该配[集] = 逐

            v = [t for t in 逐 if "异常" not in t]
            n2 = len(v)
            if not n2:
                continue
            print(f"  【{集}】{n2} 道 ｜ 重排 token {该tokens:,}")
            for 档, 标 in (("按题型", "★ 按题型 N"), ("Top4", "Top-4"), ("Top5", "Top-5"), ("Top10", "Top-10")):
                k = sum(1 for t in v if t[档])
                基 = 基线率.get(集)
                差 = ""
                if 档 == "按题型" and 基 is not None:
                    差 = f"　基线 {基 * 100:.2f}%　★ 变化 {(k / n2 - 基) * 100:+.2f} 个百分点"
                print(f"    {标:<12}：{k}/{n2} = {k / n2 * 100:.2f}%{差}")
            未 = [t["编号"] for t in v if not t["按题型"]]
            print(f"    未命中 {len(未)} 道：{未}")
            print()
        输出[名] = 该配

    print(f"  总耗时 {time.time() - t0:.1f} 秒")
    try:
        print(f"  重排账本：{json.dumps(检.读重排账本(), ensure_ascii=False)}")
    except Exception as e:  # noqa: BLE001
        print(f"  重排账本读取失败：{e}")
    输出路径.write_text(json.dumps(输出, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  明细：{输出路径}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
