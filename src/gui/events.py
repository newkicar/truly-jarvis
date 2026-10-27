"""worker 线程 → 主线程（Qt UI 线程）的事件桥（Qt 信号）。

worker 永不直接碰 widget：run_agent_turn 的 5 键 StreamCallbacks 在 worker 里
emit 信号，Qt 队列信号把 handler 调度到主线程执行。契约：
- 每个信号首参是 thread_id（每 thread 独立消息栈，切会话=换栈不重建 runtime）。
- create_card 携带 ask_action 的载荷（卡片对象在主线程创建，见 tickets 04）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class UiBridge(QObject):
    # 流式回答增量 / 结束（整段文本）
    message_delta = Signal(str, str)
    message_end = Signal(str, str)
    # 无 stream 回调时的兜底消息（force_handoff / 取消收尾）
    fallback = Signal(str, str)
    # 工具调用完成（name, args, err, output, depth）
    tool_call = Signal(str, str, str, bool, str, int)
    # 子代理状态（name, status, depth）
    subagent = Signal(str, str, str, int)
    # 思考块增量（tid, delta）——可选第 6 键 on_thinking 的 GUI 端（工单 06）
    thinking = Signal(str, str)
    # 状态行（重试退避 / 步数预算）
    status = Signal(str, str)
    # 回合开始（tid）——FIFO 重投 / 用户提交
    turn_started = Signal(str)
    # 回合结束（tid, ok）
    turn_done = Signal(str, bool)
    # HITL 卡片创建请求（tid, payload, card_id）——payload 由 runtime 组装
    create_card = Signal(str, object, str)
    # 会话列表需要刷新（新增/删除 thread）
    refresh_sessions = Signal()
    # 轻提示（状态行一次性文案）
    notify = Signal(str)
    # 审批决策完成 → 焦点回输入框（工单 04）
    focus_input = Signal()
