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
    # 审批决策完成 → 焦点回输入框（工单 04；G7 携带 tid 撤待审批卡）
    focus_input = Signal(str)
    # undo 等消息层操作后 → 主线程重建该 thread 的 pane 记录（工单 08）
    rebuild_pane = Signal(str)
    # 分支（fork）出新会话 → 主线程切换（工单 09）：new_tid, note
    switch_session = Signal(str, str)
    # 任务完成三通道通知载荷（TaskDoneEvent：会话回合/定时任务，含后台项目；queued 信号 worker→主线程安全）
    task_done = Signal(object)
    # 排队消息重投入门（tid, 原文, 图片列表）→ 主线程把用户气泡补入 pane；气泡仅在回合真正开跑时上屏（gui15 G5；
    # #2：图片随队列载荷走，排队重投不丢图、不跨会话泄漏；第 3 参为 list[str]，声明 object 以便跨线程队列）
    queued_flush = Signal(str, str, object)
    # 命令 worker 完成后 → 主线程重同步模式面（菜单 YOLO 勾选 / [YOLO] 徽标；
    # /yolo 等改共享 permission_state 的斜杠命令在 worker 线程执行，UI 三件套须回主线程单一同步点刷新）
    sync_modes = Signal()

