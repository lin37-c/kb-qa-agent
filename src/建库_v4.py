# -*- coding: utf-8 -*-
"""建一套新向量库：DashScope text-embedding-v4（1024 维），**不动旧库**。

★ 2026-10-23 加断点：每 50 批落一次盘，中断后可按 `进度.json` 续跑。
   （上一版只在最后保存，跑到 97.5% 被停，¥0.93 全白花 —— 这是那次教训的直接修补。）

落点：data/向量库_v4/向量.npy（41 MB）＋ 沿用 data/向量库/切片.jsonl 的同一批块（顺序不变）
key：只从环境变量 QWEN_KEY 读，不落盘、不打印。

用法：python 建库_v4.py [--限 N] [--重来]
"""
from __future__ import annotations

import argparse
import json
import os
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

库路径 = 根 / "data" / "向量库" / "切片.jsonl"
URLEP = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
维度 = 1024
批 = 10
每批落盘 = 50          # 每 50 批（500 块）存一次


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--限", type=int, default=0)
    ap.add_argument("--重来", action="store_true")
    ap.add_argument("--模型", default="text-embedding-v4")
    ap.add_argument("--子目录", default="向量库_v4")
    ap.add_argument("--维", type=int, default=1024)
    a = ap.parse_args()

    global 模型, 输出目录, 向量路径, 部分路径, 进度路径, 用量路径, 维度
    模型 = a.模型
    维度 = a.维
    输出目录 = 根 / "data" / a.子目录
    向量路径 = 输出目录 / "向量.npy"
    部分路径 = 输出目录 / "向量_部分.npy"
    进度路径 = 输出目录 / "进度.json"
    用量路径 = 输出目录 / "用量.jsonl"
    URL = URLEP

    key = os.environ.get("QWEN_KEY", "")
    if not key:
        print("❌ 环境变量 QWEN_KEY 为空")
        return 1

    块 = [json.loads(l) for l in 库路径.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.限:
        块 = 块[: a.限]
    输出目录.mkdir(parents=True, exist_ok=True)

    起 = 0
    vecs: list[list[float]] = []
    if 进度路径.exists() and 部分路径.exists() and not a.重来:
        进 = json.loads(进度路径.read_text(encoding="utf-8"))
        旧 = np.load(部分路径)
        if 旧.shape[0] == 进["已处理"] and 进["总块数"] == len(块):
            起 = 进["已处理"]
            vecs = 旧.tolist()
            print(f"♻️ 从断点续跑：已有 {起} 块")
        else:
            print("⚠️ 断点与当前任务不匹配，从头开始")
    if 起 == 0:
        # 从头跑：把上次的用量日志改名留档，避免与本轮混账
        if 用量路径.exists():
            用量路径.rename(输出目录 / f"用量_上次_{time.strftime('%Y%m%d_%H%M')}.jsonl")

    print(f"待向量化 {len(块)} 块（从第 {起} 块起）｜模型 {模型}｜维度 {维度}｜批 {批}｜每 {每批落盘} 批落盘")

    t0 = time.time()
    tokens = 0
    n批 = 0
    for i in range(起, len(块), 批):
        批块 = 块[i : i + 批]
        payload = {"model": 模型, "input": [b["文本"] for b in 批块], "dimensions": 维度}
        for 试 in range(4):
            try:
                r = requests.post(URL, headers={"Authorization": f"Bearer {key}",
                                                "Content-Type": "application/json"},
                                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=120)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                j = r.json()
                d = sorted(j["data"], key=lambda x: x["index"])
                vecs.extend(x["embedding"] for x in d)
                u = j.get("usage", {}) or {}
                t = int(u.get("total_tokens") or u.get("prompt_tokens") or 0)
                tokens += t
                with 用量路径.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"时间": time.strftime("%F %T"), "条数": len(批块), "tokens": t}) + "\n")
                break
            except Exception as e:  # noqa: BLE001
                if 试 < 3:
                    time.sleep(2 * (试 + 1))
                else:
                    print(f"❌ 第 {i} 批连续失败：{str(e)[:160]}")
                    if vecs:
                        np.save(部分路径, np.array(vecs, dtype=np.float32))
                        进度路径.write_text(json.dumps({"已处理": len(vecs), "总块数": len(块)}), encoding="utf-8")
                        print(f"   已把 {len(vecs)} 块存盘，可续跑")
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
    print(f"\n✅ 已保存 {arr.shape} → {向量路径}")
    print(f"   tokens {tokens:,}｜约 ¥{tokens/1e6*0.5:.4f}｜耗时 {time.time()-t0:.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
