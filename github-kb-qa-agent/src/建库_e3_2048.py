# -*- coding: utf-8 -*-
"""建 `embedding-3` @2048 维的向量库（智谱），**不动旧库、不走旧缓存**。

★ 为什么不用 向量化.py：它的内容指纹缓存**只按文本哈希**，会直接返回 1024 维的旧向量。
  这里直接调接口，批 16，每 50 批落盘、可续跑。

落点：data/向量库_e3_2048/向量.npy
"""
from __future__ import annotations

import argparse
import json
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

import 配置          # noqa: E402
import 向量化        # noqa: E402

库路径 = 根 / "data" / "向量库" / "切片.jsonl"
输出目录 = 根 / "data" / "向量库_e3_2048"
向量路径 = 输出目录 / "向量.npy"
部分路径 = 输出目录 / "向量_部分.npy"
进度路径 = 输出目录 / "进度.json"
用量路径 = 输出目录 / "用量.jsonl"
模型 = "embedding-3"
维度 = 2048
批 = 16
每批落盘 = 50


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--限", type=int, default=0)
    a = ap.parse_args()

    key = 向量化.取密钥()
    块 = [json.loads(l) for l in 库路径.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.限:
        块 = 块[: a.限]
    输出目录.mkdir(parents=True, exist_ok=True)

    起, vecs = 0, []
    if 进度路径.exists() and 部分路径.exists():
        进 = json.loads(进度路径.read_text(encoding="utf-8"))
        旧 = np.load(部分路径)
        if 旧.shape[0] == 进["已处理"] and 进["总块数"] == len(块):
            起 = 进["已处理"]
            vecs = 旧.tolist()
            print(f"♻️ 从断点续跑：已有 {起} 块")
    else:
        if 用量路径.exists():
            用量路径.rename(输出目录 / f"用量_上次_{time.strftime('%Y%m%d_%H%M')}.jsonl")

    print(f"待向量化 {len(块)} 块（从 {起} 起）｜{模型}｜维度 {维度}｜批 {批}")
    t0, tokens, n批 = time.time(), 0, 0
    URL = f"{配置.服务地址}/embeddings"
    for i in range(起, len(块), 批):
        批块 = 块[i : i + 批]
        payload = {"model": 模型, "input": [b["文本"] for b in 批块], "dimensions": 维度}
        for 试 in range(4):
            try:
                r = requests.post(URL, headers={"Authorization": f"Bearer {key}",
                                                "Content-Type": "application/json; charset=utf-8"},
                                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=120)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                j = r.json()
                vecs.extend(d["embedding"] for d in j["data"])
                t = int((j.get("usage") or {}).get("total_tokens", 0))
                tokens += t
                with 用量路径.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"时间": time.strftime("%F %T"), "条数": len(批块), "tokens": t}) + "\n")
                break
            except Exception as e:  # noqa: BLE001
                if 试 < 3:
                    time.sleep(2 * (试 + 1))
                else:
                    print(f"❌ 第 {i} 批失败：{str(e)[:160]}")
                    if vecs:
                        np.save(部分路径, np.array(vecs, dtype=np.float32))
                        进度路径.write_text(json.dumps({"已处理": len(vecs), "总块数": len(块)}), encoding="utf-8")
                    return 1
        n批 += 1
        if n批 % 每批落盘 == 0:
            np.save(部分路径, np.array(vecs, dtype=np.float32))
            进度路径.write_text(json.dumps({"已处理": len(vecs), "总块数": len(块)}), encoding="utf-8")
            print(f"  💾 {len(vecs)}/{len(块)}｜tokens {tokens:,}｜{time.time()-t0:.0f} 秒")

    arr = np.array(vecs, dtype=np.float32)
    np.save(向量路径, arr)
    for p in (部分路径, 进度路径):
        if p.exists():
            p.unlink()
    print(f"\n✅ {arr.shape} → {向量路径}")
    print(f"   tokens {tokens:,}｜约 ¥{tokens/1e6*0.5:.4f}｜耗时 {time.time()-t0:.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
