# JARVIS 执行韧性（Execution Resilience）Spec

日期：2026-08-24
状态：implemented
输入：`from_codex_and_opencode_to_deepagents/`（codex_tutor 06/10、opencode_tutor 02/10、deepagents_tutor 02/11/15）

## 问题

当前执行类任务表现为「执行 → 遇到问题 → 中断」，无法完成
「任务分解 → 执行 → 检查 → 纠错 → 再执行 …… 直到交付」。

病灶（诊断于 2026-08-24，证据见票）：

| # | 病灶 | 位置 |
|---|------|------|
| 1 | `recursion_limit: 30` 硬编码，多步任务超限即 `GraphRecursionError` 硬中断（deepagents 官方图默认 9999） | streaming.py / scheduler.py |
| 2 | 无错误分类学：仅 400 重试一次；429/5xx/流断直接 raise 整轮死亡 | streaming.py |
| 3 | 步数耗尽无软着陆（对标 opencode MAX_STEPS_PROMPT） | — |
| 4 | 提示词「都失败则说明不确定」把调研诚实条款泛化到执行任务＝授权放弃 | agent.py harness suffix |
| 5 | 无 doom-loop 防御（复读机式失败无人拦截） | — |
| 6 | ChatOpenAI 未设 max_retries / timeout | agent.py |

## 方案（对标 codex/opencode harness 可靠性工程）

### 01 · 错误分类学 + 重试（harness 层）
- `src/resilience.py`：`classify_error()` 决策表（aborted/auth/context_overflow/retryable/fatal）
  + `with_retry()`（2s×2 指数退避、±25% 抖动、retry-after 头优先、上限 5 次、致命白名单）。
- `run_agent_turn` retryable 错误不再 raise：发 muted 状态行后重试；400-repair 并入。
- ChatOpenAI 显式 `max_retries=3, timeout=120`。
- `GraphRecursionError` 兜底转友好提示 + finalize。

### 02 · 步数预算配置化 + 软着陆 + doom-loop
- `javis.json` `execution.max_steps`（默认 200）；streaming/scheduler 全部改读配置。
- `StepBudgetMiddleware`（wrap_model_call）：接近预算注入一次性提醒
  「收敛工作并总结交付」——只改本次请求（ModelRequest.override），不污染历史。
- `DoomLoopMiddleware`（wrap_tool_call）：同名同参**且失败**连续 3 次 →
  在工具结果尾部附加引导「禁止原样重试，先诊断根因或换方案」；成功调用不拦（轮询合法）。

### 03 · 执行纪律 prompt + 状态事件 + 测试
- 重写 harness suffix：≥3 步必须 write_todos；执行循环铁律
  （执行→核对→失败即诊断→修正→再执行）；唯一停下条件=3 种不同方案仍失败→报告已尝试清单+卡点；
  完成声明必须附验证证据。
- CLI/TUI 增加 `on_status` muted 状态行（重试进度可见）。
- `tests/test_resilience.py` 全覆盖；存量 280 测试保绿。

## 非目标（对标 opencode V2 的克制）

- 崩溃后自动续跑（provider 歧义写问题无法可靠猜测）——保留手动 `/replay`。
- 上下文压缩自定义（SummarizationMiddleware 未默认挂载的问题另开票观察）。
