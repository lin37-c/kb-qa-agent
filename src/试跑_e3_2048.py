# -*- coding: utf-8 -*-
"""评测 `embedding-3` @2048 维：同一套 124 题、同一重排、同一判据。
★ 问向量直接调智谱接口（不走内容指纹缓存 —— 那份缓存是 1024 维的）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests

本文件 = Path(__file__).resolve()
根 = 本文件.parent.parent.parent
sys.path.insert(0, str(本文件.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as 检          # noqa: E402
import 配置               # noqa: E402
import 向量化             # noqa: E402

题集路径 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
库路径 = 根 / "data" / "向量库" / "切片.jsonl"
矩阵路径 = 根 / "data" / "向量库_e3_2048" / "向量.npy"
结果路径 = 根 / "05_项目验证证据" / "_M7评测" / "e3_2048_结果.json"
明细路径 = 根 / "05_项目验证证据" / "_M7评测" / "e3_2048_明细.json"
维度 = 2048
取前 = 100


def 净(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def 分段(f: str):
    段 = [净(x) for x in re.split(r"[；;／/]|…+|——|。", f)]
    return [x for x in 段 if len(x) >= 6] or [净(f)]


def 题型N(q: str) -> int:
    对比 = ("区别", "差异", "不同", "对比", "相比", "vs", "VS", "与…的差别", "有什么不一样")
    说明 = ("为什么", "原因", "是怎么", "如何保证", "原理")
    return 8 if any(m in q for m in 对比) else (5 if any(m in q for m in 说明) else 4)


def 问向量(问题们: list[str], key: str) -> np.ndarray:
    出 = []
    URL = f"{配置.服务地址}/embeddings"
    for i in range(0, len(问题们), 16):
        批 = 问题们[i : i + 16]
        payload = {"model": 配置.向量模型, "input": 批, "dimensions": 维度}
        for 试 in range(4):
            try:
                r = requests.post(URL, headers={"Authorization": f"Bearer {key}",
                                                "Content-Type": "application/json; charset=utf-8"},
                                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=60)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
                j = r.json()
                出.extend(d["embedding"] for d in j["data"])
                break
            except Exception as e:  # noqa: BLE001
                if 试 < 3:
                    time.sleep(1.5 * (试 + 1))
                else:
                    raise RuntimeError(f"问向量失败：{e}") from e
    return np.array(出, dtype=np.float32)


def main() -> int:
    t0 = time.time()
    key = 向量化.取密钥()
    题集 = json.loads(题集路径.read_text(encoding="utf-8-sig"))
    集s = {"覆盖集": 题集["覆盖集"], "回归集": 题集["回归集_B_改写配对"]}
    块 = [json.loads(l) for l in 库路径.read_text(encoding="utf-8").splitlines() if l.strip()]
    m = np.load(矩阵路径)
    assert m.shape[0] == len(块), f"向量 {m.shape} 与块 {len(块)} 不一致"
    模 = np.linalg.norm(m, axis=1, keepdims=True)
    模[模 == 0] = 1
    m = m / 模
    权重 = np.array([检.有效权重(d["来源文件"], d.get("文本", "")) for d in 块])
    print(f"库 {m.shape}｜块 {len(块)}｜模型 {配置.向量模型}@{维度}")

    全部题 = [x for 集 in 集s.values() for x in 集]
    Q = 问向量([检.扩展查询(x["问题"].strip())[0] for x in 全部题], key)
    Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
    print(f"问向量 {Q.shape}｜{time.time()-t0:.0f} 秒")

    明细 = {"元": {"生成时间": time.strftime("%F %T"), "模型": f"{配置.向量模型}@{维度}"}, "题": {}}
    汇总 = {"元": 明细["元"], "集": {}}
    tokens, idx = 0, 0
    for 集, 题们 in 集s.items():
        逐 = []
        for x in 题们:
            Nq = 题型N(x["问题"])
            段们, 可 = 分段(x["原文片段"]), tuple(x.get("可接受块") or ())
            分 = (m @ Q[idx]) * 权重
            idx += 1
            序 = np.argsort(-分)[:取前]
            候选 = []
            for i in 序:
                d = dict(块[int(i)])
                d["相似度"] = round(float(分[int(i)]), 4)
                候选.append(d)
            try:
                命中, 用量 = 检.重排(x["问题"].strip(), 候选, 取前=len(候选), 场景="M7e3_2048")
            except Exception as e:  # noqa: BLE001
                print(f"  ❌ {x['编号']} {str(e)[:100]}")
                continue
            tokens += (用量 or {}).get("tokens", 0)

            def 中(b):
                if all(s in 净(b.get("文本", "")) for s in 段们):
                    return True
                return any((a.get("内容指纹") and b.get("内容指纹") == a["内容指纹"]) or
                           (b.get("来源文件") == a.get("来源文件") and int(b.get("起始行", -1)) == int(a.get("起始行", -2)))
                           for a in 可)
            严格位 = next((i for i, b in enumerate(命中, 1) if all(s in 净(b.get("文本", "")) for s in 段们)), None)
            含块位 = next((i for i, b in enumerate(命中, 1) if 中(b)), None)
            逐.append({"编号": x["编号"], "N": Nq,
                       "严格": 严格位 is not None and 严格位 <= Nq, "严格位次": 严格位,
                       "含块": 含块位 is not None and 含块位 <= Nq, "含块位次": 含块位})
            明细["题"].setdefault(x["编号"], {})["e3_2048"] = {
                "集": 集, "块": [{"来源文件": h["来源文件"], "起始行": h["起始行"], "内容指纹": h.get("内容指纹"),
                                "相似度": h.get("相似度"), "重排分": h.get("重排分"),
                                "重排前位次": h.get("重排前位次")} for h in 命中[:20]]}
        汇总["集"][集] = 逐
        n = len(逐)
        k1 = sum(1 for t in 逐 if t["严格"])
        k2 = sum(1 for t in 逐 if t["含块"])
        print(f"  【{集}】{n} 道｜严格 {k1}/{n} = {k1/n*100:.2f}%｜含块 {k2}/{n} = {k2/n*100:.2f}%")

    print(f"\n重排 token {tokens:,}｜总耗时 {time.time()-t0:.0f} 秒")
    明细路径.write_text(json.dumps(明细, ensure_ascii=False), encoding="utf-8")
    结果路径.write_text(json.dumps(汇总, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细：{明细路径}\n结果：{结果路径}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
