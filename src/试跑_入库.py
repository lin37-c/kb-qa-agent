# -*- coding: utf-8 -*-
"""M2 试跑：入库 + 验证。支持 A / B 两个范围，跑完打印统计与检索实测。

范围口径（用户 2026-10-13 确认）：
    A = 仅中文为主的切片（语料来自 02_规则\，取中文占比 > 15% 的块）
    B = A + 全部技能正文切片（语料来自 01_技能\SKILL.md）

为什么 A 要做"中文占比"过滤：
    02_规则\ 里混有中英夹杂的片段；而 A 的目的就是"先只入中文规则、把流程跑通"。
    阈值 15% 是本次 A 的口径——A 的语料本就是规则，这个阈值只用来剔掉纯英文碎片。

用法：
    python 试跑_入库.py A      # 只入中文规则
    python 试跑_入库.py B      # 再追加技能正文
    python 试跑_入库.py 查询 "改文件之前要先做什么"
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# 搜索路径要加两处：
#   ① 本文件所在目录 —— 让 import 入库 命中"正在被验证的候选版"
#   ② 正式位置的 src\ —— 让 入库.py 里的 import 配置/向量化/缓存 命中已发布的依赖包
# 为什么需要 ②：候选区只有待验证的脚本，共享依赖仍在正式位置。
#   若不加，Python 找不到 配置.py（它只把脚本自身目录放进搜索路径）。
项目src = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用\02_项目源码与工程\src")
for p in (str(Path(__file__).resolve().parent), str(项目src)):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np

import 入库 as K

# 切片来源：默认取 <项目>\data\缓存\_试跑输出\切片_试跑.jsonl 这类位置。
# 用环境变量 M2_切片文件 指定，便于在候选区开发时指向候选区的产物。
默认切片 = Path(__file__).resolve().parent / "_试跑输出" / "切片_试跑.jsonl"
切片源 = Path(os.environ.get("M2_切片文件") or 默认切片)

中文阈值 = 0.15


# 范围口径（用户 2026-10-13 确认，同日追加 C 档）：
#     A = 仅中文为主的切片（语料来自 02_规则\，中文占比 > 15%）
#     B = A + 全部技能正文切片（语料来自 01_技能\SKILL.md）
#     C = B + 维护层正文（04_来源版本与校验\03_维护与改进\ 下的 *.md）
#         ★ 加 C 的原因（实测发现的缺口）：14 条禁令的**完整定义**只存在于该目录的
#           分歧与改进记录.md；规则层只有引用、没有定义。不加这一档，
#           "禁令 P-14 说的是什么"这类问题永远答不对——不是检索不准，是库里没有。
维护层前缀 = ("04_来源版本与校验/",)


def 中文占比(t: str) -> float:
    if not t:
        return 0.0
    return sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff") / len(t)


def 读切片(范围: str) -> list[dict]:
    if not 切片源.exists():
        raise FileNotFoundError(
            f"找不到 M1 切片文件：{切片源}\n"
            "请先在候选区跑一次 试跑_切片.py 生成它。"
        )
    rows = [json.loads(l) for l in 切片源.read_text(encoding="utf-8").splitlines() if l.strip()]
    范围 = 范围.upper()
    if 范围 == "A":
        取 = [r for r in rows if r["来源文件"].startswith("02_规则/") and 中文占比(r["文本"]) > 中文阈值]
    elif 范围 == "B":
        取 = rows
    elif 范围 == "C":
        取 = rows
    else:
        raise ValueError(f"未知范围：{范围}（应为 A / B / C）")
    return 取


def 打印统计(全部切片: list[dict], 本次: list[dict], 结果: dict) -> None:
    print("\n" + "=" * 76)
    print("入库统计")
    print("=" * 76)
    print(f"切片文件总量     : {len(全部切片)} 块")
    print(f"本次入库         : {len(本次)} 块")
    print(f"本次字符数       : {结果.get('字符数', 0):,}")
    print(f"耗时             : {结果.get('耗时秒', 0)} 秒")
    print(f"缓存命中/未命中  : {结果.get('缓存命中', 0)} / {结果.get('缓存未命中', 0)}")
    if 结果.get("缓存命中"):
        print(f"    ↑ 命中 {结果['缓存命中']} 块没有重新调接口 —— 这就是缓存省下的钱")
    if 结果.get("缓存未命中"):
        账 = K.向量化.读账本()
        print(f"账本累计         : {账['次数']} 次调用 / {账['tokens']} token / {账['费用_元']} 元")

    按来源 = {}
    for r in 本次:
        按来源.setdefault(r["来源文件"], 0)
        按来源[r["来源文件"]] += 1
    print(f"\n涉及文件数       : {len(按来源)}")
    print("块数最多的 8 个文件：")
    for k, v in sorted(按来源.items(), key=lambda x: -x[1])[:8]:
        print(f"    {v:>4} 块  {k}")


def 自检() -> tuple[np.ndarray, list[dict]]:
    print("\n" + "=" * 76)
    print("向量库自检")
    print("=" * 76)
    m, 元数据 = K.载入向量库()
    print(f"向量矩阵 : {m.shape[0]} 行 × {m.shape[1]} 列")
    print(f"元数据   : {len(元数据)} 条")
    print(f"行数一致 : {'✅' if m.shape[0] == len(元数据) else '❌'}")
    # 归一化核对：每行模长应≈1
    模长 = np.linalg.norm(m, axis=1)
    print(f"模长     : min {模长.min():.6f} / max {模长.max():.6f}  → {'✅ 已归一化' if abs(模长.max()-1) < 1e-4 and abs(模长.min()-1) < 1e-4 else '❌ 未归一化'}")
    print(f"数值范围 : {m.min():.5f} ~ {m.max():.5f}")
    库大小 = sum(f.stat().st_size for f in K.库目录.iterdir() if f.is_file())
    print(f"库文件   : {K.元数据路径.name} + {K.向量路径.name} = {库大小/1024/1024:.2f} MB")
    return m, 元数据


def 检索实测(问题列表: list[str], 取前: int = 3) -> None:
    print("\n" + "=" * 76)
    print("检索实测（用中文提问，看召回准不准）")
    print("=" * 76)
    for q in 问题列表:
        print(f"\n提问：「{q}」")
        try:
            命中 = K.检索(q, 取前=取前)
        except Exception as e:  # noqa: BLE001
            print(f"    ❌ {e}")
            continue
        for i, h in enumerate(命中, 1):
            t = h["文本"].replace("\n", " ⏎ ")
            print(f"    {i}. [{h['相似度']:.4f}] {h['来源文件']}")
            print(f"       标题: {h['标题路径'] or '(无)'}  行 {h['起始行']}–{h['结束行']}")
            print(f"       内容: {t[:110]}{'…' if len(t) > 110 else ''}")


def main() -> int:
    范围 = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()

    print("=" * 76)
    print(f"M2 入库试跑 —— 范围 {范围}")
    print("=" * 76)

    全部 = [json.loads(l) for l in 切片源.read_text(encoding="utf-8").splitlines() if l.strip()] if 切片源.exists() else []
    本次 = 读切片(范围)
    print(f"切片文件: {切片源}")
    print(f"切片总量: {len(全部)} 块 ｜ 本次入库: {len(本次)} 块")

    t0 = time.time()
    结果 = K.入库(本次, 场景=f"M2_范围{范围}")
    打印统计(全部, 本次, 结果)

    m, 元数据 = 自检()

    问题 = [
        "改文件之前要先做什么",
        "提交代码之前需要出什么报告",
        "候选区和正式区的区别是什么",
        "禁令 P-14 说的是什么",
        "个人偏好里对交付目录怎么规定的",
    ]
    检索实测(问题)

    print("\n" + "=" * 76)
    print(f"M2 范围 {范围} 完成 ｜ 总耗时 {time.time()-t0:.1f} 秒")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
