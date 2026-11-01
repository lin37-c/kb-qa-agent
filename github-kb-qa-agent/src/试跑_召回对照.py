# -*- coding: utf-8 -*-
"""M7 召回改造 R1 · 三臂对照（2026-10-22）。

只改一个参数：候选池大小（50 / 100 / 128）。**不改生产代码**。
判据：每臂都按「严格口径」与「含可接受块」各判一次；看**净变化**（新增−丢失）。

用法：
    python 试跑_召回对照.py --冒烟      # 每臂 1 道，先验通路（尤其验 128 条会不会被接口拒）
    python 试跑_召回对照.py              # 全量 124 道
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

题集路径 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
输出路径 = 根 / "05_项目验证证据" / "_M7评测" / "召回三臂_结果.json"
明细路径 = 根 / "05_项目验证证据" / "_M7评测" / "召回三臂_明细.json"

臂 = [50, 100, 128]
存前 = 20          # 每臂每题存前 20 条块身份（够判四档与归因）


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(片段: str) -> list[str]:
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", 片段)]
    return [x for x in 段 if len(x) >= 6] or [净(片段)]


def 题型N(q: str) -> int:
    对比 = ("区别", "差异", "不同", "对比", "相比", "vs", "VS", "与…的差别", "有什么不一样")
    说明 = ("为什么", "原因", "是怎么", "如何保证", "原理")
    return 8 if any(m in q for m in 对比) else (5 if any(m in q for m in 说明) else 4)


def 判(块们: list[dict], 段们: list[str], n: int, 可: tuple) -> dict:
    def 中(b):
        if all(s in 净(b.get("文本", "")) for s in 段们):
            return True
        return any((a.get("内容指纹") and b.get("内容指纹") == a["内容指纹"]) or
                   (b.get("来源文件") == a.get("来源文件") and int(b.get("起始行", -1)) == int(a.get("起始行", -2)))
                   for a in 可)
    命中 = any(中(b) for b in 块们[:n])
    位 = next((i for i, b in enumerate(块们, 1) if 中(b)), None)
    return {"中": 命中, "位次": 位}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--冒烟", action="store_true")
    a = ap.parse_args()

    题集 = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    集s = {"覆盖集": 题集["覆盖集"], "回归集": 题集["回归集_B_改写配对"]}
    if a.冒烟:
        集s = {k: v[:1] for k, v in 集s.items()}

    t0 = time.time()
    print("=== M7 召回改造 R1 · 三臂对照（只改候选池大小）===")
    print(f"  臂：{臂}　｜ 每题存前 {存前} 条块身份\n")

    明细: dict = {"元": {"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "臂": 臂}, "题": {}}
    汇总: dict = {"元": 明细["元"], "臂": {}}

    for 候选数 in 臂:
        print(f"───── 臂：候选池 {候选数} ─────")
        该臂 = {}
        tokens = 0
        for 集, 题们 in 集s.items():
            逐 = []
            for x in 题们:
                N = 题型N(x["问题"])
                段们 = 分段(x["原文片段"])
                可 = tuple(x.get("可接受块") or ())
                t1 = time.time()
                try:
                    r = 检.检索(x["问题"], 取前=候选数, 分组=None, 用扩展=True, 自动判房间=True,
                              用重排=True, 重排池="全库", 重排候选数=候选数)
                except Exception as e:  # noqa: BLE001
                    print(f"  ❌ {x['编号']} {type(e).__name__}: {e}")
                    continue
                耗 = time.time() - t1
                tokens += (r.get("重排用量") or {}).get("tokens", 0)
                命中 = r.get("结果") or []
                新 = 判(命中, 段们, N, 可)
                旧 = 判(命中, 段们, N, ())
                逐.append({"编号": x["编号"], "N": N,
                           "严格": 旧["中"], "严格位次": 旧["位次"],
                           "含块": 新["中"], "含块位次": 新["位次"],
                           "Top10": 判(命中, 段们, 10, 可)["中"],
                           "耗时": round(耗, 2)})
                明细["题"].setdefault(x["编号"], {})[str(候选数)] = {
                    "集": 集, "分组": r.get("分组"), "候选池": r.get("候选池"),
                    "块": [{"来源文件": h["来源文件"], "起始行": h["起始行"], "结束行": h.get("结束行"),
                            "内容指纹": h.get("内容指纹"), "相似度": h.get("相似度"),
                            "重排分": h.get("重排分"), "重排前位次": h.get("重排前位次")}
                           for h in 命中[:存前]]}
            该臂[集] = 逐
            n = len(逐)
            k1 = sum(1 for t in 逐 if t["严格"])
            k2 = sum(1 for t in 逐 if t["含块"])
            均耗 = sum(t["耗时"] for t in 逐) / n if n else 0
            print(f"  【{集}】{n} 道｜严格 {k1}/{n} = {k1/n*100:.2f}%｜含块 {k2}/{n} = {k2/n*100:.2f}%"
                  f"｜平均 {均耗:.2f} 秒/题")
        该臂["_tokens"] = tokens
        print(f"  重排 token：{tokens:,}\n")
        汇总["臂"][str(候选数)] = 该臂

    # 净变化（以臂 50 为基准）
    print("=== 净变化（相对候选池 50）===")
    for 集 in ("覆盖集", "回归集"):
        基准 = {t["编号"]: t for t in 汇总["臂"]["50"][集]}
        for 候选数 in 臂[1:]:
            v = {t["编号"]: t for t in 汇总["臂"][str(候选数)][集]}
            for 口径 in ("严格", "含块"):
                新 = [k for k in v if v[k][口径] and not 基准.get(k, {}).get(口径)]
                丢 = [k for k in v if 基准.get(k, {}).get(口径) and not v[k][口径]]
                print(f"  {集}｜{候选数}｜{口径}：净 {len(新)-len(丢):+d}（新增 {len(新)}，丢失 {len(丢)}）")
                if 新:
                    print(f"      新增：{新}")
                if 丢:
                    print(f"      丢失：{丢}")

    print(f"\n总耗时 {time.time() - t0:.1f} 秒")
    try:
        print("重排账本：", json.dumps(检.读重排账本(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print("重排账本读取失败：", e)

    明细路径.write_text(json.dumps(明细, ensure_ascii=False), encoding="utf-8")
    输出路径.write_text(json.dumps(汇总, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细：{明细路径}")
    print(f"结果：{输出路径}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
