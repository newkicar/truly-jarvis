# 02 — 步数预算配置化 + 软着陆 + doom-loop 防御

**What to build:** 解除 recursion_limit=30 自缚；接近预算软着陆；病理循环检测。

**Type:** task
**Status:** done
**Blocked by:** —

## 范围

- [x] `javis.json` 新增 `execution.max_steps`（默认 200），Config 解析；streaming / scheduler 全部改读配置（deepagents 官方姿态：图默认 9999，我们用配置上限）
- [x] `StepBudgetMiddleware`（wrap_model_call）：剩 ≤3 步时注入一次性提醒「收敛工作并总结交付」（ModelRequest.override，不污染历史）
- [x] `DoomLoopMiddleware`（wrap_tool_call）：同名同参且失败连续 3 次 → 工具结果尾部附加引导；成功调用清零 streak（轮询合法）
- [x] 中间件挂主代理（子代理经 task 内部继承 deepagents 默认高限）
- [x] 单测：预算注入触发/不触发；doom-loop 第 3 次附加引导、成功后清零

## Resolution

实现：`src/resilience.py::StepBudgetMiddleware/DoomLoopMiddleware`、`src/config.py::execution_max_steps`、
`src/agent.py::build_agent` 挂载、`src/scheduler.py` 读配置。
