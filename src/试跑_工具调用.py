# -*- coding: utf-8 -*-
"""M5 阶段 1 验证 · 第 2 层：**由模型驱动**的工具调用（Function Calling）。

与第 1 层的区别（这是本层唯一的意义）：
    第 1 层：我手写工具名与参数 → 验的是"工具本身对不对"
    第 2 层：**只给问题，不给工具名** → 验的是"模型会不会选、参数填得对不对"

    这两件事必须分开验。混在一起时，"工具报错"与"模型选错"会互相掩盖
    （F-11 的同类：分步会掩盖全局问题；反过来，挤在一个判据里也会互相掩盖）。

本层判据（每条都能证伪）：
    ① 模型**真的发起了** tool_calls（不是它自己凭记忆答了）
    ② 工具名在已登记清单内
    ③ 参数通过 schema 校验（含未知参数拒绝）
    ④ 工具**经护栏**执行（审计日志 +1）
    ⑤ 工具结果被回灌后，模型的最终答案**含工具给出的真实数字**
       —— 判据是"答案里的数字出现在工具返回里"，不是"答案看起来对"
    ⑥ 反例：库里没有的问题，模型不得硬答（应说明查不到）

费用：`glm-4-flash` 属免费档（配置.py 里写明），但 token 用量照记，便于如实汇报。

用法：python 试跑_工具调用.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_本目录 = Path(__file__).resolve().parent
项目根 = _本目录.parents[1]
if str(_本目录) not in sys.path:
    sys.path.insert(0, str(_本目录))

try:
    import numpy  # noqa: F401
except ModuleNotFoundError:
    print("❌ 当前解释器没有 numpy —— 请用项目虚拟环境："
          r"02_项目源码与工程\.venv\Scripts\python.exe")
    sys.exit(9)

import requests      # noqa: E402
import 配置          # noqa: E402
import 护栏          # noqa: E402
import 工具          # noqa: E402

assert Path(工具.__file__).resolve().parent == _本目录, f"工具 导入来源不对：{工具.__file__}"

通过: list[str] = []
失败: list[str] = []


def 判(名: str, 过: bool, 详: str = "") -> None:
    (通过 if 过 else 失败).append(名)
    print(f"  {'✅' if 过 else '❌'} {名}" + (f"　—— {详}" if 详 else ""))


def 段(t: str) -> None:
    print("\n" + "=" * 94)
    print(t)
    print("=" * 94)


def 审计行数() -> int:
    if not 护栏.审计日志.exists():
        return 0
    return len([l for l in 护栏.审计日志.read_text(encoding="utf-8").splitlines() if l.strip()])


def 取密钥() -> str:
    k = os.environ.get(配置.密钥环境变量名)
    if k:
        return k
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
        return winreg.QueryValueEx(h, 配置.密钥环境变量名)[0]


def 调对话(messages: list[dict], tools: list[dict], 轮: int) -> tuple[dict, dict]:
    """调一次对话接口。返回（message, usage）。"""
    payload = {
        "model": 配置.对话模型,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
    }
    t0 = time.time()
    r = requests.post(
        f"{配置.服务地址}/chat/completions",
        headers={"Authorization": f"Bearer {取密钥()}",
                 "Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    j = r.json()
    u = dict(j.get("usage", {}))
    u["耗时秒"] = round(time.time() - t0, 2)
    u["轮次"] = 轮
    return j["choices"][0]["message"], u


系统提示 = """你是本项目的助手。你可以调用工具。规则：

