# 15 — 动态子代理 fan-out（CodeInterpreterMiddleware 接入主代理）

**What to build:** 复杂/多角度研究时，主代理写 JS 脚本用内置 `task()` + `Promise.all` 并行派发多个 researcher 子代理，再合并结果。设计文档标注 beta，须先实测 deepseek-v4-flash 写 JS 能力。

**Blocked by:** 批1-A（事件流式，stream_events v3）已 done

**Status:** resolved

## 先实测（已通过）

`tests/_manual/fanout_probe.py` 用真实 go 套餐模型跑最小 agent（+CodeInterpreterMiddleware），提示写 JS 并行派发 2 个 researcher。结果：
- 消息序列 `human→ai→tool×6→ai`，共 6 次 tool 调用
- 模型明确写出 JS，用 `Promise.all` 并行派发 2 个 researcher 子代理研究两个角度，再合并返回总结
- **结论：deepseek-v4-flash 具备写可执行 JS 做 fan-out 的能力**

## 接入（agent.py）

- `middleware=[CodeInterpreterMiddleware(subagents=True)]`（langchain_quickjs 提供，Python 3.12 + langchain-quickjs>=0.2.0 满足）
- 主代理 system_prompt 加「复杂/多角度研究 → 写 JS fan-out」路由
- 所有 agent 实例（CLI 会话、scheduler `_run_task`）默认启用动态子代理

## 关键决策

- **自动 fan-out**：用户无需手动触发，复杂研究自动走 fan-out；`subagents=True` 使 task() 全局可用。
- **beta 接受**：实测通过才接入（遵循设计文档「先实测，不行回退串行」约定）。CodeInterpreterMiddleware 是 beta，API 可能变。
- **保留探针**：`tests/_manual/fanout_probe.py` 留作回归，非 pytest 收集。

## 验收

- [x] 实测 deepseek 能写 JS 做 fan-out（探针通过）
- [x] 主代理接入 CodeInterpreterMiddleware(subagents=True)
- [x] 主代理 system_prompt 加 fan-out 路由
- [x] 全套单测仍绿（27 pass，仅 beta 警告）
- [x] 设计文档二期「多角度并行研究」勾选