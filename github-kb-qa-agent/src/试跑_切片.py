# -*- coding: utf-8 -*-
"""M1 试跑：用真实语料验证切片参数，只输出统计与抽样，不写正式位置。

运行：
    <项目>\\02_项目源码与工程\\.venv\\Scripts\\python.exe -B -X utf8 试跑_切片.py

输出目录可用环境变量覆盖（默认：本脚本同级 _试跑输出）：
    $env:M1_输出目录 = "<候选区某目录>"
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import 切片 as S

语料根 = Path(r"<asset-root>")

# 输出目录：默认放本脚本同级的 _试跑输出。
# 可用环境变量 M1_输出目录 覆盖——用于在候选区开发时把中间产物写到候选区，
# 而不必复制出第二份脚本（§6.2⑨「同一用途只保留一套」）。
输出目录 = Path(os.environ.get("M1_输出目录") or (Path(__file__).resolve().parent / "_试跑输出"))

# 切片范围（按用户确认的手续逐步扩展）：
#   ① 规则正文      02_规则\*.md
#   ② 技能正文      01_技能\SKILL.md
#   ③ 维护层正文    04_来源版本与校验\*.md
#      ★ 加这一档的原因（实测发现的缺口）：14 条禁令的**完整定义**只在
#        `04_来源版本与校验\03_维护与改进\分歧与改进记录.md` 里，
#        规则层只有引用、没有定义。不加这一档，"禁令 P-14 说的是什么"这类问题
#        永远答不对——**不是检索不准，是库里根本没有**。
#        （扫描器已统一排除 _维护工作区 与 node_modules）
模式 = [
    ("02_规则", "*.md"),
    ("01_技能", "SKILL.md"),
    ("04_来源版本与校验", "*.md"),
]


def main() -> int:
    t0 = time.time()
    文件 = S.扫描语料(语料根, 模式)
    print("=" * 76)
    print("M1 切片试跑（不写正式位置）")
    print("=" * 76)
    print(f"语料根 : {语料根}")
    print(f"待切文件: {len(文件)} 个")
    for 子, 匹 in 模式:
        n = len([f for f in 文件 if 子 in f.parts])
        print(f"    {子} / {匹} → {n} 个")

    全部: list[S.切片] = []
    每文件: list[tuple[str, int, int]] = []
    for f in 文件:
        try:
            块 = S.切文件(f, 语料根)
        except Exception as e:  # noqa: BLE001
            print(f"    ❌ {f.name}: {e}")
            continue
        全部.extend(块)
        每文件.append((f.relative_to(语料根).as_posix(), len(块), sum(b.字符数 for b in 块)))

    字符 = [b.字符数 for b in 全部]
    字符.sort()

    def 分位(p: float) -> int:
        return 字符[min(len(字符) - 1, int(len(字符) * p))]

    print(f"\n{'=' * 76}")
    print("切片结果统计")
    print("=" * 76)
    print(f"总切片数   : {len(全部)}")
    print(f"总字符数   : {sum(字符):,}（原文合计 {sum(c for _, _, c in 每文件):,}）")
    print(f"平均每块   : {sum(字符) // len(字符)} 字符")
    print(f"最小 / 中位 / 最大 : {字符[0]} / {分位(0.5)} / {字符[-1]}")
    print(f"分位 P10/P25/P75/P90: {分位(0.1)} / {分位(0.25)} / {分位(0.75)} / {分位(0.9)}")
    print(f"\n参数：最小块合并阈值 {S.最小块字符} 字符 ｜ 最大块上限 {S.最大块字符} 字符")

    区间 = Counter()
    for c in 字符:
        if c < 100: 区间["<100"] += 1
        elif c < 300: 区间["100-299"] += 1
        elif c < 500: 区间["300-499"] += 1
        elif c < 700: 区间["500-699"] += 1
        elif c < 900: 区间["700-899"] += 1
        elif c <= 900: 区间["=900"] += 1
        else: 区间[">900（超上限）"] += 1
    print("\n字符数分布：")
    for k in ["<100", "100-299", "300-499", "500-699", "700-899", ">900（超上限）"]:
        if 区间[k]:
            print(f"    {k:>16} : {区间[k]:>5} 块  ({区间[k]/len(字符)*100:5.1f}%)")

    小块 = [b for b in 全部 if b.字符数 < 100]
    print(f"\n过碎小块（<100 字符）: {len(小块)} 个  {'✅' if len(小块) == 0 else '⚠️ 需调参'}")

    print(f"\n{'=' * 76}")
    print("产出最多的 12 个文件")
    print("=" * 76)
    print(f"{'文件':<52}{'块数':>6}{'字符':>9}")
    for name, n, c in sorted(每文件, key=lambda x: -x[1])[:12]:
        print(f"{name:<52}{n:>6}{c:>9,}")

    print(f"\n{'=' * 76}")
    print("抽样：3 个不同规模、不同来源的切片完整内容")
    print("=" * 76)
    样本 = sorted(全部, key=lambda b: b.字符数)
    取 = [样本[0], 样本[len(样本) // 2], 样本[-1]]
    for i, b in enumerate(取, 1):
        print(f"\n--- 样本 {i} ---")
        print(f"来源文件 : {b.来源文件}")
        print(f"标题路径 : {b.标题路径 or '(无标题)'}")
        print(f"行号     : {b.起始行}–{b.结束行}")
        print(f"字符数   : {b.字符数}")
        print("正文：")
        for line in b.文本.split("\n"):
            print(f"    │ {line}")

    # 落盘到临时目录（不是正式位置）
    输出目录.mkdir(parents=True, exist_ok=True)
    out = 输出目录 / "切片_试跑.jsonl"
    with out.open("w", encoding="utf-8") as fp:
        for b in 全部:
            fp.write(json.dumps({
                "来源文件": b.来源文件, "标题路径": b.标题路径,
                "起始行": b.起始行, "结束行": b.结束行,
                "字符数": b.字符数, "文本": b.文本,
            }, ensure_ascii=False) + "\n")
    print(f"\n{'=' * 76}")
    print(f"试跑输出（临时，非正式位置）: {out}")
    print(f"文件大小: {out.stat().st_size:,} 字节 ｜ 总耗时 {time.time() - t0:.1f} 秒")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
