# ADR-0008: Esc 取消的 drain 语义（RunControl，非 SIGKILL）

**状态:** 已接受（2026-10-18）

## 背景

TUI/CLI 按 Esc 取消 worker 时，旧实现只翻转 `is_cancelled` 标志，而 `consume_stream_events` 是纯拉取式消费：它只在事件到达时检查标志。慢工具（如 `execute` 长命令）执行期间**没有任何事件产出**，取消信号要等到命令跑完、下一条事件到达才可能被感知——实测（`scratch/probe_drain.py` noctrl 模式）取消 0.5s 后触发，stream 仍跑满 2.57s（两轮模型 + 2s 工具全部执行完），取消等于没按。用户报告：「任务执行中途按 esc，提示（已中断），但实际上并未立刻切断，有时候还是会继续执行」。

## 决策

1. **取消通道 = `langgraph.runtime.RunControl` drain**（langgraph ≥1.2 原生能力，无需自研信号传递）：`run_agent_turn` 的每个 stream 尝试（含 HITL resume 每轮）新建一个 `RunControl()`，传入 `agent.stream_events(..., control=control)`。
2. **消费层接法**（`consume_stream_events` 增 `control=None` 参数）：取消命中（`is_cancelled()`）且 `control` 非 None → `on_cancelled()` + `control.request_drain("user-cancel")`（恰好一次），置 draining 标志；drain 期间**抑制全部后续回调**（消息 delta、工具、子代理均不再推 UI），让 `GraphDrained` 从流中自然上抛。`control=None` 保持旧语义（取消命中立即 return，图继续按自身节奏跑满）——CLI 等未接 control 的调用方行为不变。
3. **异常路径**：`_stream_with_resilience` 在 generic except 之前加 `except GraphDrained: raise`——取消**不是 API 错误**，不进韧性重试/退避，不做 checkpoint 清理（与 fatal 异常路径区分）；`run_agent_turn` 外层 `except GraphDrained` → `outcome = "cancel"`，返回 False（不走 `force_handoff`，与步数超限不同路），`finally` 统一走 `_finalize_if_needed`。TUI 侧零改动：`run_agent_turn` 正常返回 False，`tui_turn` finally 照旧写「（已取消）」。
4. **drain 语义定稿（本 ADR 核心）**：Esc 取消 = 「**正在执行的当前命令/superstep 跑完后停止，后续步骤全部跳过**」。即：
   - 当前 LLM 调用正在进行 → 等它出完 token（流式 token 逐条仍在到达，取消在下一个 delta 间隙生效）；
   - 当前工具/命令（含 2s 的 `execute`）正在执行 → 等它执行完，图在下一个 superstep 边界停止；
   - 停止后：后续模型调用、后续工具调用、后续子代理**一律不发生**；
   - **不做进程级 SIGKILL**：不杀 `execute` 子进程，不做 Python 线程强杀（Textual worker 线程本就不可安全强杀，且 langgraph 无该能力）。
   对用户可见的提示语义保持「（已取消）」，但文档/汇报需说明：已启动的长命令会跑完才停，不是按下 Esc 世界立刻静止。

## 被否决的选项

- **自研取消标志 + 图内轮询**：工具执行在 langgraph 内部同步进行，无注入检查点的位置；给每个工具包一层「每 100ms 查标志」的 wrapper 覆盖不到 LLM 调用本身。
- **kill `execute` 子进程（SIGKILL 路线）**：需要把 shell 进程句柄一路穿透 deepagents/shell backend，实现面大且跨平台（Windows 无 SIGKILL）；取消语义被放大为「杀用户命令」，误伤面大（长构建被误杀）。
- **worker 线程直接 `raise SystemExit`/强杀**：Textual worker 在线程池里，强杀线程会留下半写的 checkpoint 与未收尾的 RichLog，且 `finally` 的 finalize 不可靠。
- **每次取消新建整张 graph 实例**：昂贵且与「同一会话继续」语义冲突；RunControl 本来就是 per-run 粒度，无需重建。

## 影响

- 变更：`src/streaming.py`（`consume_stream_events` +`control` 参、`_run_stream` 建 RunControl、`_stream_with_resilience`/`run_agent_turn` 的 GraphDrained 分支）；测试 fake agent 的 `stream_events` 签名 +`control=None`（test_streaming / test_resilience / test_clipboard_image）。
- 新增测试：consume 层（假 control 记录 request_drain；取消后回调全抑制；`GraphDrained` 透传；control=None 旧语义）+ e2e（真 RunControl + 2s 慢工具 + 线程 0.3s 后取消 → 断言第二次模型调用未发生、wall-time < 3.5s、`run_agent_turn` 返回 False）。
- 行为变更：此前「取消但图跑满」的窗口期收敛为「取消后当前 superstep 结束即停」；HITL resume 轮次各自独立 RunControl，取消不跨轮泄漏。
