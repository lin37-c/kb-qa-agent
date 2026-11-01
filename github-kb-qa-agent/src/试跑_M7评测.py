# -*- coding: utf-8 -*-
"""M7 评测跑数脚本 —— 5 档对比 ＋ 三项指标。

★ 硬约束（任务索引 §5.1）：本脚本放在 `src\\`（§2：源码不套任务六类目录），
  且**必须从 `src\\` 载入模块**（U-45 反向守卫要求）。
★ 只测不改：不改任何已发布模块的行为。
★ 三档位映射（依据 `检索.py` 的 3 个开关）：
    ① 纯向量      ：分组=全库，用扩展=False，自动判房间=False
    ② ＋来源过滤   ：分组=默认（规则体系），用扩展=False，自动判房间=False
    ③ ＋查询扩展   ：分组=默认，用扩展=True， 自动判房间=False
    ④ ＋自动判房间 ：分组=None，用扩展=True， 自动判房间=True
    ⑤ 全开＝现网   ：同 ④（现网默认调用形态）

用法：
    python 试跑_M7评测.py --冒烟          # 只跑 3 题 × 5 档，验证脚本通
    python 试跑_M7评测.py                 # 全量 40 题 × 5 档
    python 试跑_M7评测.py --档 4          # 只跑某一档
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

本文件 = Path(__file__).resolve()
SRC = 本文件.parent
根 = SRC.parent.parent
sys.path.insert(0, str(SRC))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import 检索 as 检  # noqa: E402
import 生成 as 生  # noqa: E402

题集路径 = 根 / "05_项目验证证据" / "_M7评测" / "评测集_M7.json"
输出目录 = 根 / "05_项目验证证据" / "_M7评测"
包根 = Path(r"<asset-root>")

#   5 档位定义
档位 = {
    1: {"名": "纯向量", "分组": "全库", "用扩展": False, "自动判房间": False},
    2: {"名": "＋来源过滤", "分组": None, "用扩展": False, "自动判房间": False},
    3: {"名": "＋查询扩展", "分组": None, "用扩展": True, "自动判房间": False},
    4: {"名": "＋自动判房间", "分组": None, "用扩展": True, "自动判房间": True},
    5: {"名": "全开（＝现网口径）", "分组": None, "用扩展": True, "自动判房间": True},
}


def 跑一题(问题: str, 档: dict, 取前: int = 10) -> dict:
    """跑一题，返回 {命中列表, 判定, 最高分, 分组, 异常}。"""
    try:
        r = 检.检索(问题, 取前=取前, 分组=档["分组"],
                    用扩展=档["用扩展"], 自动判房间=档["自动判房间"])
        return {
            # ★ 字段名修正（2026-10-16）：实际是 `结果` —— 我原写 `结果列表` ⇒ 永远取到空列表，
            #   导致 Top5 全 0 的**假读数**。教训：**字段名要打盘上看，不能凭印象写**。
            "命中列表": [{"来源文件": h.get("来源文件", ""),
                          "相似度": h.get("相似度"),
                          "标题路径": h.get("标题路径", "")} for h in r.get("结果", [])],
            "判定": r.get("判定", ""),
            "最高分": r.get("最高相似度"),
            "分组": r.get("分组", ""),
            "分组来源": r.get("分组来源", ""),
            "异常": None,
        }
    except Exception as ex:  # noqa: BLE001
        return {"命中列表": [], "判定": "", "最高分": None, "分组": "",
                "分组来源": "", "异常": f"{type(ex).__name__}: {ex}"}


def _规范(s: str) -> str:
    return str(s).replace("/", "\\").strip("\\").lower()


def 判命中(命中: list[dict], 出处: str, k: int, 模式: str = "严格") -> tuple[bool, int | None]:
    """Top-k 命中判定。

    模式
        严格 : 命中的「来源文件」必须是**金标准那个文件**（或其上级/下级路径互为包含）
        前缀 : 命中的「来源文件」**落在金标准所在目录内**即可
              ★ 这一档与题集「期望来源前缀」的设计口径一致

    ★ 为什么两个都要：只报严格会低估（题集本设计成前缀口径）；
      只报前缀会高估（进对目录、进错文件也可能答不出）。**差额就是"进对目录没进对文件"。**
    """
    tgt = _规范(出处)
    目录 = tgt.rsplit("\\", 1)[0] if "\\" in tgt else tgt
    for i, h in enumerate(命中[:k], 1):
        源 = _规范(h.get("来源文件", ""))
        if 模式 == "严格":
            if 源 == tgt or 源.endswith("\\" + tgt) or tgt.endswith("\\" + 源) or 源 in tgt or tgt in 源:
                return True, i
        else:
            if 源.startswith(目录) or 目录.startswith(源.rsplit("\\", 1)[0] if "\\" in 源 else 源):
                return True, i
    return False, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--冒烟", action="store_true", help="只跑 3 题 × 5 档")
    ap.add_argument("--档", type=int, default=0, help="只跑某一档（1~5）")
    a = ap.parse_args()

    题集 = json.loads(题集路径.read_text(encoding="utf-8"))
    覆盖 = 题集["覆盖集"]
    改写 = 题集["回归集_A_语义改写"]
    陷阱 = 题集["回归集_B_陷阱"]

    要跑的档 = [a.档] if a.档 else [1, 2, 3, 4, 5]
    有出处的题 = [{**x, "类型": "覆盖"} for x in 覆盖] + [{**x, "类型": "回归改写"} for x in 改写]

    if a.冒烟:
        有出处的题 = 有出处的题[:3]
        陷阱 = 陷阱[:2]
        print("  ★ 冒烟模式：只跑 3 题（有出处）＋ 2 题（陷阱）")

    print("=" * 96)
    print(f"M7 评测 · {len(有出处的题)} 题 × {len(要跑的档)} 档　＋　陷阱 {len(陷阱)} 题")
    print("=" * 96)

    结果 = {"档位": {}, "陷阱": {}, "元": {
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "冒烟": a.冒烟, "题数": len(有出处的题), "陷阱数": len(陷阱),
    }}

    for 号 in 要跑的档:
        档 = 档位[号]
        print(f"\n【第 {号} 档】{档['名']}")
        逐题 = []
        t0 = time.time()
        for x in 有出处的题:
            r = 跑一题(x["问题"], 档)
            进5, 位5 = 判命中(r["命中列表"], x["金标准出处"], 5, "严格")
            进1, 位1 = 判命中(r["命中列表"], x["金标准出处"], 1, "严格")
            进10, 位10 = 判命中(r["命中列表"], x["金标准出处"], 10, "严格")
            前5, 前位5 = 判命中(r["命中列表"], x["金标准出处"], 5, "前缀")
            逐题.append({"编号": x["编号"], "问题": x["问题"], "出处": x["金标准出处"],
                         "Top1": 进1, "Top5": 进5, "Top10": 进10, "位次": 位5,
                         "前缀Top5": 前5, "前缀位次": 前位5,
                         "最高分": r["最高分"], "判定": r["判定"],
                         "分组": r["分组"], "分组来源": r["分组来源"], "异常": r["异常"]})
            标 = "✅" if 进5 else ("🟡" if 进10 else "❌")
            print(f"    {标} {x['编号']:<7} Top5={进5} 位次={位5} 最高分={r['最高分']} 判定={r['判定'][:12]}")
        n = len(逐题)
        汇总 = {
            "Top1命中率": round(sum(1 for t in 逐题 if t["Top1"]) / n, 4),
            "Top5命中率": round(sum(1 for t in 逐题 if t["Top5"]) / n, 4),
            "Top10命中率": round(sum(1 for t in 逐题 if t["Top10"]) / n, 4),
            "★前缀Top5命中率": round(sum(1 for t in 逐题 if t["前缀Top5"]) / n, 4),
            "耗时秒": round(time.time() - t0, 1),
            "异常数": sum(1 for t in 逐题 if t["异常"]),
        }
        print(f"    ⇒ 严格：Top1 {汇总['Top1命中率']:.2%}｜Top5 {汇总['Top5命中率']:.2%}｜"
              f"Top10 {汇总['Top10命中率']:.2%}　★前缀Top5 {汇总['★前缀Top5命中率']:.2%}｜"
              f"{汇总['耗时秒']}s｜异常 {汇总['异常数']}")
        结果["档位"][str(号)] = {"档名": 档["名"], "汇总": 汇总, "逐题": 逐题}

    #   陷阱题（幻觉信号①：该拒答而肯定回答）
    if 陷阱:
        print(f"\n【陷阱题】{len(陷阱)} 题 —— 期望全部拒答")
        逐陷 = []
        #   ★ 判据修正（2026-10-16）：检索层有 4 种判定，**只有「可信命中」才是"给出肯定回答"**：
        #       · 该区域尚未入库 / 库中没有相关内容   → 硬拒答（检索层就没给材料）
        #       · 弱相关（仅供参考…）               → ★ **灰区**：检索层给了材料，**由生成层决定**
        #       · 可信命中                          → ★ **肯定回答 ⇒ 陷阱题在这里才算幻觉**
        #   ⇒ 所以陷阱题**必须跑生成层**才量得准（0.53~0.58 那段灰区只有生成层能分辨）。
        for x in 陷阱:
            r = 跑一题(x["问题"], 档位[5])
            检判 = r["判定"]
            #   检索层已硬拒答 ⇒ 无需调模型
            if ("尚未入库" in 检判) or ("库中没有" in 检判):
                类 = "硬拒答"; 答 = "（检索层拒答，未调模型）"
            else:
                try:
                    g = 生.回答(x["问题"])
                    答 = g.get("答案", "")
                    拒 = ("没有相关内容" in 答) or ("无法回答" in 答) or ("资料里没有" in 答) or bool(g.get("拒答原因"))
                    类 = "软拒答" if 拒 else ("幻觉" if "可信命中" in 检判 else "灰区-未拒答")
                except Exception as ex:  # noqa: BLE001
                    答 = f"（生成异常：{type(ex).__name__}: {ex}）"
                    类 = "生成异常"
            逐陷.append({"编号": x["编号"], "问题": x["问题"], "检索判定": 检判,
                         "最高分": r["最高分"], "分类": 类, "答案": 答[:300]})
            print(f"    {'✅' if 类 in ('硬拒答', '软拒答') else '❌'} {x['编号']} "
                  f"分={r['最高分']} 检索={检判[:16]} ⇒ **{类}**")
        n = len(逐陷)
        from collections import Counter as _C
        分 = _C(t["分类"] for t in 逐陷)
        拒 = 分.get("硬拒答", 0) + 分.get("软拒答", 0)
        结果["陷阱"] = {"汇总": {"拒答率": round(拒 / n, 4),
                                 "硬拒答": 分.get("硬拒答", 0), "软拒答": 分.get("软拒答", 0),
                                 "灰区未拒答": 分.get("灰区-未拒答", 0),
                                 "★幻觉信号①": 分.get("幻觉", 0),
                                 "阈值_高": 检.阈值_高, "阈值_低": 检.阈值_低},
                        "逐题": 逐陷}
        print(f"    ⇒ 拒答率 {结果['陷阱']['汇总']['拒答率']:.2%}"
              f"（硬 {分.get('硬拒答',0)}／软 {分.get('软拒答',0)}）｜"
              f"灰区未拒答 {分.get('灰区-未拒答',0)}｜★ 幻觉信号① {分.get('幻觉',0)} 题")

    后缀 = "_冒烟" if a.冒烟 else ""
    输出目录.mkdir(parents=True, exist_ok=True)   # ★ 缺这一句 ⇒ 首次跑写盘必失败
    出 = 输出目录 / f"多档对比{后缀}.json"
    出.write_text(json.dumps(结果, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✅ 已落：{出}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
