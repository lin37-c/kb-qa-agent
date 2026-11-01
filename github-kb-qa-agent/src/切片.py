# -*- coding: utf-8 -*-
"""切片：把长文档切成带出处的小段。

为什么要切片（这是 RAG 的第一步，也是最重要的一步）：
    ① 整篇太长塞不进 LLM 的上下文窗口；
    ② 就算塞得进，一整篇的向量会"什么都沾一点、什么都不准"——检索精度会崩。
    切成小块后，每一块的向量只表达一个具体的点，检索才准。

切法的三条硬约束（本项目语料的实际情况决定的，不是通用教条）：
    ① 按 Markdown 标题层级切 —— 语料本身就是按标题组织的，这是天然的语义边界；
    ② 小段要合并 —— 实测有 6 份规则文件完全没有 ## 标题，最短的只有 363 字符。
       如果"一段就切一块"，会产生大量过碎的小块，检索时噪声大。
    ③ 大段要能二次拆 —— 实测 全局个人规则.md 有 13,444 字符但只有 14 个 ##，
       单段可能上千字符，必须按空行（段落）再拆。

不能被切断的东西（切了就失去意义）：
    · 表格（连续的 | 行）—— 切成两半，表头和表体分家就没法读
    · 代码块（``` 围栏内）—— 切一半代码就废了
    · 因此：解析标题时必须跳过代码块内的 # 行（否则会把代码注释当成标题）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------- 切片参数 ----------
# 目标：每块 400~900 字符。
#   太小（<400）→ 一块讲不清一件事，检索出来信息不足，还要多召回几块；
#   太大（>900）→ 一块混进多个主题，向量被"平均"掉，精度下降。
# 这两个数是先验值，M1 跑完看实际分布再调（参数集中在此，调完重跑靠缓存几乎不花钱）。
最小块字符 = 300
最大块字符 = 900


@dataclass
class 段:
    """一个标题段：从某个标题行开始，到下一个同级/更高级标题之前。"""
    标题路径: list[str] = field(default_factory=list)   # ["3. 优先级", "3.2 ..."] 形式
    起始行: int = 0
    结束行: int = 0
    文本: str = ""


@dataclass
class 切片:
    来源文件: str          # 相对语料根的路径，例如 02_规则/01_全局规则/全局个人规则.md
    标题路径: str          # 用 " > " 连接的标题链，例如 "3. 优先级 > 3.2 ..."
    起始行: int
    结束行: int
    字符数: int
    文本: str


def _是围栏行(line: str) -> bool:
    return line.lstrip().startswith("```") or line.lstrip().startswith("~~~")


def _标题级别(line: str) -> int:
    """返回 ATX 标题级别（1~6）；不是标题返回 0。

    注意：Markdown 规定 # 后必须有空格才算标题，所以 "#标签" 不算。
    """
    m = re.match(r"^(#{1,6})\s+\S", line)
    return len(m.group(1)) if m else 0


def _去标题标记(line: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", line).strip()


def 去掉frontmatter(文本: str) -> tuple[str, int]:
    """去掉开头的 YAML frontmatter（--- 包围的部分），返回（正文, 被去掉的行数）。

    SKILL.md 常见开头是 frontmatter（name/description 等元数据）。
    它照理也是内容，但作为检索块价值低，且会打乱标题层级——所以单独剥离，
    并把它作为"元数据段"的正文前缀一起保留（不丢信息）。

    ★★ 2026-10-18 修（F-86）：原实现 `return "\n".join(lines[i+1:]), i+1` 把
       frontmatter **整段丢掉**，与本注释承诺的"一起保留（不丢信息）"**矛盾**。
       后果：44 个 SKILL.md 的 `description:`（"这个技能干什么"的最权威一句话）
       **全部不可检索** —— 10 道评测题因此永远测不中。
       ⇒ 改为**保留 frontmatter 作为正文前缀**，行数语义不变（总行数一致），
         仍返回其占用行数，供调用方换算行号。
    """
    lines = 文本.split("\n")
    if not lines or lines[0].strip() != "---":
        return 文本, 0
    for i in range(1, min(len(lines), 60)):
        if lines[i].strip() == "---":
            #   ★★ 返回值 2 必须是 **0**：内容已全保留，`解析为段` 拿到的就是
            #      原文全文，行号即原文行号；调用方（切文件）会再加偏移，
            #      再加就偏了（实测偏 5 行）。
            return 文本, 0
    return 文本, 0


def 解析为段(文本: str) -> list[段]:
    """把 Markdown 文本按标题解析成段（跳过代码块内的伪标题）。"""
    lines = 文本.split("\n")
    段列表: list[段] = []
    当前标题路径: list[str] = []
    当前: 段 | None = None
    在围栏内 = False

    def 收尾(结束行: int) -> None:
        nonlocal 当前
        if 当前 is not None:
            当前.结束行 = 结束行
            当前.文本 = "\n".join(当前.文本.split("\n")).strip("\n")
            段列表.append(当前)
            当前 = None

    for idx, line in enumerate(lines, start=1):
        if _是围栏行(line):
            在围栏内 = not 在围栏内
        lv = 0 if 在围栏内 else _标题级别(line)
        if lv:
            收尾(idx - 1)
            当前标题路径 = 当前标题路径[: lv - 1] + [_去标题标记(line)]
            #   ★★ 2026-10-18 修（F-86）：标题行本身也进「文本」。
            #      原实现只把标题放进「标题路径」（元数据），而 `入库.py` 只用
            #      「文本」做向量 ⇒ **所有标题在检索层等于不存在**，
            #      问"某一节讲什么"、JSON 顶层键（`## plugins`）都测不中。
            当前 = 段(标题路径=list(当前标题路径), 起始行=idx, 文本=line + "\n")
        else:
            if 当前 is None:
                当前 = 段(标题路径=list(当前标题路径), 起始行=idx, 文本="")
            当前.文本 += line + "\n"
    收尾(len(lines))
    return [s for s in 段列表 if s.文本.strip()]


def _按空行拆(文本: str) -> list[tuple[str, int, int]]:
    """按空行拆成"块"，但保证代码块与表格不被拆开。

    ★★ 2026-10-18 改（F-86）：返回 `(块文本, 起行偏移, 止行偏移)`。
       原实现只返回字符串，拆完行号信息全丢 ⇒ `切一块` 只能拿"整段"的行范围
       冒充"每块"的行范围（元数据失真，实测 300 字的块标着 9 行）。
       偏移是**相对段首行**的 0 基行号，由调用方加上 `段.起始行` 还原。
    """
    块列表: list[tuple[str, int, int]] = []
    当前: list[str] = []
    起 = 0
    止 = 0
    在围栏内 = False
    上一个是表格行 = False

    def 冲刷(末: int) -> None:
        nonlocal 当前
        if 当前:
            块列表.append(("\n".join(当前), 起, 末))
            当前 = []

    for 序, line in enumerate(文本.split("\n")):
        if not 当前:
            起 = 序
        止 = 序
        if _是围栏行(line):
            在围栏内 = not 在围栏内
            当前.append(line)
            continue
        是表格行 = (not 在围栏内) and line.lstrip().startswith("|")
        if 在围栏内:
            当前.append(line)
            continue
        if line.strip() == "" and not 上一个是表格行:
            冲刷(止 - 1)
        else:
            当前.append(line)
        上一个是表格行 = 是表格行
    冲刷(止)
    return [(t, a, b) for t, a, b in 块列表 if t.strip()]


def _按字符硬拆(文本: str, 上限: int) -> list[str]:
    """最后一级兜底：按字符数硬切，保证**任何块都不超过上限**。

    什么时候会走到这里（2026-10-13 实测）：
        压缩过的前端资源、单行超长 JSON、base64 大块等 —— **整个文件一行**，
        `_按行硬拆` 无法降级。实测 `chart.umd.min.js` 一块达 **196,751 字符**，
        导致 embedding 接口报 `HTTP 400 code 1210`，全包入库失败。

    切法：优先在**语义较弱的边界**下刀，找不到才纯按长度切：
        ① 分号 `;`（JS/CSS 语句边界）
        ② 逗号 `,`
        ③ 空白
        ④ 都没有 → 纯按字符数
    这样做的好处：切出来的块仍尽量落在语句边界上，比"每 900 字符一刀"可读。

    代价（如实记录）：**一个语义单元被切开**。但相比"整块进不了库"，
    这是唯一不丢内容的选择——**信息可以简化，不能缺席**。
    """
    结果: list[str] = []
    起点 = 0
    n = len(文本)
    while 起点 < n:
        终点 = min(起点 + 上限, n)
        if 终点 < n:
            # 在末尾 15% 的窗口里找一个较好的切点
            窗口起 = max(起点 + int(上限 * 0.85), 起点 + 1)
            段 = 文本[窗口起:终点]
            切点 = -1
            for 候选 in (";", "}", ",", " "):
                k = 段.rfind(候选)
                if k >= 0:
                    切点 = 窗口起 + k + 1
                    break
            if 切点 > 起点:
                终点 = 切点
        块 = 文本[起点:终点]
        if 块.strip():
            结果.append(块)
        起点 = 终点
    return 结果


def _按行硬拆(文本: str, 上限: int) -> list[tuple[str, int, int]]:
    """按行累积打包，保证单块尽量不超过上限。

    保护规则：代码块与表格内部不切开。
    附带策略（M1 试跑第二轮实测加入）：遇到一个"不可切区域"（代码块/表格）
    本身就超过上限时，**先把缓冲区吐出去**，让它独占一块。
    否则前面已攒的普通内容会把这 3000 字符的表越顶越高（实测有块达 6245 字符）。
    代价：该不可切区域仍会超过上限，但这是唯一不破坏结构的选择。

    ★★ 2026-10-18 改（F-86）：返回 `(块文本, 起行偏移, 止行偏移)`，
       与 `_按空行拆` 同口径，供块级行号还原。
    """
    结果: list[tuple[str, int, int]] = []
    缓冲: list[str] = []
    缓冲长 = 0
    缓冲起 = 0
    缓冲止 = 0
    在围栏内 = False
    上一个是表格行 = False

    def 冲刷(末: int) -> None:
        nonlocal 缓冲, 缓冲长
        if 缓冲:
            t = "\n".join(缓冲).strip("\n")
            if t.strip():
                结果.append((t, 缓冲起, 末))
            缓冲, 缓冲长 = [], 0

    lines = 文本.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if _是围栏行(line):
            在围栏内 = not 在围栏内
        是表格行 = (not 在围栏内) and line.lstrip().startswith("|")
        不可切 = 在围栏内 or 是表格行 or 上一个是表格行

        if 不可切 and not 缓冲:
            # 缓冲区为空且当前行不可切 → 收集整个不可切区域，测它的实际长度
            区: list[str] = []
            围栏内2 = 在围栏内
            上一表 = False
            j = i
            while j < len(lines):
                ln = lines[j]
                if _是围栏行(ln):
                    围栏内2 = not 围栏内2
                t2 = (not 围栏内2) and ln.lstrip().startswith("|")
                可切 = (not 围栏内2) and (not t2) and (not 上一表)
                if 区 and 可切:
                    break
                区.append(ln)
                上一表 = t2
                j += 1
            区长 = sum(len(x) + 1 for x in 区)
            if 区长 > 上限:
                t = "\n".join(区).strip("\n")
                if t.strip():
                    结果.append((t, i, j - 1))
                i = j
                在围栏内 = False
                上一个是表格行 = False
                continue

        if not 缓冲:
            缓冲起 = i
        缓冲止 = i
        if 缓冲 and not 不可切 and 缓冲长 + len(line) + 1 > 上限:
            冲刷(i - 1)
            缓冲起 = i
        缓冲.append(line)
        缓冲长 += len(line) + 1
        上一个是表格行 = 是表格行
        i += 1
    冲刷(缓冲止)
    return 结果


def _是垃圾块(文本: str) -> bool:
    """判断是否为无检索价值的碎片。

    M1 试跑实测发现的问题：文件里的水平分隔线（---）会被单独切成一块，
    内容只有 "---"（4 字符）。这类块没有任何语义，只会污染检索结果。
    判定：去掉空行后，剩余内容全部由 -、*、_、= 这类分隔符组成，或长度过短。
    """
    实质 = "".join(文本.split())
    if len(实质) < 20:
        return True
    return all(ch in "-*_=#>\u3000 \t" for ch in 实质)


def _是独立块(块文本: str) -> bool:
    """判断一块是否为"不可再合并"的独立块。

    M1 试跑第三轮实测发现的坑：
        _按行硬拆 已经把超大的表格/代码块吐成独立块了，
        但外层"尽量填满"的打包逻辑又把它和相邻内容合并回去，
        结果超限块数一点没降（24 块，最大 6245 字符）。
    判定依据：整块由表格行构成，或由代码围栏包住（去掉空白后以 ``` 开头）。
    """
    lines = [ln for ln in 块文本.split("\n") if ln.strip()]
    if not lines:
        return False
    表 = sum(1 for ln in lines if ln.lstrip().startswith("|"))
    if 表 >= len(lines) * 0.8:
        return True
    s = 块文本.strip()
    return s.startswith("```") or s.startswith("~~~")


