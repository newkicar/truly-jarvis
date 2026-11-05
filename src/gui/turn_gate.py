"""每 thread 回合门 + 消息 FIFO 队列（纯逻辑，不依赖 Qt，可单测）。

语义（spec 回合门与排队）：
- 同一 thread 同时只允许一个回合在跑（对齐 main/TUI 的 worker 串行约定）。
- 执行中再发消息 → 不进新回合，进该 thread 的 FIFO 队列；回合结束后按序重投。
- 不同 thread 之间互不阻塞（各自独立回合门 + 队列），跨 thread 并行。
- 取消当前回合 = 置 cancel 位（worker 在 drain 边界生效），不阻塞其它 thread。
- 队列项 = (原文, 图片列表)：#2 修复——带图消息排队后重投时图片不能丢
  （旧实现队列只存原文，图片随提交清空丢失 / 或泄漏到别的会话）。

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
        self._queues: dict[str, deque[tuple[str, list[str]]]] = {}
        self._cancel: dict[str, bool] = {}

    # ---- 回合生命周期
    def try_start(self, tid: str, user_text: str, *, images: list[str] | None = None) -> str:
        """尝试进回合。返回 'started'（立即开跑）或 'queued'（已排队）。

        images：随队载荷（#2），仅排队分支使用；started 分支忽略。
        """
        with self._lock:
            if tid in self._running:
                self._queues.setdefault(tid, deque()).append((user_text, list(images or [])))
                return "queued"
            self._running.add(tid)
            self._cancel[tid] = False
            return "started"

    def finish_full(self, tid: str) -> tuple[str, list[str]] | None:
        """回合结束。返回下一条待发消息 (原文, 图片列表)（FIFO 出队），没有则 None。"""
        with self._lock:
            self._running.discard(tid)
            self._cancel[tid] = False
            q = self._queues.get(tid)
            if q:
                return q.popleft()
            return None

    def finish(self, tid: str) -> str | None:
        """回合结束。返回下一条待发消息（纯原文），没有则 None。

        调用方拿到非 None 时应重新调 try_start 起下一回合。
        """
        item = self.finish_full(tid)
        return item[0] if item is not None else None

    # ---- 队列观测
    def queued_count(self, tid: str) -> int:
        with self._lock:
            return len(self._queues.get(tid) or ())

    def queued_texts(self, tid: str) -> list[str]:
        """该 thread 排队中的全部消息原文（FIFO 顺序 list 副本，改动不影响队列本体）。"""
        with self._lock:
            return [t for t, _imgs in (self._queues.get(tid) or ())]

    def pull_out(self, tid: str, text: str) -> bool:
        """撤出队列：移除原文精确匹配的第一条。返回是否命中。"""
        return self.pull_out_full(tid, text) is not None

    def pull_out_full(self, tid: str, text: str) -> tuple[str, list[str]] | None:
        """撤出队列（带回随载荷）：移除原文精确匹配的第一条，返回 (原文, 图片)。"""
        with self._lock:
            q = self._queues.get(tid)
            if not q:
                return None
            for i, item in enumerate(q):
                if item[0] == text:
                    del q[i]
                    return item
            return None

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