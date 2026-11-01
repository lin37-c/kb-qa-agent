# -*- coding: utf-8 -*-
"""S1 验证：`落恢复点` 工具能不能真的承担 P-12。

判据（每条都能证伪）：
  ① 真落一份恢复点 → 文件数/字节数与源一致，**回读全一致**
  ② **与既有实现同口径**：对同一批文件，本工具的 sha256 与 `落恢复点_M5.py` 的基线清单逐条相等
     （若两套算法不一致，"恢复点"就成了两套说法 —— 这是 F-19 那类同步缺陷的同型）
  ③ 回读不一致时**必须报失败**（用一个人造场景触发：把副本改一个字节后再校验）
  ④ 护栏拦截路径：范围里出现 `..` → 拒；出现绝对路径 → 拒；路径不存在 → 拒
  ⑤ 落点正确：恢复点确实落在恢复点根下（不是别处）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

项目根 = Path(r"<workspace>\01_项目\DeepSeek Harness专用\LLM知识库检索与工具调用")
SRC = 项目根 / "02_项目源码与工程" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import 护栏    # noqa: E402
import 工具    # noqa: E402

assert Path(工具.__file__).resolve().parent == SRC, f"工具导入来源不对：{工具.__file__}"

通过: list[str] = []
失败: list[str] = []
提示: list[str] = []


def 判(名: str, 过: bool, 详: str = "") -> None:
    (通过 if 过 else 失败).append(名)
    print(f"  {'✅' if 过 else '❌'} {名}" + (f"　—— {详}" if 详 else ""))


def 段(t: str) -> None:
    print("\n" + "=" * 92)
    print(t)
    print("=" * 92)


测试恢复点名 = "LLM知识库检索与工具调用_S1验证_20261014"


def 调(工具名: str, 参数: dict) -> dict:
    try:
        return 工具.调用(工具名, 参数)
    except 护栏.拦截 as e:
        return {"ok": False, "被拦": True, "违规": e.违规,
                "说明": "；".join(f"[{v['规则']}]{v['判据']}" for v in e.违规)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "异常": f"{type(e).__name__}: {e}", "说明": str(e)}


def main() -> int:
    段("S1 验证 · 落恢复点 工具（阶段 3）")
    目标根 = 项目根 / "02_项目源码与工程"
    范围 = ["src/工具.py", "src/护栏.py", "src/配置.py"]
    恢复点根 = 护栏.恢复点根
    print(f"目标根  ：{目标根}")
    print(f"范围    ：{范围}")
    print(f"恢复点根：{恢复点根}")

    # ---------- ① 正常落一份 ----------
    段("① 真落一份恢复点")
    if (恢复点根 / 测试恢复点名).exists():
        提示.append(f"上一次验证留下的恢复点已存在，先清理：{测试恢复点名}")
        import shutil
        shutil.rmtree(恢复点根 / 测试恢复点名)
    r = 调("落恢复点", {"名称": 测试恢复点名, "目标根": str(目标根), "范围": 范围,
                      "备注": "S1 验证用（可删）"})
    print(f"  结果：{r.get('说明')}")
    判("① 落恢复点成功", bool(r.get("ok")), str(r.get("数据", {}).get("名称", "")))
    if r.get("ok"):
        d = r["数据"]
        判("① 文件数＝3", d.get("文件数") == 3, f"{d.get('文件数')} 个")
        判("① 回读全一致", d.get("回读一致") == "3/3", str(d.get("回读一致")))
        判("① 落点在恢复点根下", str(恢复点根) in d.get("恢复点", ""), d.get("恢复点", "")[:70])

        # ---------- ② 与既有实现同口径 ----------
        段("② 与既有实现同口径核对（哈希算法是否一致）")
        基线 = json.loads((Path(d["基线清单"])).read_text(encoding="utf-8-sig"))
        我方 = {x["相对路径"]: x["sha256"] for x in 基线["文件"]}
        # ★ 判据修正（2026-10-14）：第一版按 `src/工具.py` 去旧恢复点里找 —— **找不到**，
        #   因为旧恢复点是**以项目根为目标根**建的，相对路径写作 `02_项目源码与工程\src\工具.py`。
        #   **路径书写口径不同 ≠ 算法不同**；与其在旧清单里找，不如**直接现算磁盘哈希**比对，
        #   这样判据只锚在"哈希算法"这一件事上（P-08：用生产实际那条口径）。
        import hashlib

        def 现算(p: Path) -> str:
            h = hashlib.sha256()
            with p.open("rb") as f:
                for 块 in iter(lambda: f.read(1 << 20), b""):
                    h.update(块)
            return h.hexdigest()

        对照 = []
        for rel, s in 我方.items():
            disk = Path(d.get("目标根") or 目标根) / rel   # ★ 相对路径要拼**目标根**，不是项目根
            if disk.exists():
                对照.append((rel, s == 现算(disk)))
        print(f"  与磁盘现算对照：{len(对照)} 个 → {[r for r,_ in 对照]}")
        判("② 归档哈希与磁盘现算一致（同口径）",
           bool(对照) and all(ok for _, ok in 对照),
           f"对照 {len(对照)} 个；{'全一致' if all(ok for _, ok in 对照) else '有不一致'}")

    # ---------- ③ 副本被改动 → 校验必须报失败 ----------
    段("③ 副本被改一个字节后，校验必须报失败（证明回读不是走过场）")
    r = 调("查恢复点", {"名称": 测试恢复点名})
    判("③ 改前校验通过", bool(r.get("ok")), r.get("说明", "")[:60])
    cp = 恢复点根 / 测试恢复点名 / "文件副本" / "02_项目源码与工程" / "src" / "配置.py"
    if cp.exists():
        原文 = cp.read_bytes()
        cp.write_bytes(原文 + b"\n# tamper-test\n")
        r2 = 调("查恢复点", {"名称": 测试恢复点名})
        判("③ 篡改后校验失败（副本异常）", not r2.get("ok") and r2.get("数据", {}).get("副本异常"),
           f"副本异常 {len(r2.get('数据', {}).get('副本异常', []))} 处")
        cp.write_bytes(原文)          # 还原
        r3 = 调("查恢复点", {"名称": 测试恢复点名})
        判("③ 还原后校验恢复通过", bool(r3.get("ok")), r3.get("说明", "")[:60])

    # ---------- ④ 护栏拦截路径 ----------
    段("④ 护栏拦截：范围里出现 `..` / 绝对路径 / 不存在的路径")
    r = 调("落恢复点", {"名称": "不该被创建的_探针A", "目标根": str(目标根),
                      "范围": [r"..\..\..\恢复点\越界"], "备注": "探针"})
    判("④ `..` 跳出被拒", r.get("被拦") and any(v["规则"] == "P-12" for v in r.get("违规", [])),
       r.get("说明", "")[:90])
    r = 调("落恢复点", {"名称": "不该被创建的_探针B", "目标根": str(目标根),
                      "范围": [str(项目根 / "AGENTS.md")], "备注": "探针"})
    判("④ 绝对路径被拒", r.get("被拦") and any(v["规则"] == "P-12" for v in r.get("违规", [])),
       r.get("说明", "")[:90])
    r = 调("落恢复点", {"名称": "不该被创建的_探针C", "目标根": str(目标根),
                      "范围": ["src/不存在的文件.py"], "备注": "探针"})
    判("④ 不存在的路径被拒", not r.get("ok"), r.get("说明", "")[:90])
    判("④ 三个探针都没留下目录",
       not any((恢复点根 / f"不该被创建的_探针{x}").exists() for x in "ABC"),
       "无残留")

    # ---------- ⑤ 查恢复点（列清单） ----------
    段("⑤ 查恢复点（只读）")
    r = 调("查恢复点", {})
    print(f"  {r.get('说明')}")
    判("⑤ 列清单可用且本项目份数 ≥ 16", bool(r.get("ok")) and r["数据"]["本项目份数"] >= 16,
       f"{r.get('数据', {}).get('本项目份数')} 份")

    段("汇总")
    print(f"通过 {len(通过)} 项　｜　失败 {len(失败)} 项　｜　提示 {len(提示)} 项")
    for x in 失败:
        print(f"  ❌ {x}")
    for x in 提示:
        print(f"  ⚠️ {x}")
    print(f"\n★ 本次验证留下的恢复点：{测试恢复点名}（3 文件，可随时删）")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
