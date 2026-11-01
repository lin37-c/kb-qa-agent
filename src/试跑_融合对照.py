# -*- coding: utf-8 -*-
"""M7 召回改造 R1 · 方案 B：两路召回（向量＋关键词）RRF 融合，两臂对照。

    F50  = 融合后取前 50，交给重排 50
    F100 = 融合后取前 100，交给重排 100

★ 关键词一路纯本地、不花钱；花钱的只有重排。
判据：严格口径 与 含可接受块 各判一次；与「向量@100 对照」(45/50) 比净变化。

用法：python 试跑_融合对照.py [--冒烟]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

本文件 = Path(__file__).resolve()
SRC = 本文件.parent
根 = SRC.parent.parent
sys.path.insert(0, str(SRC))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as 检          # noqa: E402
import 入库 as K           # noqa: E402
import 向量化              # noqa: E402
from 缓存 import 归一化     # noqa: E402

题集路径 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
结果路径 = 根 / "05_项目验证证据" / "_M7评测" / "融合两臂_结果.json"
明细路径 = 根 / "05_项目验证证据" / "_M7评测" / "融合两臂_明细.json"
库路径 = 根 / "data" / "向量库" / "切片.jsonl"

臂 = [50, 100]
K_RRF = 60
存前 = 20


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 词(s: str):
    s = s.lower()
    汉 = re.findall(r"[\u4e00-\u9fff]", s)
    return [汉[i] + 汉[i + 1] for i in range(len(汉) - 1)] + re.findall(r"[a-z0-9_\-]{2,}", s)


def 分段(f: str):
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", f)]
    return [x for x in 段 if len(x) >= 6] or [净(f)]


def 题型N(q: str) -> int:
    对比 = ("区别", "差异", "不同", "对比", "相比", "vs", "VS", "与…的差别", "有什么不一样")
    说明 = ("为什么", "原因", "是怎么", "如何保证", "原理")
    return 8 if any(m in q for m in 对比) else (5 if any(m in q for m in 说明) else 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--冒烟", action="store_true")
    a = ap.parse_args()
    深 = 128

    t0 = time.time()
    题集 = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    集s = {"覆盖集": 题集["覆盖集"], "回归集": 题集["回归集_B_改写配对"]}
    if a.冒烟:
        集s = {k: v[:1] for k, v in 集s.items()}

    块 = []
    for line in 库路径.read_text(encoding="utf-8").splitlines():
        if line.strip():
            块.append(json.loads(line))
    文本 = [d.get("文本", "") for d in 块]
    指纹 = [d["内容指纹"] for d in 块]

    # 关键词倒排（只为题里出现过的词建）
    查询词集 = set()
    for 集 in 集s.values():
        for x in 集:
            查询词集.update(词(x["问题"]))
    df = Counter()
    倒排 = defaultdict(list)
    for i, t in enumerate(文本):
        ws = set(词(t)) & 查询词集
        if ws:
            df.update(ws)
            for w in ws:
                倒排[w].append(i)
    N = len(文本)
    idf = {w: math.log(1 + (N - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    m, 元数据 = K.载入向量库()
    权重 = np.array([检.有效权重(d["来源文件"], d.get("文本", "")) for d in 元数据])
    print(f"库 {N} 块｜题中词 {len(查询词集)}｜倒排命中 {len(倒排)}｜臂 {臂}\n")

    def 融合候选(问题, 取):
        _, 纯 = 检.解析分组(问题)
        查询文本, _ = 检.扩展查询(问题.strip())
        qv = 归一化(向量化.向量化单条(查询文本, 场景="M3检索"))
        分v = (m @ qv) * 权重
        序v = list(np.argsort(-分v)[:深])
        q = [w for w in set(词(问题)) if w in idf]
        分k = Counter()
        for w in q:
            v = idf[w]
            for i in 倒排[w]:
                分k[i] += v
        序k = [i for i, _ in 分k.most_common(深)]
        融 = defaultdict(float)
        for r, i in enumerate(序v, 1):
            融[i] += 1 / (K_RRF + r)
        for r, i in enumerate(序k, 1):
            融[i] += 1 / (K_RRF + r)
        取序 = [i for i, _ in sorted(融.items(), key=lambda kv: -kv[1])[:取]]
        候选 = []
        for i in 取序:
            d = dict(元数据[int(i)])
            d["相似度"] = round(float(分v[int(i)]), 4)
            候选.append(d)
        return 候选

    def 判(块们, 段们, n, 可):
        def 中(b):
            if all(s in 净(b.get("文本", "")) for s in 段们):
                return True
            return any((x.get("内容指纹") and b.get("内容指纹") == x["内容指纹"]) or
                       (b.get("来源文件") == x.get("来源文件") and int(b.get("起始行", -1)) == int(x.get("起始行", -2)))
                       for x in 可)
        return any(中(b) for b in 块们[:n]), next((i for i, b in enumerate(块们, 1) if 中(b)), None)

    明细 = {"元": {"生成时间": time.strftime("%Y-%m-%d %H:%M:%S"), "臂": 臂, "RRF_k": K_RRF}, "题": {}}
    汇总 = {"元": 明细["元"], "臂": {}}

    for 取 in 臂:
        print(f"───── 臂 F{取} ─────")
        该臂 = {}
        tokens = 0
        for 集, 题们 in 集s.items():
            逐 = []
            for x in 题们:
                Nq = 题型N(x["问题"])
                段们 = 分段(x["原文片段"])
                可 = tuple(x.get("可接受块") or ())
                t1 = time.time()
                try:
                    候选 = 融合候选(x["问题"], 取)
                    命中, 用量 = 检.重排(x["问题"].strip(), 候选, 取前=len(候选), 场景="M7融合")
                except Exception as e:  # noqa: BLE001
                    print(f"  ❌ {x['编号']} {type(e).__name__}: {e}")
                    continue
                耗 = time.time() - t1
                tokens += (用量 or {}).get("tokens", 0)
                严格 = 判(命中, 段们, Nq, ())
                含块 = 判(命中, 段们, Nq, 可)
                逐.append({"编号": x["编号"], "N": Nq, "严格": 严格[0], "严格位次": 严格[1],
                           "含块": 含块[0], "含块位次": 含块[1],
                           "Top10": 判(命中, 段们, 10, 可)[0], "耗时": round(耗, 2)})
                明细["题"].setdefault(x["编号"], {})[f"F{取}"] = {
                    "集": 集,
                    "块": [{"来源文件": h["来源文件"], "起始行": h["起始行"], "结束行": h.get("结束行"),
                            "内容指纹": h.get("内容指纹"), "相似度": h.get("相似度"),
                            "重排分": h.get("重排分"), "重排前位次": h.get("重排前位次")}
                           for h in 命中[:存前]]}
            该臂[集] = 逐
            n = len(逐)
            k1 = sum(1 for t in 逐 if t["严格"])
            k2 = sum(1 for t in 逐 if t["含块"])
            均 = sum(t["耗时"] for t in 逐) / n if n else 0
            print(f"  【{集}】{n} 道｜严格 {k1}/{n} = {k1/n*100:.2f}%｜含块 {k2}/{n} = {k2/n*100:.2f}%"
                  f"｜平均 {均:.2f} 秒")
        该臂["_tokens"] = tokens
        print(f"  重排 token：{tokens:,}\n")
        汇总["臂"][str(取)] = 该臂

    # 与「向量@100 对照」比净变化
    对照路径 = 根 / "05_项目验证证据" / "_M7评测" / "召回三臂_结果.json"
    if 对照路径.exists() and not a.冒烟:
        对照 = json.loads(对照路径.read_text(encoding="utf-8"))["臂"]["100"]
        print("=== 净变化（对照：向量@100，严格 45/45、含块 50/50）===")
        for 集 in ("覆盖集", "回归集"):
            基 = {t["编号"]: t for t in 对照[集]}
            for 取 in 臂:
                v = {t["编号"]: t for t in 汇总["臂"][str(取)][集]}
                for 口径 in ("严格", "含块"):
                    新 = [k for k in v if v[k][口径] and not 基.get(k, {}).get(口径)]
                    丢 = [k for k in v if 基.get(k, {}).get(口径) and not v[k][口径]]
                    print(f"  {集}｜F{取}｜{口径}：净 {len(新)-len(丢):+d}（新增 {len(新)}，丢失 {len(丢)}）")
                    if 新:
                        print(f"      新增：{新}")
                    if 丢:
                        print(f"      丢失：{丢}")

    print(f"\n总耗时 {time.time()-t0:.1f} 秒")
    try:
        print("重排账本：", json.dumps(检.读重排账本(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print("账本读取失败：", e)
    明细路径.write_text(json.dumps(明细, ensure_ascii=False), encoding="utf-8")
    结果路径.write_text(json.dumps(汇总, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细：{明细路径}\n结果：{结果路径}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