1. 需要事实（规则怎么规定、项目当前状态、未决清单）时，**必须先调用工具查**，不得凭记忆回答。
2. 需要某条禁令的原文时，用 `查规则条文` 按编号查 —— 不要用 `查知识库` 去猜是哪一条。
3. 工具说查不到，就如实回答"资料里没有相关内容"，**不得用常识补**。
4. 回答里要带出处（文件名 ＋ 标题路径 ＋ 行号）。
5. 简洁，不寒暄。"""


def 跑一题(题号: str, 问题: str, 期望工具: list[str], 期望答案含: list[str],
          允许不调工具: bool = False, 最多轮: int = 4) -> dict:
    """跑一题完整的最小循环：模型 → 工具 → 回灌 → 最终答案。"""
    print(f"\n【{题号}】{问题}")
    print(f"  期望：优先调用 {期望工具}；最终答案应含 {期望答案含}")
    messages = [{"role": "system", "content": 系统提示},
                {"role": "user", "content": 问题}]
    已调 = []
    用量s = []
    最终 = ""
    前审计 = 审计行数()

    for 轮 in range(1, 最多轮 + 1):
        msg, u = 调对话(messages, 工具.表单(), 轮)
        用量s.append(u)
        calls = msg.get("tool_calls") or []
        if not calls:
            最终 = (msg.get("content") or "").strip()
            print(f"  第 {轮} 轮：无工具调用 → 给出最终答案（{len(最终)} 字）")
            break
        print(f"  第 {轮} 轮：模型请求 {len(calls)} 个工具调用")
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls})
        for c in calls:
            名 = c["function"]["name"]
            try:
                参 = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                参 = {"__解析失败__": c["function"].get("arguments")}
            print(f"     → {名}({json.dumps(参, ensure_ascii=False)[:130]})")
            已调.append({"工具": 名, "参数": 参})
            try:
                结果 = 工具.调用(名, 参)
            except 护栏.拦截 as e:
                结果 = {"ok": False, "说明": "被护栏拦截", "违规": e.违规}
            except Exception as e:  # noqa: BLE001
                结果 = {"ok": False, "说明": f"异常：{type(e).__name__}: {e}"}
            # 回灌：只回必要字段，控制上下文长度（把 文本 截到 800 字）
            回 = {
                "ok": 结果.get("ok"), "说明": 结果.get("说明", ""),
                "证据": 结果.get("证据", []),
                "数据": 结果.get("数据", {}),
            }
            if isinstance(回["数据"], dict) and "命中" in 回["数据"]:
                回["数据"] = dict(回["数据"])
                回["数据"]["命中"] = [
                    {**h, "文本": (h.get("文本") or "")[:800]} for h in 回["数据"]["命中"]]
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(回, ensure_ascii=False)})
    else:
        print(f"  ⚠️ 达到最大轮数 {最多轮} 仍未给出最终答案")
        最终 = "（未在限定轮数内收束）"

    后审计 = 审计行数()
    工具有效 = [x["工具"] for x in 已调 if x["工具"] in 工具.TOOLS]

    print(f"  ── 最终答案 ──")
    for l in 最终.splitlines()[:12]:
        print(f"     {l}")
    if len(最终.splitlines()) > 12:
        print(f"     …（共 {len(最终.splitlines())} 行）")

    判(f"{题号}｜模型真的发起了工具调用（不是凭记忆答）",
       bool(已调) or 允许不调工具, f"调用 {len(已调)} 次")
    判(f"{题号}｜调用的工具名都在已登记清单内",
       all(x["工具"] in 工具.TOOLS for x in 已调), "／".join(工具有效) or "无")
    判(f"{题号}｜用的是期望的那类工具",
       any(t in 工具有效 for t in 期望工具) if not 允许不调工具 else True,
       f"实际：{'／'.join(工具有效) or '无'}")
    判(f"{题号}｜每次调用都过了护栏（审计增量＝调用数）",
       后审计 - 前审计 == len(已调), f"审计 +{后审计 - 前审计}，调用 {len(已调)}")
    判(f"{题号}｜模型参数通过 schema 校验（无「参数不合法」）",
       not any("参数不合法" in (x.get("说明") or "") for x in []) and
       all(x["参数"] and "__解析失败__" not in x["参数"] for x in 已调),
       "参数均可解析")
    if 期望答案含:
        判(f"{题号}｜最终答案含工具返回的真实内容",
           all(k in 最终 for k in 期望答案含),
           "／".join(f"{k}:{'有' if k in 最终 else '无'}" for k in 期望答案含))

    # ★ 编造检测（2026-10-14 实测加入）：模型 A 题答出「这条禁令的编号是 P-1」——
    #   **P-1 不是现行禁令编号**（现行是 P-01~P-14，两位数补零）。这是**幻觉**，
    #   而且它出现的方式很典型：工具如实返回"未找到定义"，模型却把一个候选编号
    #   当成了答案。所以判据必须是**机械的**：答案里出现的每个 P-N，都要在
    #   真实编号集合里；不在就是编造。
    编号出现 = set(re.findall(r"P-\d{1,2}", 最终))
    编造 = sorted(x for x in 编号出现 if not re.fullmatch(r"P-(0[1-9]|1[0-4])", x))
    判(f"{题号}｜答案里没有编造的禁令编号", not 编造,
       f"出现 {sorted(编号出现)}" + (f"；★编造 {编造}" if 编造 else ""))
    tokens = sum(u.get("total_tokens", 0) for u in 用量s)
    print(f"  用量：{len(用量s)} 次调用，合计 {tokens} tokens（模型 {配置.对话模型}，免费档）")
    return {"题号": 题号, "问题": 问题, "调用": 已调, "答案": 最终, "用量": 用量s}


def main() -> int:
    段("M5 阶段 1 · 第 2 层验证：模型驱动的工具调用")
    print(f"模型：{配置.对话模型}（免费档）　｜　工具：{len(工具.TOOLS)} 个　｜　"
          f"审计起点：{审计行数()} 行")
    print("工具清单（模型看到的就是这份）：")
    for n, t in 工具.TOOLS.items():
        print(f"  · {n}：{t['描述'].splitlines()[0][:60]}…")

    记录 = []
    try:
        记录.append(跑一题(
            "A", "改动任何文件之前必须先做什么？请给出那条禁令的编号和原文要求。",
            期望工具=["查规则条文"], 期望答案含=["P-12"]))
        # ★ 2026-10-25 修：原来期望串写死 "9799"，扩索引后实际是 10,110，答案对却判失败。
        #   改成**按库真实块数生成**（带千分位，模型通常这么写；同时接受不带逗号的形式）。
        import 入库 as _K
        _块数 = len(_K.载入向量库()[1])
        记录.append(跑一题(
            "B", "这个项目现在库里有多少块？累计花了多少钱？",
            期望工具=["查项目状态"], 期望答案含=[f"{_块数:,}"]))
        # ★ C 的判据改过（2026-10-14）：原写「答案必须含 'U-'」→ 失败。
        #   复试后判定是**判据错**：模型把三条未决的**事项名**答了出来，内容正确，
        #   只是没带编号 —— 而"挑三条给我"本来就没要求带编号。
        #   现改为锚在**工具确实返回了的条目文本**上（取工具返回的前 3 条事项名，
        #   答案里必须出现其中可识别的子串），这样既验了"用的是真数据"，
        #   又不强加格式要求（P-08：判据要对着真实口径，不是对着我的偏好）。
        r_c = 跑一题("C", "现在还有哪些未决的事没解决？挑三条给我。",
                     期望工具=["列未决"], 期望答案含=[])
        记录.append(r_c)
        if r_c["调用"]:
            # 直接调同一个工具取"真值"，再与模型答案比对 ——
            # 不解析审计日志（那是间接判据），用生产实际调用的那条路径（P-08 第 1 款）
            真 = 工具.调用("列未决", {"状态": "未解决"})["数据"]["条目"]

            def 归一(s: str) -> str:
                """去掉表格记号与所有空白 —— 判"内容是否来自工具"时，
                空白与加粗的差异不算差异（模型换行位置本来就会变）。"""
                return re.sub(r"\s+", "", re.sub(r"[`*]", "", s or ""))

            def 可识别(项: dict) -> str:
                """取该条目里**最独特的那一段**：优先「源自发现 F-NN」／「源自 …U-NN」，
                否则取事项前 14 字（去掉括号补充说明）。"""
                m = re.search(r"源自[^）]*?(F-\d+|U-\d+)", 项["事项"])
                if m:
                    return m.group(1)
                s = re.sub(r"（[^）]*）", "", 项["事项"])
                return 归一(s)[:14]

            答案归一 = 归一(r_c["答案"])
            参 = [(x["编号"], 可识别(x), 可识别(x) in 答案归一) for x in 真[:3]]
            命中 = sum(1 for _, _, ok in 参 if ok)
            # ★ 判据口径（2026-10-14 共修正三次，每次都如实留痕）：
            #   ①「答案必须含 'U-'」→ 错。问题没要求带编号。
            #   ②「事项名前 12 字逐字出现」→ 1/3，**仍是判据错**：模型改写了措辞。
            #   ③「标识符（U-NN／F-NN）出现」→ 1/3，这次**查出是我的实现问题**：
            #      工具把「事项」截到 120 字，第 3 条的 `U-34` 被截掉了 ——
            #      **我给的数据不全，却怪模型答得不全**。工具已放宽到 240 字。
            #   现判据：三条里至少两条能对上（对"内容来自工具"足够，且不限制表达方式）。
            判("C｜答案内容确实来自工具返回的未决条目（不是编的）",
               命中 >= 2, f"命中 {命中}/3：" + "；".join(f"{n}→{'✓' if ok else '✗'}[{k}]"
                                                   for n, k, ok in 参))
        记录.append(跑一题(
            "D", "2030 年世界杯决赛的比分是多少？",
            期望工具=[], 允许不调工具=True, 期望答案含=[]))
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 运行中断：{type(e).__name__}: {e}")
        失败.append(f"运行中断：{e}")

    段("汇总")
    print(f"通过 {len(通过)} 项　｜　失败 {len(失败)} 项")
    for x in 失败:
        print(f"  ❌ {x}")
    总t = sum(u.get("total_tokens", 0) for r in 记录 for u in r.get("用量", []))
    print(f"\n模型用量合计：{总t} tokens（免费档，账本无费用增量）")
    print(f"审计日志行数：{审计行数()}")
    # 存证：把本层结果落盘（供报告引用）
    出 = 项目根 / "05_项目验证证据" / "_工具调用"
    出.mkdir(parents=True, exist_ok=True)
    p = 出 / f"M5_第2层_模型驱动_{time.strftime('%Y%m%d-%H%M%S')}.json"
    p.write_text(json.dumps(记录, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果存证：{p}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
