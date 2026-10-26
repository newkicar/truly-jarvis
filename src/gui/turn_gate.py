"""每 thread 回合门 + 消息 FIFO 队列（纯逻辑，不依赖 Qt，可单测）。

语义（spec 回合门与排队）：
- 同一 thread 同时只允许一个回合在跑（对齐 main/TUI 的 worker 串行约定）。
- 执行中再发消息 → 不进新回合，进该 thread 的 FIFO 队列；回合结束后按序重投。
- 不同 thread 之间互不阻塞（各自独立回合门 + 队列），跨 thread 并行。
- 取消当前回合 = 置 cancel 位（worker 在 drain 边界生效），不阻塞其它 thread。

本模块只管「能否进回合 / 排队 / 出队 / 取消位」，不碰 agent/Qt。
"""
from __future__ import annotations

import threading
from collections import deque


class TurnGate:
    """线程安全的每 thread 回合门 + FIFO 消息队列。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._queues: dict[str, deque[str]] = {}
        self._cancel: dict[str, bool] = {}

    # ---- 回合生命周期
    def try_start(self, tid: str, user_text: str) -> str:
        """尝试进回合。返回 'started'（立即开跑）或 'queued'（已排队）。"""
        with self._lock:
            if tid in self._running:
                self._queues.setdefault(tid, deque()).append(user_text)
                return "queued"
            self._running.add(tid)
            self._cancel[tid] = False
            return "started"

    def finish(self, tid: str) -> str | None:
        """回合结束。返回下一条待发消息（FIFO 出队），没有则 None。

        调用方拿到非 None 时应重新调 try_start 起下一回合。
        """
        with self._lock:
            self._running.discard(tid)
            self._cancel[tid] = False
            q = self._queues.get(tid)
            if q:
                return q.popleft()
            return None

    # ---- 队列观测
    def queued_count(self, tid: str) -> int:
        with self._lock:
            return len(self._queues.get(tid) or ())

    def is_running(self, tid: str) -> bool:
        with self._lock:
            return tid in self._running

    def running_threads(self) -> list[str]:
        with self._lock:
            return sorted(self._running)

    # ---- 取消
    def request_cancel(self, tid: str) -> None:
        with self._lock:
            self._cancel[tid] = True

    def is_cancelled(self, tid: str) -> bool:
        with self._lock:
            return self._cancel.get(tid, False)

    def peek_cancelled(self, tid: str) -> bool:
        """非破坏性读取消位（worker 的 is_cancelled 闭包用它）。"""
        return self.is_cancelled(tid)
