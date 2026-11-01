# -*- coding: utf-8 -*-
"""S1｜恢复点维护：把「落改前恢复点」做成可被工具调用的能力（P-12 的落地）。

--------------------------------------------------------------------------
它和《禁令》P-12 的关系
--------------------------------------------------------------------------
P-12 原文要求：改动任何文件前**必须**落改前恢复点 —— **完整副本 ＋ 基线哈希 ＋ 当场回读核对**，
且**用户已授权也不豁免**（授权解决"该不该改"，恢复点解决"改错了能不能退"）。

本模块把这三件事做成一个原子动作，**把"当场回读"变成硬判据**：
回读不一致就**不返回成功**（而不是像手写流程那样"日志说成功就算成功"）。
依据是发现 **G-3**：脚本打印了"已复制 13 个文件"，但**清单 JSON 其实没写出来** ——
**只看日志就会误判成功**。

--------------------------------------------------------------------------
为什么放在候选区（本阶段纪律）
--------------------------------------------------------------------------
用户 2026-10-14 明确：「**候选是让你保证自己不会出错，且出错也能进行修改的地方**」。
所以阶段 3 的代码**先落候选区**，验证通过 → 四项确认 → 用户批准 → 才发布到正式 `src\`。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# 默认恢复点根（本项目约定：与"项目"同级，见 AGENTS.md 风险 0）
默认恢复点根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\恢复点")
# 不纳入恢复点的目录（可重建的运行产物／虚拟环境／缓存）
默认排除 = (".venv", "__pycache__", "node_modules", ".git")


def 文件sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for 块 in iter(lambda: f.read(1 << 20), b""):
            h.update(块)
    return h.hexdigest()


def _收集(目标根: Path, 范围: list[str], 排除: tuple[str, ...]) -> list[Path]:
    """把"范围"展开成文件清单。范围可以是文件或目录（目录按 rglob 展开）。"""
    出: list[Path] = []
    for r in 范围:
        p = (目标根 / r) if not Path(r).is_absolute() else Path(r)
        if p.is_file():
            出.append(p)
        elif p.is_dir():
            for x in sorted(p.rglob("*")):
                if x.is_file() and not any(部 in 排除 for 部 in x.parts):
                    出.append(x)
        else:
            出.append(p)      # 不存在的路径留给调用方判定（下面会报错）
    return 出


def 落恢复点(名称: str,
           目标根: str,
           范围: list[str],
           恢复点根: str | None = None,
           排除: list[str] | None = None,
           备注: str = "") -> dict:
    """落一份改前恢复点。**回读不一致就不算成功**。

    参数
        名称    : 恢复点目录名，如 `LLM知识库检索与工具调用_阶段3开工前_20261014`
        目标根  : 被保护文件所在的那一层（如项目根、或 `<workspace>\\00_资产`）
        范围    : 目标根下的相对路径列表（文件或目录）；也可以是绝对路径
        恢复点根 : 不填则用本项目默认
        排除    : 不纳入的目录名；不填用默认四类
        备注    : 写进基线清单，便于以后看懂"这份是保护什么的"

    返回 `{ok, 数据, 证据, 说明}`；失败时 `ok=False` 且**不留下半成品成功态**。
    """
    恢复点根 = Path(恢复点根) if 恢复点根 else 默认恢复点根
    目标根 = Path(目标根)
    排除t = tuple(排除) if 排除 else 默认排除
    根 = 恢复点根 / 名称

    if not 目标根.exists():
        return {"ok": False, "说明": f"目标根不存在：{目标根}", "数据": {}, "证据": []}
    if 根.exists():
        return {"ok": False, "说明": f"恢复点已存在，不覆盖：{根}（如要校验请用 校验恢复点()）",
                "数据": {}, "证据": []}

    文件 = _收集(目标根, 范围, 排除t)
    缺 = [str(x) for x in 文件 if not x.exists()]
    if 缺:
        return {"ok": False, "说明": f"范围里有不存在的路径：{缺}", "数据": {}, "证据": []}

    清单 = []
    for src in 文件:
        try:
            rel = src.relative_to(目标根)
        except ValueError:
            rel = Path(src.name)
        dst = 根 / "文件副本" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        清单.append({"相对路径": rel.as_posix(), "字节": src.stat().st_size,
                   "sha256": 文件sha256(src)})

    基线 = {
        "恢复点名称": 名称,
        "建立时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "目标根": str(目标根),
        "范围": 范围,
        "排除目录": list(排除t),
        "备注": 备注,
        "文件数": len(清单),
        "总字节": sum(x["字节"] for x in 清单),
        "文件": 清单,
    }
    基线路 = 根 / "基线清单.json"
    基线路.write_text(json.dumps(基线, ensure_ascii=False, indent=2), encoding="utf-8")

    # ★ 第一道自检：清单**真的写出来了**吗（G-3 的教训：日志说成功 ≠ 文件写出来了）
    if not 基线路.exists() or 基线路.stat().st_size < 100:
        return {"ok": False, "说明": "基线清单未写出或过小 —— 恢复点不成立（已复刻 G-3 的坑）",
                "数据": {}, "证据": []}

    # ★ 第二道自检：**当场回读**，逐文件比对副本与原件
    不一致 = []
    for x in 清单:
        cp = 根 / "文件副本" / x["相对路径"]
        if not cp.exists():
            不一致.append((x["相对路径"], "副本缺失"))
        elif cp.stat().st_size != x["字节"]:
            不一致.append((x["相对路径"], f"字节不符 {cp.stat().st_size}≠{x['字节']}"))
        elif 文件sha256(cp) != x["sha256"]:
            不一致.append((x["相对路径"], "sha256 不符"))

    if 不一致:
        return {"ok": False, "说明": f"回读不一致 {len(不一致)} 处 —— 恢复点不成立",
                "数据": {"恢复点": str(根), "不一致": 不一致[:20]},
                "证据": [{"恢复点": str(根), "不一致数": len(不一致)}]}

    return {
        "ok": True,
        "数据": {"恢复点": str(根), "名称": 名称, "文件数": len(清单),
                "总字节": 基线["总字节"], "基线清单": str(基线路),
                "回读一致": f"{len(清单)}/{len(清单)}", "备注": 备注},
        "证据": [{"恢复点": str(根), "文件数": len(清单),
                 "总字节": 基线["总字节"], "回读": "全一致"}],
        "说明": f"恢复点成立：{名称}　{len(清单)} 文件 / {基线['总字节']:,} B，回读 {len(清单)}/{len(清单)} 一致",
        "费用": {"embedding": "0", "生成": "0"},
    }


def 校验恢复点(名称: str, 恢复点根: str | None = None) -> dict:
    """只读校验一份已存在的恢复点：副本与基线一致 ＋ **原件是否被改动**。"""
    恢复点根 = Path(恢复点根) if 恢复点根 else 默认恢复点根
    根 = 恢复点根 / 名称
    if not 根.exists():
        return {"ok": False, "说明": f"恢复点不存在：{根}", "数据": {}, "证据": []}
    基线 = json.loads((根 / "基线清单.json").read_text(encoding="utf-8-sig"))
    目标根 = Path(基线["目标根"])
    副本坏, 原件变 = [], []
    for x in 基线["文件"]:
        cp = 根 / "文件副本" / x["相对路径"]
        org = 目标根 / x["相对路径"]
        if not cp.exists() or 文件sha256(cp) != x["sha256"]:
            副本坏.append(x["相对路径"])
        elif not org.exists():
            原件变.append(f"{x['相对路径']}（原件已不存在）")
        elif 文件sha256(org) != x["sha256"]:
            原件变.append(f"{x['相对路径']}（现 {org.stat().st_size} B ≠ 基线 {x['字节']} B）")
    ok = not 副本坏 and not 原件变
    return {
        "ok": ok,
        "数据": {"恢复点": str(根), "建立时间": 基线["建立时间"], "文件数": 基线["文件数"],
                "总字节": 基线["总字节"], "副本异常": 副本坏, "原件变动": 原件变[:20]},
        "证据": [{"恢复点": str(根), "文件数": 基线["文件数"]}],
        "说明": (f"✅ {基线['文件数']}/{基线['文件数']} 一致：副本与基线一致，且原件未被改动"
                if ok else f"❌ 副本异常 {len(副本坏)} 处；原件被改动 {len(原件变)} 处"),
        "费用": {"embedding": "0", "生成": "0"},
    }


if __name__ == "__main__":
    import pprint
    print("恢复点维护模块 · 自测（只读打印，不落盘）")
    print(f"默认恢复点根：{默认恢复点根}")
    print(f"默认排除：{默认排除}")
    pprint.pprint(_收集(Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用"),
                       ["02_项目源码与工程/src/工具.py"], 默认排除))
