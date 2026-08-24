# 01 — 错误分类学与重试

**What to build:** `src/resilience.py` 错误决策表 + 指数退避重试；接入 `run_agent_turn`；模型层调参。

**Type:** task
**Status:** done
**Blocked by:** —

## 范围

- [x] `classify_error(exc)` → aborted / auth / context_overflow / retryable / fatal
- [x] `with_retry()`：2s 起 ×2 退避 ±25% 抖动、retry-after 头优先、上限 5 次、致命白名单（context 超限/鉴权绝不重试）
- [x] `run_agent_turn`：retryable → muted 状态行「第 N 次重试，Xs 后」→ 重试；400-repair 并入决策表；GraphRecursionError 兜底友好提示 + finalize
- [x] ChatOpenAI 显式 `max_retries=3, timeout=120`
- [x] 单测：假 agent 先抛 retryable 再成功；auth 不重试；退避序列计算

## Resolution

实现：`src/resilience.py`（分类/退避/重试）、`src/streaming.py::run_agent_turn` 重试循环、
`src/agent.py::_make_model` 调参。测试：`tests/test_resilience.py`。
