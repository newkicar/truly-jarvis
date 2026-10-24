"""tui-ux14 #04: 插队消息队列——单一事实源 + 主代理 before_model 注入。

回合执行/收尾期间（turn gate 持有），用户新消息按 thread 入 JumpInRegistry，
不进入模型历史；门释放时 UI 层重投队首（03 语义不变，数据源切到本 registry）。
MessageQueueJumpInMiddleware 挂主代理：每次模型调用前（before_model）drain 当前
thread 的缓存并整批注入 HumanMessage——用户在 agent 执行中途输入的插队消息，
模型下一步即可读到；空缓存零开销（返回 None）。

已知边界（记录不解决）：thread-local 与共享 permission_state["thread_id"] 的
并发覆写（fail-safe 方向）；registry 回调在锁外执行，UI 刷新回调异常被吞
（防 worker 线程被 UI 状态带崩）。
"""

import threading
from collections import deque
from typing import Optional

from langchain.agents.middleware.types import AgentMiddleware


class JumpInRegistry:
    """按 thread 的插队消息缓存（UI 单一事实源；线程安全）。

    push/pop/drain/clear 变更数据后触发 on_change 回调（持锁内收集、锁外执行，
    防 UI 回调内再入 registry 造成死锁）。
    """

    def __init__(self) -> None:
        self._queues: dict[str, deque[str]] = {}
        self._lock = threading.Lock()
        self._change_callbacks: list = []

    def push(self, tid: str, msg: str) -> int:
        """入队一条；返回该 thread 入队后的总条数（供 notify 文案用）。"""
        with self._lock:
            q = self._queues.setdefault(tid, deque())
            q.append(msg)
            n = len(q)
        self._fire_change()
        return n

    def pop_first(self, tid: str) -> Optional[str]:
        """弹队首；队空返回 None。"""
        with self._lock:
            q = self._queues.get(tid)
            if not q:
                return None
            msg = q.popleft()
            if not q:
                del self._queues[tid]
        self._fire_change()
        return msg

    def pop_item(self, tid: str, idx: int) -> Optional[str]:
        """按索引弹出（越界返回 None；不移动其他元素）。"""
        with self._lock:
            q = self._queues.get(tid)
            if q is None or idx < 0 or idx >= len(q):
                return None
            msg = q[idx]
            del q[idx]
            if not q:
                del self._queues[tid]
        self._fire_change()
        return msg

    def drain(self, tid: str) -> list:
        """清空该 thread 队列并返回全部消息（FIFO 序）；空则 []。"""
        with self._lock:
            q = self._queues.pop(tid, None)
            msgs = list(q) if q else []
        if msgs:
            self._fire_change()
        return msgs

    def items(self, tid: str) -> list:
        """该 thread 当前队列快照（不触发回调、不移除）。"""
        with self._lock:
            return list(self._queues.get(tid) or ())

    def clear(self, tid: str) -> int:
        """清空该 thread 队列，返回清掉的条数。"""
        with self._lock:
            q = self._queues.pop(tid, None)
            n = len(q) if q else 0
        if n:
            self._fire_change()
        return n

    def snapshot(self) -> list:
        """All-thread queue snapshot ((thread_id, message) table, thread insertion order); no callback fire, no removal."""
        with self._lock:
            return [(tid, msg) for tid, q in self._queues.items() for msg in q]

    def has(self, tid: str) -> bool:
        with self._lock:
            return bool(self._queues.get(tid))

    def count(self, tid: str) -> int:
        with self._lock:
            return len(self._queues.get(tid) or ())

    def on_change(self, callback) -> None:
        """注册变更回调（传 None 清空全部）。回调在锁外调用。"""
        with self._lock:
            if callback is None:
                self._change_callbacks = []
            else:
                self._change_callbacks.append(callback)

    def _fire_change(self) -> None:
        with self._lock:
            callbacks = list(self._change_callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception:  # noqa: BLE001 — UI 刷新回调异常不得炸穿 worker 线程
                pass


_tls = threading.local()


def set_current_thread_id(tid: Optional[str]) -> None:
    """本线程当前对话 thread（threading.local，set/清 成对）。"""
    _tls.thread_id = tid


def get_current_thread_id() -> Optional[str]:
    return getattr(_tls, "thread_id", None)


class MessageQueueJumpInMiddleware(AgentMiddleware):
    """主代理 before_model：drain 当前 thread 插队缓存 → 整批 HumanMessage。

    只注入主代理（子代理无 queue 概念）。无 thread 上下文或空缓存 → 返回
    None（零开销、不改 state）。langchain 按协议调用 before_model 钩子
    （同 StepBudgetMiddleware 的 AgentMiddleware 用法面）。
    """

    def __init__(self, registry, permission_state: Optional[dict] = None) -> None:
        super().__init__()
        self._registry = registry
        self._permission_state = permission_state or {}

    @property
    def name(self) -> str:
        return "jump-in-queue"

    def _run(self, state, runtime):
        tid = get_current_thread_id() or self._permission_state.get("thread_id")
        if not tid:
            return None
        msgs = self._registry.drain(tid)
        if not msgs:
            return None
        from langchain_core.messages import HumanMessage

        return {"messages": [HumanMessage(content=m) for m in msgs]}

    def before_model(self, state, runtime) -> Optional[dict]:
        return self._run(state, runtime)

    async def abefore_model(self, state, runtime) -> Optional[dict]:
        return self._run(state, runtime)
