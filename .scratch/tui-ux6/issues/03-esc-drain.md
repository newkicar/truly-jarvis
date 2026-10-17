# 03 — Esc 取消真切断（RunControl drain，ADR-0008）

**What to build:** worker 取消（Esc）目前只翻转 `is_cancelled` 标志，`consume_stream_events` 在事件到达时才检查 → 慢工具（execute 长命令）期间图继续跑满。改用 `langgraph.runtime.RunControl` drain：

- `src/streaming.py`：
  - `_run_stream`（每次 stream 尝试，含 HITL resume 每轮）：新建 `control = RunControl()`，`agent.stream_events(stream_input, version="v3", config=config, control=control)`；把 `control` 传给 `consume_stream_events`。
  - `consume_stream_events` 增 kwarg `control=None`：取消命中 → `on_cancelled()` + `control.request_drain("user-cancel")`（control 为 None 时保持旧语义直接 return）；置 draining 标志，后续迭代只 continue（抑制所有回调），让 `GraphDrained` 自然上抛（graph 排空当前 superstep 后抛出）。
  - `_stream_with_resilience`：generic except 前加 `except GraphDrained: raise`——**不重试、不 finalize**（取消不是 API 错误）。
  - `run_agent_turn`：外层 `except GraphDrained` → `outcome = "cancel"; return False`（finally 自动 finalize；不走 handoff）。
- `src/tui_turn.py` 零改动：drain 后 `run_agent_turn` 正常返回 False，finally 写「（已取消）」。
- `docs/adr/0008-cancel-drain-semantics.md`：drain 语义定稿。
- 测试（`tests/test_streaming.py` 追加）：
  ① consume 层：假 control（record `request_drain`）+ 假 stream，`is_cancelled` 翻转 → 断言 request_drain 被调一次、后续回调被抑制、stream 在 drain 后若抛 `GraphDrained` 则透传；
  ② e2e：`TProbe` fake model（`bind_tools` 返回 self）+ 2s 慢工具 + 真 `RunControl`，线程 0.3s 后翻转取消 → 断言 wall-time ≈ 单次慢工具时长（~2s 而非 ~4s，第二次模型调用未发生），返回 False。

**Type:** bug
**Status:** done (2026-10-18, commit 3bbc5f8)
**Blocked by:** 无（与 01 独立）

## 验收
- [x] ADR-0008 写入（drain 语义：当前 superstep/命令跑完即停，后续步骤跳过，非 SIGKILL）
- [x] 探针红/绿对照（noctrl 2.57s vs drain 0.51s）写进 Comments
- [x] consume 层 + e2e 单测绿（慢工具只跑一次）
- [x] 全量 pytest 无新增失败

## Comments
diagnosing-bugs 六阶段痕迹：
- Phase 1 假设：① 取消标志传播滞后（stream 不感知）② Textual worker.cancel 语义只停 worker 线程 ③ langgraph stream 无取消通道。
- Phase 2 红灯：`scratch/probe_drain.py noctrl` → 取消 0.5s 后触发，stream 仍跑满 **2.57s**（2 轮模型 + 2s 工具完整执行完，取消无效）。
- Phase 3 根因：`agent.stream_events` 不传 control 时，消费循环是纯拉取式，图在独立线程按自己的节奏跑满；`is_cancelled` 只能在事件间隙生效（慢工具期间无事件 → 感知不到取消）。
- Phase 4 绿灯：同探针 `drain` 模式 → **0.51s 抛 `GraphDrained`**（0.5s 时 request_drain，图跑完当前 superstep 即停，exit=0）。
- Phase 5 回归：本票单测（drain 后只跑一次慢工具、二次模型调用不发生）+ 全量。
- Phase 6 复盘：取消语义定稿入 ADR-0008——**正在执行的当前命令跑完后停止，后续步骤跳过；不做进程级 SIGKILL**。


实施记录（2026-10-18, commit 3bbc5f8）：
- `src/streaming.py`：`consume_stream_events(+control=None)` 取消命中 `request_drain("user-cancel")` 一次 + draining 抑制后续回调，`GraphDrained` 自然上抛；`_run_stream` 每 attempt 新建 `RunControl()`；`_stream_with_resilience` 与 `run_agent_turn` 各加 `except GraphDrained` 分支（不重试/不退避/不 handoff，finally 统一 finalize）。
- 测试 fake 的 `stream_events` 签名 +`control=None`（test_resilience/test_clipboard_image）；test_tui fake 走 `*args,**kwargs` 天然兼容。
- `tests/test_streaming.py` 新增 4 条：consume 层假 control 记录 request_drain / GraphDrained 透传 / control=None 旧语义 / e2e 真 RunControl + 2s 慢工具（断言 model_calls==1、wall<3.5s、返回 False）。
- 修一处 off-by-one：`_DrainStream` 的 drain 检查点必须放在 yield 之后（生成器恢复时求值），与真实 Pregel 排空语义对齐。
