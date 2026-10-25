# 02: 接桩 agent.py + subagents.py + harness 提示词

**What to build:**
- src/agent.py：import 块（L371-375）追加 StagnationGuardMiddleware；
  在 StepBudgetMiddleware 之后、DoomLoopMiddleware 之前 append 一个**全新实例**；
  JARVIS_HARNESS_SUFFIX（L49-61）追加「搜索停滞」铁律一条。
- src/subagents.py：L7 import 追加 StagnationGuardMiddleware；
  build_researcher 两个 middleware 分支（L67 / L70）各加一个**全新** StagnationGuardMiddleware()
  （有状态，绝不共享 _ERROR_BOUNDARY 那个实例）；
  RESEARCHER_PROMPT 追加一行搜索停滞纪律（搜 3 次没新信息就换挡/作答/报告卡点）。

**Blocked by:** 01。

**Status:** done

- [ ] agent.py 中间件顺序 = StepBudget -> StagnationGuard -> DoomLoop（DoomLoop 最内层）
- [ ] subagents.build_researcher 两分支均含全新 StagnationGuard 实例
- [ ] harness suffix 含搜索停滞铁律
- [ ] 不共享有状态实例（researcher 无 deny / 有 deny 两分支各自独立）
