# -*- coding: utf-8 -*-
"""入库与查询：把切片变成向量，存进本地向量库；并按中文提问召回。

这一步在 RAG 里的位置：
    切片(M1) → 【向量化 + 入库】 → 检索(M3) → 生成(M4)
    本模块同时提供"入库"和"按问句召回"，因为召回是验证入库是否成功的唯一手段。

为什么自带查询（而不是留到 M3）：
    入库完不验证等于没做。而验证的唯一办法就是"拿一个真实问题去召回，看对不对"。
    所以本模块把最小可用的查询也一并实现——M3 再在它上面做加工（重排、阈值、多路召回）。

存储设计（两个文件，都是可重建的运行产物）：
    data/向量库/切片.jsonl    一行一块：来源、标题路径、行号、内容指纹、文本
    data/向量库/向量.csv      一行一块：1024 个归一化后的浮点数
    为什么分两个文件：
        JSONL 便于人读与增量追加；CSV 便于 numpy 直接加载成矩阵（快）。
        两者行号一一对应（第 N 行 = 第 N 块）。

    ★ 为什么存归一化后的向量：
        M1 试跑实测发现 embedding-3 返回的是**未归一化**向量（模长 0.7785 而非 1）。
        入库时统一归一化，检索时点积即余弦相似度，不用每次重复计算。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

import 配置
import 向量化
from 缓存 import 归一化

库目录 = 配置.数据目录 / "向量库"
元数据路径 = 库目录 / "切片.jsonl"
向量路径 = 库目录 / "向量.csv"


# ---------- 入库 ----------
def 入库(切片列表: list[dict], 场景: str = "入库") -> dict:
    """把切片列表向量化并写入向量库。

    参数
        切片列表：每项含 来源文件 / 标题路径 / 起始行 / 结束行 / 文本
    返回
        统计信息字典（块数、字符数、缓存命中、耗时等）

    ★ 为什么是"整体重建"而不是"增量追加"：
        元数据文件与向量文件是**按行号一一对应**的两个文件（第 N 行 = 第 N 块）。
        若两次运行各自 append，一旦中途失败或范围变化，两个文件就会行数错位，
        重复内容也会被重复写入。整体重建最简单、最不容易错。
        重建并不贵——向量化有内容指纹缓存，没变的块**不会重新调接口**，
        增量成本只是"重写两个本地文件"。
    """
    if not 切片列表:
        return {"块数": 0}
    库目录.mkdir(parents=True, exist_ok=True)

    文本s = [s["文本"] for s in 切片列表]
    t0 = __import__("time").time()
    向量s = 向量化.向量化(文本s, 场景=场景)
    耗时 = __import__("time").time() - t0

    缓存 = 向量化.缓存实例()

    # 元数据：整体重写
    with 元数据路径.open("w", encoding="utf-8") as f:
        for s in 切片列表:
            f.write(json.dumps({
                "来源文件": s["来源文件"],
                "标题路径": s.get("标题路径", ""),
                "起始行": s.get("起始行", 0),
                "结束行": s.get("结束行", 0),
                "内容指纹": 向量化.内容指纹(s["文本"]),
                "字符数": len(s["文本"]),
                "文本": s["文本"],
            }, ensure_ascii=False) + "\n")

    # 向量：整体重写，统一归一化（点积即余弦相似度）
    with 向量路径.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for v in 向量s:
            w.writerow([f"{x:.7f}" for x in 归一化(v)])

    return {
        "块数": len(切片列表),
        "字符数": sum(len(t) for t in 文本s),
        "耗时秒": round(耗时, 2),
        "缓存命中": getattr(缓存, "本次命中", 0),
        "缓存未命中": getattr(缓存, "本次未命中", 0),
    }


# ---------- 载入 ----------
def 载入向量库() -> tuple[np.ndarray, list[dict]]:
    """读回向量矩阵与元数据。返回（矩阵 N×维度, 元数据列表）。

    ★ 2026-10-24：支持两种落盘形态 ——
      ① `向量.npy` ＋ `元数据.jsonl`（当前 v4@2048 用这种，载入快、体积小）
      ② `向量.csv` ＋ `元数据.jsonl`（旧智谱库的形态，保留兼容；旧库不再被读取）
    """
    元数据路径 = 配置.向量库目录 / "元数据.jsonl"
    npy路径 = 配置.向量库目录 / "向量.npy"

    if npy路径.exists():
        m = np.load(npy路径).astype(np.float32)
        元数据 = [json.loads(line) for line in 元数据路径.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(元数据) != m.shape[0]:
            raise RuntimeError(f"元数据 {len(元数据)} 条与向量 {m.shape[0]} 行不一致——库损坏，需重建")
        return m, 元数据

    向量路径 = 配置.向量库目录 / "向量.csv"
    if not 向量路径.exists() or not 元数据路径.exists():
        raise FileNotFoundError(f"向量库为空，请先入库。期望：{npy路径} 或 {向量路径}")
    m = np.loadtxt(向量路径, delimiter=",", dtype=np.float32)
    if m.ndim == 1:                      # 只有一行时 numpy 会给一维数组
        m = m.reshape(1, -1)
    元数据 = [json.loads(line) for line in 元数据路径.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(元数据) != m.shape[0]:
        raise RuntimeError(f"元数据 {len(元数据)} 条与向量 {m.shape[0]} 行不一致——库损坏，需重建")
    return m, 元数据


# ---------- 检索 ----------
def 检索(问题: str, 取前: int = 5) -> list[dict]:
    """按中文问题召回最相关的若干块。

    做法：把问题也向量化并归一化，与库中每块算点积（=余弦相似度），取前 N。
    """
    m, 元数据 = 载入向量库()
    qv = 归一化(向量化.向量化单条(问题, 场景="检索问题"))
    分 = m @ qv                                   # 库已归一化 + 问题已归一化 → 点积即余弦
    序 = np.argsort(-分)[:取前]
    结果 = []
    for i in 序:
        d = dict(元数据[int(i)])
        d["相似度"] = round(float(分[int(i)]), 4)
        结果.append(d)
    return 结果
