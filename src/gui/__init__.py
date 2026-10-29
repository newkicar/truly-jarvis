"""GUI 桌面端（PySide6）——同进程 MVP（架构 A，见 .scratch/gui-desktop/spec.md）。

薄 presenter 层：runtime 装配（agent/checkpointer/permissions 与 TUI/CLI 同源）+
Qt 事件泵 + 每 thread 回合门；worker 线程跑 run_agent_turn，UI 线程只消费信号。
"""