def 切一块(段: 段, 来源文件: str) -> list[切片]:
    """把单个段转成切片；超长则先按空行、再按行兜底二次拆。"""
    标题路径 = " > ".join(段.标题路径)
    if len(段.文本) <= 最大块字符:
        return [
            切片(
                来源文件=来源文件,
                标题路径=标题路径,
                起始行=段.起始行,
                结束行=段.结束行,
                字符数=len(段.文本),
                文本=段.文本,
            )
        ]

    # 超长：先按空行块打包，超上限的空行块再按行硬拆
    # ★ 第三级兜底「按字符硬拆」（2026-10-13 扩建全资产包时加的，实测触发）：
    #   前两级都依赖"文本里有换行"。压缩过的前端资源（如 `chart.umd.min.js`）
    #   **整个文件就是一行**，`_按行硬拆` 拿它没办法 → 吐出 **196,751 字符**的块
    #   → 超过 embedding 模型输入上限 → 接口返回 `HTTP 400 code 1210`，**全包入库直接失败**。
    #   教训：`02_规则` 全是 `.md`（一定有换行），所以 M1 四轮实测从未暴露这个问题；
    #   一扩到 `.js`／压缩产物就炸。**分期扩索引的价值就在这里——小额代价提前发现。**
    细化: list[tuple[str, int, int]] = []      # ★ (文本, 起行偏移, 止行偏移)
    for b, ba, bz in _按空行拆(段.文本):
        if len(b) <= 最大块字符:
            细化.append((b, ba, bz))
            continue
        for x, xa, xz in _按行硬拆(b, 最大块字符):
            # 行拆后仍超上限 → 说明存在"超长单行"，只能按字符数硬切
            if len(x) > 最大块字符:
                #   ★ 按字符硬切的是**同一行**的不同片段，行号相同
                for y in _按字符硬拆(x, 最大块字符):
                    细化.append((y, ba + xa, ba + xz))
            else:
                细化.append((x, ba + xa, ba + xz))

    # 打包：尽量填满，但"独立块"（整块表格/代码）不与相邻内容合并
    结果: list[切片] = []
    缓冲: list[str] = []
    缓冲长 = 0
    缓冲起 = 0
    缓冲止 = 0

    def 吐() -> None:
        nonlocal 缓冲, 缓冲长
        if 缓冲:
            文本 = "\n\n".join(缓冲)
            结果.append(
                切片(来源文件, 标题路径, 段.起始行 + 缓冲起, 段.起始行 + 缓冲止, len(文本), 文本)
            )
            缓冲, 缓冲长 = [], 0

    for 块, 起, 止 in 细化:
        if _是独立块(块):
            吐()
            结果.append(
                切片(来源文件, 标题路径, 段.起始行 + 起, 段.起始行 + 止, len(块), 块)
            )
            continue
        if 缓冲 and 缓冲长 + len(块) + 2 > 最大块字符:
            吐()
        if not 缓冲:
            缓冲起 = 起
        缓冲止 = 止
        缓冲.append(块)
        缓冲长 += len(块) + 2
    吐()
    return 结果


