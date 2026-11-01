# -*- coding: utf-8 -*-
"""向量缓存：按「内容指纹」复用已算过的向量，避免重复付费。

为什么必须要有这一层：
    embedding 是按 token 付费的。切片参数调一次、重跑一次，如果全量重算，
    就是一笔真金白银。而绝大多数文字在两次重跑之间根本没变——
    重算它们纯属浪费。缓存就是把这部分浪费消掉。

为什么缓存能成立（关键，与"接口是否确定性"无关）：
    我们不依赖"接口每次返回一模一样"。
    只要内容的指纹没变，就直接复用本地存的那份向量——
    接口偶尔的浮点抖动不会影响我们，因为我们根本不重新调它。
    ★ 这一点很重要：很多人以为"接口不稳定所以没法缓存"，其实方向反了——
      缓存恰恰是应对接口抖动的手段，而不是依赖接口稳定的结果。

存储结构（两个文件，都是可重建的运行产物）：
    data/缓存/索引.json       指纹 → {文件名, 位置, 去向偏移, 长度}
    data/缓存/向量.jsonl      一行一条 JSON：{"指纹":..., "向量":[...]}  （追加式）
    为什么拆两个：
        只用一个 JSON 大文件的话，每加一条就要重写整个文件，几万条会越来越慢。
        拆成「索引 + 追加日志」后，新增是纯追加，快且不怕中断。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import 配置


缓存目录 = 配置.缓存目录
索引路径 = 缓存目录 / "索引.json"
向量路径 = 缓存目录 / "向量.jsonl"


class 向量缓存:
    """内容指纹 → 向量 的本地缓存。"""

    def __init__(self) -> None:
        缓存目录.mkdir(parents=True, exist_ok=True)
        self._索引: dict[str, list] = {}
        self._向量池: list[list[float]] = []
        self._命中 = 0
        self._未命中 = 0
        self._载入()

    # ---------- 启动时读盘 ----------
    def _载入(self) -> None:
        if 索引路径.exists():
            self._索引 = json.loads(索引路径.read_text(encoding="utf-8"))
        if 向量路径.exists():
            with 向量路径.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._向量池.append(json.loads(line)["向量"])

    # ---------- 查询 ----------
    def 取(self, 指纹: str) -> list[float] | None:
        loc = self._索引.get(指纹)
        if loc is None:
            self._未命中 += 1
            return None
        self._命中 += 1
        return self._向量池[loc["行"]]

    # ---------- 写入 ----------
    def 存(self, 指纹: str, 向量: list[float]) -> None:
        if 指纹 in self._索引:
            return
        行号 = len(self._向量池)
        with 向量路径.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"指纹": 指纹, "向量": 向量}, ensure_ascii=False) + "\n")
        self._向量池.append(向量)
        self._索引[指纹] = {"行": 行号}
        索引路径.write_text(
            json.dumps(self._索引, ensure_ascii=False), encoding="utf-8"
        )

    # ---------- 统计 ----------
    @property
    def 已缓存条数(self) -> int:
        return len(self._索引)

    @property
    def 本次命中(self) -> int:
        return self._命中

    @property
    def 本次未命中(self) -> int:
        return self._未命中

    def 重置计数(self) -> None:
        self._命中 = 0
        self._未命中 = 0


# ---------- 向量数学 ----------
def 归一化(向量: list[float] | np.ndarray) -> np.ndarray:
    """把向量缩放成模长 = 1。

    为什么需要：
        智谱 embedding-3 返回的是**未归一化**向量（实测模长 0.7785，不是 1）。
        未归一化时，"点积"不等于"余弦相似度"，对角线也就不是 1。
        归一化之后，点积 = 余弦相似度，数值才落在 0~1 且可解释。
    """
    a = np.asarray(向量, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return a / n if n else a


def 余弦相似度矩阵(向量组: list[list[float]] | np.ndarray) -> np.ndarray:
    """一批向量两两之间的余弦相似度（先逐行归一化，再点积）。"""
    m = np.asarray(向量组, dtype=np.float32)
    m = m / np.linalg.norm(m, axis=1, keepdims=True)
    return m @ m.T


def 余弦相似度(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    return float(归一化(a) @ 归一化(b))
