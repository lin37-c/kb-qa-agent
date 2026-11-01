# -*- coding: utf-8 -*-
"""建「含标题路径」的向量库：把 `标题路径` 拼进被向量化的文本。

★ 与 建库_v4.py 的唯一差别：被向量化的文本 = `标题路径 + "\\n" + 正文`。
  为什么：`入库.py` 原来只嵌正文，切片里明明有 `兼容性测试 > 分层策略` 这种上下文没用上。
  打的是"问字段/问章节"的题（如「插件登记文件里有 plugins 吗」——正文可能只有一行 JSON）。

落点：data/向量库_v4_2048_t/向量.npy（**旧库原样保留，不覆盖**）
断点：每 50 批落盘 ＋ `进度.json`；重跑同一条命令自动续。
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
输出目录 = 根 / "data" / "向量库_v4_2048_t"
向量路径 = 输出目录 / "向量.npy"
部分路径 = 输出目录 / "向量_部分.npy"
进度路径 = 输出目录 / "进度.json"
用量路径 = 输出目录 / "用量.jsonl"
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
模型 = "text-embedding-v4"
维度 = 2048
批 = 10
每批落盘 = 50


def 文本含标题(d: dict) -> str:
    t = d.get("标题路径") or ""
    body = d.get("文本") or ""
    return f"{t}\n{body}" if t.strip() else body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--限", type=int, default=0)
    ap.add_argument("--重来", action="store_true")
    a = ap.parse_args()

    key = os.environ.get("QWEN_KEY", "")
    if not key:
        print("❌ 环境变量 QWEN_KEY 为空")
        return 1

    块 = [json.loads(l) for l in 库路径.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.限:
        块 = 块[: a.限]
    输出目录.mkdir(parents=True, exist_ok=True)

    起, vecs = 0, []
    if 进度路径.exists() and 部分路径.exists() and not a.重来:
        进 = json.loads(进度路径.read_text(encoding="utf-8"))
        旧 = np.load(部分路径)
        if 旧.shape[0] == 进["已处理"] and 进["总块数"] == len(块):
            起 = 进["已处理"]
            vecs = 旧.tolist()
            print(f"♻️ 从断点续跑：已有 {起} 块")
        else:
            print("⚠️ 断点与当前任务不匹配，从头开始")
    if 起 == 0 and 用量路径.exists():
        用量路径.rename(输出目录 / f"用量_上次_{time.strftime('%Y%m%d_%H%M')}.jsonl")

    print(f"待向量化 {len(块)}（从 {起}）｜{模型}｜{维度} 维｜批 {批}｜每 {每批落盘} 批落盘"
          f"｜文本=标题路径+正文")
    t0, tokens, n批 = time.time(), 0, 0
    for i in range(起, len(块), 批):
        批块 = 块[i : i + 批]
        payload = {"model": 模型, "input": [文本含标题(b) for b in 批块], "dimensions": 维度}
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
                t = int((j.get("usage") or {}).get("total_tokens", 0))
                tokens += t
                with 用量路径.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"时间": time.strftime("%F %T"), "条数": len(批块), "tokens": t},
                                       ensure_ascii=False) + "\n")
                break
            except Exception as e:  # noqa: BLE001
                if 试 < 3:
                    time.sleep(2 * (试 + 1))
                else:
                    print(f"❌ 第 {i} 批失败：{str(e)[:150]}")
                    if vecs:
                        np.save(部分路径, np.array(vecs, dtype=np.float32))
                        进度路径.write_text(json.dumps({"已处理": len(vecs), "总块数": len(块)}), encoding="utf-8")
                        print(f"   已存 {len(vecs)} 块，可续跑")
                    return 1
        n批 += 1
        if n批 % 每批落盘 == 0:
            np.save(部分路径, np.array(vecs, dtype=np.float32))
            进度路径.write_text(json.dumps({"已处理": len(vecs), "总块数": len(块)}), encoding="utf-8")
            print(f"  💾 {len(vecs)}/{len(块)}｜tokens {tokens:,}｜{time.time()-t0:.0f} 秒", flush=True)

    arr = np.array(vecs, dtype=np.float32)
    np.save(向量路径, arr)
    for p in (部分路径, 进度路径):
        if p.exists():
            p.unlink()
    # 元数据沿用同一批块（顺序一致）
    (输出目录 / "元数据.jsonl").write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in 块), encoding="utf-8")
    print(f"\n✅ {arr.shape} → {向量路径}")
    print(f"   tokens {tokens:,}｜约 ¥{tokens/1e6*0.5:.3f}｜耗时 {time.time()-t0:.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
