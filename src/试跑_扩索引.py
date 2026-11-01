# -*- coding: utf-8 -*-
"""分期扩索引：按「期」跑切片 + 入库，产出真实花费与规模。

与 M1/M2 试跑的区别：
    M1/M2 试跑处理的是**写死的小范围**（3 个顶层目录的 .md）。
    本脚本处理的是**整个资产包**，按用户定的判据（"内容是不是用户的"）分类入索引。

用法：
    python 试跑_扩索引.py --期 第1期              # 只切片，不写库（免费，先看规模）
    python 试跑_扩索引.py --期 第1期 --入库        # 真入库（会花钱，先报预估）
    python 试跑_扩索引.py --期 全包 --入库         # 全包一次到位

成本保护（用户 2026-10-13 要求「确定效果再花钱」）：
    ① **默认只切片不入库** —— 不加 --入库 就一分钱不花，但能看到块数/字符数/分布
    ② 入库前打印预估费用，并要求 `--确认费用 <数值>` 与之匹配才继续
    ③ 内容指纹缓存：已算过的块不重复计费；失败重跑只花时间不花钱
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

# ⚠️ sys.path 顺序：候选区（被测代码）必须在最前，正式 src 只作依赖来源。
#    实测踩过：写成"已在 sys.path 就跳过"会让正式版盖住候选版（Python 会把脚本目录
#    自动放进 sys.path，于是那一条被跳过、正式 src 被插到第 0 位）。
_本目录 = str(Path(__file__).resolve().parent)
项目src = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用\02_项目源码与工程\src")
if str(项目src) not in sys.path:
    sys.path.append(str(项目src))
while _本目录 in sys.path:
    sys.path.remove(_本目录)
sys.path.insert(0, _本目录)

import 语料管道 as P
import 入库 as K

语料根 = Path(r"<asset-root>")
输出目录 = Path(os.environ.get("M1_输出目录") or (Path(__file__).resolve().parent / "_试跑输出"))

# 实测口径（2026-10-13 用 4 个样本各调一次 embedding-3 标定）
字每token = 1.50
元每token = 0.5 / 1_000_000


def 打印统计(st: P.统计, 标签: str) -> None:
    print("=" * 88)
    print(f"{标签} · 切片结果")
    print("=" * 88)
    print(f"  入索引文件  : {st.文件数:,} 个（全文 {st.全文文件:,} ／ 结构化 {st.结构化文件:,} ／ 二进制条目 {st.二进制文件:,}）")
    print(f"  切片块数    : {st.切片数:,} 块")
    print(f"  字符数      : {st.字符数:,}")
    if st.切片数:
        print(f"  平均块大小  : {st.字符数 / st.切片数:.0f} 字符")
    if st.失败:
        print(f"  ⚠️ 失败      : {len(st.失败)} 个")
        for f, e in st.失败[:5]:
            print(f"       {f}  →  {e}")
    print()
    print("  按顶层目录（块数）：")
    for k, v in sorted(st.按顶层.items(), key=lambda x: -x[1]):
        print(f"    {k:<28}{v:>8,}")
    if getattr(st, "跳过", None):
        print()
        print("  排除统计：")
        for k, v in sorted(st.跳过.items(), key=lambda x: -x[1]):
            print(f"    {k:<54}{v:>5} 个文件")
    if getattr(st, "台账明细", None):
        print()
        print(f"  ★ 台账类排除明细（{len(st.台账明细)} 个文件，可核对／可回退）：")
        for f in st.台账明细[:40]:
            print(f"      {f}")
        if len(st.台账明细) > 40:
            print(f"      …另有 {len(st.台账明细)-40} 个")
    print()
    print("  预估入库费用（实测 {:.2f} 字符/token）：".format(字每token))
    print(f"    新增需计算 : {st.字符数:,} 字符 → {st.字符数/字每token:,.0f} token → ¥{st.字符数/字每token*元每token:.4f}")
    print(f"    （已入库内容会走内容指纹缓存，实际费用通常低于此值）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--期", default="第1期", choices=list(P.分期前缀) + ["第6期"],
                    help="用于统计/报费用；★ 入库时一律按全包重建（见 语料管道.py 的事故说明）")
    ap.add_argument("--入库", action="store_true", help="真的写入向量库（会花钱）")
    ap.add_argument("--确认费用", type=float, default=None, help="必须与预估费用匹配才继续")
    ap.add_argument("--保留切片", action="store_true", help="把切片写到 _试跑输出（便于核对）")
    args = ap.parse_args()

    print("=" * 88)
    print(f"扩索引 · 统计期「{args.期}」 ｜ 语料根 {语料根}")
    print("=" * 88)
    print("  ⓘ 分期只用于「统计这一期新增了什么」。**入库一律按全包重建**——")
    print("     因为 入库() 是整体重建，只传新增部分会把原有内容覆盖掉（2026-10-13 实测踩过）。")
    print()

    t0 = time.time()
    块, st = P.扫描并切片(语料根, 期=args.期)
    耗时切片 = time.time() - t0
    print(f"  【本统计期】切片完成，耗时 {耗时切片:.1f} 秒\n")
    打印统计(st, f"统计期「{args.期}」")

    # ★ 入库用的完整集合 = 全包
    块全, st全 = (块, st) if args.期 == "全包" else P.扫描并切片(语料根, 期="全包")
    if args.期 != "全包":
        print("\n" + "=" * 88)
        print("【入库集合 = 全包】（只对缓存未命中的块计费，故费用≈本期新增）")
        print("=" * 88)
        print(f"  全包文件数: {st全.文件数:,} ｜ 块数: {st全.切片数:,} ｜ 字符数: {st全.字符数:,}")

    if args.保留切片 and 块全:
        输出目录.mkdir(parents=True, exist_ok=True)
        out = 输出目录 / f"切片_{args.期}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for b in 块全:
                f.write(json.dumps({
                    "来源文件": b.来源文件, "标题路径": b.标题路径,
                    "起始行": b.起始行, "结束行": b.结束行,
                    "字符数": b.字符数, "文本": b.文本,
                }, ensure_ascii=False) + "\n")
        print(f"\n  切片已写: {out}（{len(块全):,} 块）")

    if not args.入库:
        print("\n  ⓘ 未加 --入库，**本次一分钱未花**（只做了切片，没有向量化）")
        print("     要看真实费用，加 --入库 --确认费用 <预估费用> 再跑一次。")
        return 0

    预估 = st.字符数 / 字每token * 元每token
    if args.确认费用 is None or abs(args.确认费用 - 预估) > max(0.005, 预估 * 0.05):
        print(f"\n  🛑 费用未确认。本期新增预估 ¥{预估:.4f}，请用 --确认费用 {预估:.4f} 明确批准。")
        print("     （本检查防的是「没看数字就开跑」，不是形式主义）")
        return 2

    print(f"\n  费用已确认：本期新增预估 ¥{args.确认费用:.4f}。开始入库（全包 {len(块全):,} 块）…")
    切片字典 = [{
        "来源文件": b.来源文件, "标题路径": b.标题路径,
        "起始行": b.起始行, "结束行": b.结束行,
        "内容指纹": getattr(b, "内容指纹", ""), "字符数": b.字符数, "文本": b.文本,
    } for b in 块全]

    t1 = time.time()
    结果 = K.入库(切片字典, 场景=f"扩索引_{args.期}")
    耗时入库 = time.time() - t1

    print("\n" + "=" * 88)
    print("入库完成")
    print("=" * 88)
    for k, v in 结果.items():
        print(f"  {k}: {v}")
    print(f"  入库耗时: {耗时入库:.1f} 秒")

    # 真实花费（从账本读本次新增，不估算）
    账 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用\data\缓存\用量账本.jsonl")
    if 账.exists():
        rows = [json.loads(l) for l in 账.read_text(encoding="utf-8").splitlines() if l.strip()]
        本次 = [r for r in rows if r.get("场景") == f"扩索引_{args.期}"]
        if 本次:
            花 = sum(r["费用_元"] for r in 本次)
            tk = sum(r["tokens"] for r in 本次)
            print(f"\n  ★ 本次真实花费（账本原始数据）: ¥{花:.6f} ／ {tk:,} token ／ {len(本次)} 次调用")
        print(f"  账本累计: ¥{sum(r['费用_元'] for r in rows):.6f}（{len(rows)} 条记录）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
