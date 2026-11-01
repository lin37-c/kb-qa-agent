# -*- coding: utf-8 -*-
"""原文定位（M8 第 5 步）：按「来源文件 ＋ 行号」取出原文片段，并给出一致性结论。

三条硬规则：
    ① **只读**：不写语料包一个字节；
    ② **只认语料根下的路径**：拒绝绝对路径、`..`、符号链接越界 —— 接口只接受 job 与编号，
       路径永远由服务端从任务里取，不从客户端来；
    ③ **一致性必须给结论，不许含糊**：四态之一（一致／一致含缓冲／无法逐字定位／不一致），
       并且**指纹独立再核一遍**（块文本 sha256 前 16 位 vs 元数据里的内容指纹）。

为什么行范围经常"不逐字相等"（如实写）：
    切片会对超长段落做"按空行拆 → 按行硬拆 → 按字符硬切"，块的行区间可能是**缓冲区**，
    因此文件区间可能比块文本多几行。这时判"一致（含缓冲/合并）"，而不是硬说"不一致"。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import 配置
from 语料管道 import 结构化扩展, 结构化转文本

编码候选 = ("utf-8", "utf-8-sig", "gbk")


def _在语料根内(路径: Path) -> bool:
    根 = 配置.语料根.resolve()
    try:
        路径.resolve().relative_to(根)
    except ValueError:
        return False
    return True


def 读文本行(路径: Path) -> tuple[list[str], str]:
    """读成行。★ `.json` 必须走**与入库同一套**转换（结构化转文本）。

    为什么（2026-10-26 实测撞到）：
        入库前 `语料管道.结构化转文本()` 会把 JSON 重写成「键：值」的可读文本再切片，
        所以元数据里的行号是**派生文本**的行号。直接读原文件会显示**完全不相干的行** ——
        20 条实测里有 2 条（都是 JSON）栽在这上面。
    """
    if 路径.suffix.lower() in 结构化扩展:
        return 结构化转文本(路径).splitlines(), "派生（json→可读）"
    原始 = 路径.read_bytes()
    for 编码 in 编码候选:
        try:
            return 原始.decode(编码).splitlines(), 编码
        except UnicodeDecodeError:
            continue
    return 原始.decode("utf-8", errors="replace").splitlines(), "utf-8(replace)"


def _归一(行们: list[str]) -> list[str]:
    return [x.rstrip() for x in 行们 if x.strip()]


def _含子序列(长: list[str], 短: list[str]) -> bool:
    i = 0
    for x in 长:
        if i < len(短) and x == 短[i]:
            i += 1
    return i == len(短)


def 取片段(来源文件: str, 起始行: int, 结束行: int, 块文本: str,
           内容指纹: str = "", 上下文: int = 20) -> dict:
    """返回界面契约 §10.3 的结构；出错时返回 `{"码":…, "错误":…}`。"""
    根 = 配置.语料根
    相对 = str(来源文件 or "").replace("\\", "/").lstrip("/")
    if not 相对:
        return {"码": "BAD_PATH", "错误": "来源文件为空"}
    路径 = 根 / 相对
    if not _在语料根内(路径):
        return {"码": "BAD_PATH", "错误": f"路径越界（不在语料根下）：{相对}"}
    if not 路径.is_file():
        return {"码": "NOT_FOUND", "错误": f"文件不存在：{相对}"}

    行们, 编码 = 读文本行(路径)
    总行 = len(行们)
    if 总行 == 0:
        return {"码": "EMPTY", "错误": f"文件为空：{相对}"}

    起 = max(1, min(int(起始行 or 1), 总行))
    止 = max(起, min(int(结束行 or 起), 总行))
    上 = max(1, 起 - 上下文)
    下 = min(总行, 止 + 上下文)
    行 = [{"号": i, "文": 行们[i - 1], "引用": 起 <= i <= 止} for i in range(上, 下 + 1)]

    文件段 = _归一(行们[起 - 1:止])
    块段 = _归一((块文本 or "").splitlines())

    if 文件段 == 块段:
        行范围, 说明 = "一致", "逐行归一化比对一致"
    elif 块段 and _含子序列(文件段, 块段):
        行范围, 说明 = ("一致（含缓冲/合并）",
                    f"文件段 {len(文件段)} 行包含块 {len(块段)} 行（切片缓冲或合并所致）")
    elif 块段:
        重合 = len(set(文件段) & set(块段)) / max(1, len(块段))
        if 重合 >= 0.5:
            行范围, 说明 = "无法逐字定位", f"块内行只有 {重合:.0%} 出现在该行区间（切片边界或原文已变）"
        else:
            行范围, 说明 = "不一致", f"块内行只有 {重合:.0%} 出现在该行区间，原文可能已改"
    else:
        行范围, 说明 = "无法逐字定位", "块文本为空"

    if 内容指纹:
        算 = hashlib.sha256((块文本 or "").encode("utf-8")).hexdigest()[:16]
        指纹 = "一致" if 算 == 内容指纹 else "不一致"
    else:
        指纹 = "未提供"

    派生 = 路径.suffix.lower() in 结构化扩展
    if 派生:
        说明 += "（该文件是 JSON，入库前已转成可读文本；这里的行号按**派生文本**计，不等于原文件行号）"

    return {
        "来源文件": 相对,
        "派生文本": 派生,
        "范围": {"起": 起, "止": 止},
        "上下文": {"起": 上, "止": 下},
        "行": 行,
        "一致性": {"行范围": 行范围, "指纹": 指纹, "说明": 说明},
        "编码": 编码,
        "总行": 总行,
    }
