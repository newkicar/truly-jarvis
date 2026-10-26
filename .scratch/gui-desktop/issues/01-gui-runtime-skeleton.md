# 01 — GUI 运行时骨架（架构 A 装配 + 最小可对话窗口）

**What to build:** `python -m src.gui_main`（新装配入口，TUI/CLI 入口零改动）启动 PySide6 窗口：左侧占位、中间对话区、底部输入框，接**真实**模型完成一轮对话并流式上屏。落地 `src/gui/` 四个模块的骨架（装配 / presenter 事件泵 / 回合门 / 最小 ask_action 兜底）——worker 线程跑 `run_agent_turn`，5 键 StreamCallbacks 经 Qt 信号回主线程渲染（worker 永不直接碰 widget），每 thread 独立消息栈 + 同 thread 回合门（执行中再发=拒绝并提示）。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 运行新入口：输入→流式回答逐字上屏→完成，检查点落 SqliteSaver（与 TUI 同一 db 语义）
- [ ] 既有 200+ 单测全绿（streaming/commands/permissions 零行为改动回归网）
- [ ] 同 thread 回合门：执行中再发一条 → 提示「该会话已有回合在进行」
- [ ] worker→主线程事件契约有 offscreen 单测（信号 payload 形状，原型 smoke 模式）
- [ ] 取消按钮 → 当前 superstep 跑完即停（banner「已取消，正在收尾」）
