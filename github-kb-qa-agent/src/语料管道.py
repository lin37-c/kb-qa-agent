# -*- coding: utf-8 -*-
"""语料管道：把「整个资产包」按类型送进切片器，产出统一的切片列表。

为什么单独一个模块（不直接改 `切片.py`）：
    `切片.py` 已经过 M1 四轮实测、已发布、行为稳定。它只处理 Markdown 一种文本。
    扩建整个资产包要引入**三种新的处理方式**，混进去会让那个模块同时承担两件事。
    所以：**`切片.py` 保持"切一段 Markdown"的职责不变；本模块负责"决定什么该切、
    以及非 Markdown 内容怎么转成可切的文本"。**

入什么（判据由用户 2026-10-13 定）：
    **判据只有一条 —— 内容是不是用户的？是 → 入。**
    · "会不会变" 不是判据（规则、状态都是用户的，都会变）
    · "读不成文字" 不是排除理由，而是"换一种形式入"（目录条目）
    · 唯一允许排除的两类：
        ① 第三方依赖源码（不是用户的知识）
        ② 0 字节空文件（无内容可入）

三种处理方式：
    ① 全文类（.md/.py/.yaml/.txt/.mjs/.sh/.ps1/.swift/.html/.css/.csv…）
       → 直接交给 `切片.切文件()` 按 Markdown/文本规则切。
    ② 结构化类（.json/.yaml 里的大清单）
       → **先转成可读文本再切**。原因（实测）：直接按行切 JSON 会产出大量
         "路径 + 哈希"碎片，检索时毫无意义（实测 `收尾核对记录.json` 523 KB
         按行切会出几千块这种碎片）。
         转法：顶层键 → 「### 键名」小节；值按类型渲染成行；大数组按元素分行。
    ③ 二进制类（.png/.svg/.pdf/.tgz…）
       → **入目录条目**：一个文件切一块，内容是"路径 + 名称 + 类型 + 大小 + 说明"。
         目的：让"资产包里有没有这张图/这个包"这类问题**可被回答**。
         **信息可以简化，但不能缺席。**

对外主函数：`扫描并切片(范围=...)` → 返回 `(切片列表, 统计)`

--- 2026-10-13 事故与修正：分期必须是「累积」，不是「替换」 ---

**事故**：第一次跑第 1 期时，我把「第 1 期」的切片（159 块）**单独**交给 `入库()`，
结果 `入库()` 按它**整体重建**，把原有 1,184 块**覆盖掉了**（库从 13.27 MB 变成 1.78 MB）。

**根因**：`入库()` 的设计是**整体重建**（理由见它的 docstring：元数据与向量按行号
一一对应，增量追加会错位）。**而分期扩索引的正确语义是"库里始终是已完成的全部"**——
第 1 期入库时，交给 `入库()` 的必须是「**原有 68 个文件的切片 ＋ 05_维护工具的切片**」，
是**完整集合**，不是只有新增那部分。

**修正**：`扫描并切片(期=...)` 只用来**统计"这一期新增了什么"**（报费用、做对照）；
**真正入库时一律传"全包"**（`期="全包"`）——`入库()` 只对内容指纹未命中的块计费，
所以"全包重建"的实际花费**等于**只算新增部分，而库始终完整、不会丢东西。

**代价对比**：全包重建每次要重写两个本地文件（约 1,200 万字符 → 向量 CSV 上百 MB），
耗时约半分钟；换来的是**永远不会把库搞丢**。这个交换值得。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 依赖 `切片.py`。**必须在 import 之前确保候选区排在 sys.path 最前**——
# 否则会 import 到正式位置那份，等于测的不是正在改的代码。
# （调用方 `试跑_扩索引.py` 已经做了这件事；这里再兜一次底，并断言来源。）
_本目录 = str(Path(__file__).resolve().parent)
while _本目录 in sys.path:
    sys.path.remove(_本目录)
sys.path.insert(0, _本目录)

import 切片 as S
from 切片 import 切片 as 切片类

# ---------- 排除规则 ----------
# ① 第三方依赖源码（不是用户的知识）
排除目录名 = {"node_modules", ".git", "__pycache__", ".venv", "venv",
           ".mypy_cache", ".pytest_cache", ".idea", ".vscode"}

# ---------- ② 「台账类」不再排除（2026-10-14 用户裁定后撤销）----------
#
# **变更记录（重要）**：
#   2026-10-14 上午曾按"方案 A"把台账类 JSON 排除出索引；**当天即撤销**。
#
# **撤销原因（用户裁定）**：
#   用户明确「**「资产包里有哪些文件／来源」这类问题要答**」。
#   而台账类 JSON（`来源与适配清单.json`／`当前资产清单.json`／`_meta.json` 等）
#   正是回答这个问题的**唯一数据源** —— 排除它们等于把这项能力删掉。
#
# **改为"保留 ＋ 检索时降权"**（降权实现在 `检索.py`，不在本模块）：
#   · 台账类**照常入库**（可被检索到 → "资产包有哪些文件/来源"可答）
#   · 检索时给它们**降权**，而且降权**参与"定房间"的分数计算** ——
#     这才是「浏览器怎么自动化操作」被卡住的真堵点：
#       那个 JSON 拿到 0.6506 ≥ 阈值_高 0.58 → 默认组判"已达可信命中" → 不切房间
#       降权后 0.6506 × 0.85 = 0.553 < 0.58 → 触发切房间 → 技能库的真答案浮上来
#
# ---------- ③ 撤销「包内资源」整段排除（2026-10-14 修正）----------
#
# **原错误**：曾用 `"03_依赖资源/包内资源/"` 整段路径前缀排除，把
#   `codex-security/references/`（12 md 使用文档）、`scripts/`（40 py 技能脚本）、
#   `browser-automation/`（2 个脚本）等**用户技能知识**一起扫掉了。
# **实测依据**：该目录下只有 `browser/scripts/node_modules/` 是第三方库 ——
#   **已被通用 `node_modules` 规则排除**，不需要再整段排。
# **修正**：删掉该路径前缀，靠通用 `排除目录名` 精准排除第三方库。
是台账类 = None   # 保留符号位（历史引用），实际不再使用 —— 见上方变更记录

结构化扩展 = {".json"}

结构化扩展 = {".json"}
二进制扩展 = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".tgz", ".gz",
           ".tar", ".zip", ".ico", ".bmp", ".woff", ".woff2", ".ttf", ".otf",
           ".mp3", ".mp4", ".mov", ".wav", ".xlsx", ".docx", ".pptx", ".db",
           ".sqlite", ".bin", ".exe", ".dll", ".so", ".dylib", ".tgz", ".node"}
# 文本类扩展名：直接判为文本，不做解码探测（见 分类() 里的 bug 说明）
文本扩展 = {".md", ".py", ".yaml", ".yml", ".txt", ".mjs", ".js", ".sh", ".ps1",
          ".swift", ".html", ".css", ".csv", ".tsv", ".toml", ".ini", ".cfg",
          ".conf", ".cmd", ".bat", ".jsonl", ".log"}

# 分期定义：期名 → 该期包含哪些相对路径前缀（None = 全包，用于一次性跑）
分期前缀: dict[str, tuple[str, ...] | None] = {
    "全包": None,
    "第1期": ("05_维护工具/",),
    "第2期": ("05_维护工具/", "06_插件/"),
    "第3期": ("05_维护工具/", "06_插件/", "03_技能目录与依赖/"),
    "第4期": ("05_维护工具/", "06_插件/", "03_技能目录与依赖/", "_维护工作区/"),
    "第5期": ("05_维护工具/", "06_插件/", "03_技能目录与依赖/", "_维护工作区/",
             "01_技能/"),          # 01_技能 内部再按 references 细分见下
    "第7期": ("05_维护工具/", "06_插件/", "03_技能目录与依赖/", "_维护工作区/"),
}


def 分类(p: Path) -> str | None:
    """返回 全文 / 结构化 / 二进制 / None（排除）。"""
    try:
        if p.stat().st_size == 0:
            return None                     # 唯一允许的"无内容"排除
    except OSError:
        return None
    e = p.suffix.lower()
    if e in 结构化扩展:
        return "结构化"
    if e in 二进制扩展:
        return "二进制"

    # ★ 已知文本类扩展名 → 直接判为文本，**不做解码探测**。
    #
    # 为什么必须这样（2026-10-14 修的真实 bug，影响 37 个文件）：
    #   原实现是「读前 4096 字节试 decode('utf-8')，失败就当二进制」。
    #   而 **4096 字节很可能正好切在一个中文字符的中间** → 抛
    #   `UnicodeDecodeError: unexpected end of data` → **把一个完全正常的
    #   中文 Markdown 误判成二进制** → 只产出一条"目录条目"，正文全部丢失。
    #
    #   实测受害者（37 个文件，含最关键的几份）：
    #     · `04_来源版本与校验/03_维护与改进/分歧与改进记录.md`（158 KB）
    #       —— **14 条禁令的完整定义**（发现 F-2 的根因就在这份文件里）
    #     · `维护规则.md`（54 KB）、`test-column-rules.md`（28 KB）
    #     · 13 个技能的 `SKILL.md`、大量 `references/*.md`
    #   后果实证：「禁令 P-14 说的是什么」从旧库的 0.7188 掉到 0.5267，
    #   前 10 名里**根本没有禁令定义** —— 不是排序问题，是**内容不在库里**。
    #
    # 修正后：扩展名已知是文本的，一律按文本处理；只有未知扩展名才做探测，
    # 且探测时**读全文件并用 errors='ignore'** —— 目的是识别"含 NUL 的真二进制"，
    # 而不是校验编码是否严格合法。
    if e in 文本扩展:
        return "全文"

    # 未知扩展名：探测是不是二进制。判据是"有没有 NUL 字节"，不是"编码合不合法"。
    try:
        raw = p.read_bytes()
        if b"\x00" in raw[:8192]:
            return "二进制"
        raw.decode("utf-8", errors="ignore")
        return "全文"
    except Exception:  # noqa: BLE001
        return "二进制"


def 被排除(相对: str) -> str | None:
    parts = Path(相对).parts
    for d in parts:
        if d in 排除目录名:
            return f"第三方依赖源码（{d}）"
    return None


# ---------- 结构化（JSON）转可读文本 ----------
def _渲染值(v, 缩进: int = 0) -> list[str]:
    """把一个 JSON 值渲染成可读行。"""
    缩 = "  " * 缩进
    if v is None:
        return [f"{缩}（空）"]
    if isinstance(v, bool):
        return [f"{缩}{'是' if v else '否'}"]
    if isinstance(v, (int, float)):
        return [f"{缩}{v}"]
    if isinstance(v, str):
        if "\n" in v:
            return [缩 + x for x in v.split("\n")]
        return [f"{缩}{v}"]
    if isinstance(v, list):
        行 = [f"{缩}共 {len(v)} 项"]
        for i, x in enumerate(v):
            子 = _渲染值(x, 缩进 + 1)
            if 子:
                子[0] = f"{缩}- [{i}] " + 子[0].strip()
            行.extend(子)
        return 行
    if isinstance(v, dict):
        行 = []
        for k, x in v.items():
            子 = _渲染值(x, 缩进 + 1)
            if len(子) == 1:
                行.append(f"{缩}{k}：{子[0].strip()}")
            else:
                行.append(f"{缩}### {k}")
                行.extend(子)
        return 行
    return [f"{缩}{v!r}"]


def 结构化转文本(p: Path) -> str:
    """把 JSON 转成"键→值"可读文本（顶层键成小节）。

    为什么这样转：让每一条信息都**带得上它自己的键名**，
    这样向量里就含有"这个字段叫什么"，问"上次清理删了哪些文件"才可能命中到
    那个 files 数组，而不是命中一堆无名的路径串。
    """
    原文 = p.read_text(encoding="utf-8", errors="ignore")
    try:
        j = json.loads(原文)
    except Exception:  # noqa: BLE001
        # 解析不了就原样返回（宁可切出噪声，也不要丢内容）
        return 原文
    行 = [f"# {p.name}", ""]
    if isinstance(j, dict):
        for k, v in j.items():
            行.append(f"## {k}")
            行.extend(_渲染值(v, 1))
            行.append("")
    else:
        行.extend(_渲染值(j))
    return "\n".join(行)


# ---------- 二进制：目录条目 ----------
人类可读类型 = {
    ".png": "图片", ".jpg": "图片", ".jpeg": "图片", ".gif": "图片", ".webp": "图片",
    ".svg": "矢量图", ".pdf": "PDF 文档", ".tgz": "压缩包", ".gz": "压缩包",
    ".tar": "压缩包", ".zip": "压缩包", ".ico": "图标", ".bmp": "图片",
    ".woff": "字体", ".woff2": "字体", ".ttf": "字体", ".otf": "字体",
    ".mp3": "音频", ".mp4": "视频", ".xlsx": "Excel 表", ".docx": "Word 文档",
    ".pptx": "PPT", ".db": "数据库", ".sqlite": "数据库",
}


def 目录条目(p: Path, 语料根: Path) -> 切片类:
    """把一个二进制文件表示成"可被检索的一小块"。"""
    相对 = p.relative_to(语料根).as_posix()
    大小 = p.stat().st_size
    类型 = 人类可读类型.get(p.suffix.lower(), "二进制文件")
    if 大小 < 1024:
        体积 = f"{大小} 字节"
    elif 大小 < 1024 * 1024:
        体积 = f"{大小 / 1024:.1f} KB"
    else:
        体积 = f"{大小 / 1024 / 1024:.2f} MB"
    # 标题路径取它所在的目录链，便于按目录归类检索
    目录链 = " > ".join(Path(相对).parts[:-1]) or "(语料根)"
    文本 = (f"【{类型}】{p.name}\n"
            f"位置：{相对}\n"
            f"所在目录：{目录链}\n"
            f"体积：{体积}\n"
            f"说明：这是资产包内的一个{类型}，内容未纳入文本索引；"
            f"此条目用于让「这个文件在不在、放在哪」可被检索到。")
    return 切片类(
        来源文件=相对,
        标题路径=f"{目录链} > {p.name}",
        起始行=1,
        结束行=1,
        文本=文本,
        字符数=len(文本),
    )


# ---------- 主流程 ----------
@dataclass
class 统计:
    文件数: int = 0
    切片数: int = 0
    字符数: int = 0
    全文文件: int = 0
    结构化文件: int = 0
    二进制文件: int = 0
    垃圾块过滤: int = 0
    失败: list = field(default_factory=list)
    按类型: dict = field(default_factory=dict)
    按顶层: dict = field(default_factory=dict)
    跳过: dict = field(default_factory=dict)      # 排除原因 → 文件数
    台账明细: list = field(default_factory=list)   # 被排除的台账类文件清单（可核对）


def 扫描并切片(语料根: Path, 期: str = "全包", 只在: tuple[str, ...] | None = None,
            输出目录: Path | None = None) -> tuple[list[切片类], 统计]:
    """按分期范围扫描全包并切片。

    参数
        期   : `分期前缀` 里的期名（决定默认取哪些顶层目录）
        只在 : 直接指定要哪些顶层前缀（覆盖"期"）；空元组 = 全包
    """
    前缀 = 只在 if 只在 is not None else 分期前缀.get(期, None)
    统计_ = 统计()
    全部切片: list[切片类] = []
    跳过: dict[str, int] = {}
    台账明细: list[str] = []

    for p in sorted(语料根.rglob("*")):
        if not p.is_file():
            continue
        相对 = p.relative_to(语料根).as_posix()
        排 = 被排除(相对)
        if 排:
            跳过[排] = 跳过.get(排, 0) + 1
            continue
        # 台账类**不再排除**（2026-10-14 用户裁定撤销）——它们必须能被检索到，
        # 才能回答「资产包里有哪些文件／来源」。降权改在 `检索.py` 做。
        if 前缀 is not None:
            顶层 = 相对.split("/")[0] if "/" in 相对 else ""
            命中 = any(相对.startswith(x) or (x == "" and "/" not in 相对) for x in 前缀)
            # 01_技能 在"第5期"里只取 references（其余留给第6期）
            if 期 == "第5期" and 相对.startswith("01_技能/") and "/references/" not in 相对:
                命中 = False
            if 期 == "第6期" and 相对.startswith("01_技能/") and "/references/" in 相对:
                命中 = False
            if not 命中:
                continue

        类 = 分类(p)
        if 类 is None:
            跳过["空文件（0 字节，无内容可入）"] = 跳过.get("空文件（0 字节，无内容可入）", 0) + 1
            continue

        统计_.文件数 += 1
        try:
            if 类 == "二进制":
                块 = [目录条目(p, 语料根)]
                统计_.二进制文件 += 1
            elif 类 == "结构化":
                文本 = 结构化转文本(p)
                # 转出来的文本当作"一段 Markdown"再走标准切片，保留同样的边界规则
                块 = _切文本(文本, 相对)
                统计_.结构化文件 += 1
            else:
                块 = S.切文件(p, 语料根)
                统计_.全文文件 += 1
        except Exception as e:  # noqa: BLE001
            统计_.失败.append((相对, f"{type(e).__name__}: {e}"))
            continue

        全部切片.extend(块)
        统计_.切片数 += len(块)
        统计_.字符数 += sum(b.字符数 for b in 块)
        统计_.按类型[类] = 统计_.按类型.get(类, 0) + 1
        顶层 = 相对.split("/")[0] if "/" in 相对 else "(根目录)"
        统计_.按顶层[顶层] = 统计_.按顶层.get(顶层, 0) + len(块)

    统计_.跳过 = 跳过
    统计_.台账明细 = 台账明细
    return 全部切片, 统计_


def _切文本(文本: str, 相对路径: str) -> list[切片类]:
    """把一段已转好的文本按标准规则切块（复用 切片.py 的边界与合并逻辑）。"""
    import tempfile
    临时目录 = Path(tempfile.mkdtemp(prefix="语料管道_"))
    临时 = 临时目录 / "内容.md"
    临时.write_text(文本, encoding="utf-8")
    try:
        块 = S.切文件(临时, 临时目录)
    finally:
        临时.unlink(missing_ok=True)
        临时目录.rmdir()
    # 来源文件要写回真实路径，而不是临时文件名
    for b in 块:
        b.来源文件 = 相对路径
    return 块
