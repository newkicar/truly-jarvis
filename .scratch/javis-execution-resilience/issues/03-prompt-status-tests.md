# 03 — 执行纪律 prompt + 状态事件 + 回归

**What to build:** 提示词层执行循环铁律；CLI/TUI on_status 状态行；全量测试保绿。

**Type:** task
**Status:** done
**Blocked by:** 01, 02

## 范围

- [x] 重写 `JARVIS_HARNESS_SUFFIX`：≥3 步必须 write_todos 分解；执行→核对→失败即诊断根因→修正→再执行循环；唯一停下条件=3 种不同方案仍失败→报告已尝试清单+卡点+建议；完成声明附验证证据
- [x] 同步更新 `TOOL_DESCRIPTION_OVERRIDES` 的 execute / task 描述
- [x] CLI/TUI `on_status` muted 状态行接线（重试进度可见）
- [x] `tests/test_resilience.py` + conftest 更新；全量测试绿（280 存量 + 新增）

## Resolution

实现：`src/agent.py` prompt、`src/main.py` / `src/tui.py` on_status、`tests/test_resilience.py`。