def 切文件(路径: Path, 语料根: Path) -> list[切片]:
    """切一个 Markdown 文件。"""
    原文 = 路径.read_text(encoding="utf-8")
    正文, 偏移 = 去掉frontmatter(原文)
    段列表 = 解析为段(正文)
    if not 段列表:
        return []
    相对 = 路径.relative_to(语料根).as_posix()

    单段结果: list[切片] = []
    for s in 段列表:
        s.起始行 += 偏移
        s.结束行 += 偏移
        单段结果.extend(切一块(s, 相对))

    # 过滤纯装饰性碎片（水平分隔线等）—— 见 _是垃圾块 的说明
    单段结果 = [b for b in 单段结果 if not _是垃圾块(b.文本)]

    # 合并过短的相邻块（同一标题路径下、合计不超上限）
    合并后: list[切片] = []
    for 块 in 单段结果:
        if (
            合并后
            and 合并后[-1].标题路径 == 块.标题路径
            and 合并后[-1].字符数 < 最小块字符
            and 合并后[-1].字符数 + 块.字符数 <= 最大块字符
        ):
            前 = 合并后[-1]
            前.文本 = 前.文本 + "\n\n" + 块.文本
            前.字符数 = len(前.文本)
            前.结束行 = 块.结束行
        else:
            合并后.append(块)
    return 合并后


def 扫描语料(语料根: Path, 模式: list[tuple[str, str]]) -> list[Path]:
    """按（子目录, 文件名模式）清单收集要切的文件。

    模式示例：[("02_规则", "*.md"), ("01_技能", "SKILL.md")]
    统一排除 _维护工作区 与 node_modules。
    """
    文件: list[Path] = []
    for 子目录, 匹配 in 模式:
        基 = 语料根 / 子目录
        if not 基.exists():
            continue
        for p in sorted(基.rglob(匹配)):
            if not p.is_file():
                continue
            s = p.as_posix()
            if "_维护工作区" in s or "node_modules" in s:
                continue
            文件.append(p)
    # 去重（例如同时命中 SKILL.md 与 *.md 时）
    return sorted(set(文件))
