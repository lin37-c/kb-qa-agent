# -*- coding: utf-8 -*-
"""有界队列 ＋ 固定工作线程（M9 第 3 步）。

为什么要它：
    M8 用一把 `threading.Lock` 做单飞 —— 第二单直接 429「上一题还在跑」。
    这在单用户界面上够用，但调用方是程序时，"忙就拒"会让批量脚本第 2 题就失败。
    改成：**先排队，队满才拒**。

语义（与《服务契约 v1》§七一致）：
    · 并发＝同时跑几个任务（默认 1，上限 2）；
    · 容量＝最多几个在等（默认 8）；
    · `提交()` 返回**提交那一刻前面有几个在等**（0＝马上会被取走）；
    · 队列满 → 返回 None，调用方据此回 429 BUSY ＋ Retry-After。

线程模型：
    启动 N 个 daemon 工作线程，共享一个 `deque` ＋ `Condition`。
    不用 `queue.Queue` 是因为它查不到"我在第几位"——而排队位次要给调用方看。
"""
from __future__ import annotations

import collections
import threading
from typing import Callable


class 有界队列:
    def __init__(self, 并发: int = 1, 容量: int = 8) -> None:
        self.并发 = max(1, int(并发))
        self.容量 = max(1, int(容量))
        self._等: collections.deque[tuple[str, Callable[[], None]]] = collections.deque()
        self._条件 = threading.Condition()
        self._开 = True
        self._跑着 = 0
        self._线程们 = [
            threading.Thread(target=self._工作, name=f"队列-{i + 1}", daemon=True)
            for i in range(self.并发)
        ]
        for t in self._线程们:
            t.start()

    # ---------- 对外 ----------
    def 提交(self, 任务号: str, 函数: Callable[[], None]) -> int | None:
        """返回前面还有几个在等；队列满返回 None（调用方回 429）。"""
        with self._条件:
            if len(self._等) >= self.容量:
                return None
            位次 = len(self._等)
            self._等.append((任务号, 函数))
            self._条件.notify()
            return 位次

    def 位次(self, 任务号: str) -> int:
        """排队中的位次（1 起）；不在排队返回 0。"""
        with self._条件:
            for i, (号, _) in enumerate(self._等):
                if 号 == 任务号:
                    return i + 1
        return 0

    def 等待数(self) -> int:
        with self._条件:
            return len(self._等)

    def 在跑(self) -> int:
        """正在执行的任务数（被取走后到函数返回之间）。"""
        with self._条件:
            return self._跑着

    def 关(self) -> None:
        with self._条件:
            self._开 = False
            self._条件.notify_all()

    # ---------- 内部 ----------
    def _工作(self) -> None:
        while True:
            with self._条件:
                while self._开 and not self._等:
                    self._条件.wait(0.2)
                if not self._开 and not self._等:
                    return
                if not self._等:
                    continue
                _, 函数 = self._等.popleft()
                self._跑着 += 1
            try:
                函数()
            except Exception:  # noqa: BLE001
                #   任务自己的异常已在 _跑 里落成 error 事件；这里只保证工作线程不死
                pass
            finally:
                with self._条件:
                    self._跑着 -= 1
