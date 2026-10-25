# 01: StagnationGuard 中间件核心 + 纯函数助手（src/resilience.py）

**What to build:**
- 在 src/resilience.py（DoomLoop 之后，文件尾 L380 后）新增：
  - 常量 STAGNATION_WINDOW=6 / STAGNATION_SOFT=3 / STAGNATION_HARD=6 / STAGNATION_JACCARD=0.7；
  - STAGNATION_SOFT_GUIDANCE / STAGNATION_HARD_BREAK 文案；
  - 纯函数 arg_tokens(args) -> frozenset[str]（规范化 JSON 小写 -> ASCII 字母数字 >=2 段 + CJK 双字）；
  - 纯函数 token_similarity(a,b) -> float（Jaccard，双空 1.0 / 一空 0.0）；
  - class StagnationGuardMiddleware(AgentMiddleware)：name="stagnation-guard"，
    _windows/_streaks 双 dict，scope 取 thread_id（对象属性或 dict 两种 request，缺省 "default"）；
    wrap_tool_call / awrap_tool_call（近似重复两级处置，硬熔断惰性 import ToolMessage，不执行 handler）；reset()。
- 追加 tests/test_resilience.py 用例 1-9（助手边界、合法轮询不误伤、软/硬阈值、清零重武装、工具独立、
  线程隔离、异步镜像）。

**Blocked by:** 无（基础件）。

**Status:** done

- [ ] arg_tokens 支持 CJK+ASCII，None -> frozenset()
- [ ] token_similarity 边界正确（∅∅/∅-非空/互不相交）
- [ ] 合法轮询（零共享 token 的同命令不同参数）全程不误报
- [ ] 软引导在第 3 次近似重复（第 4 次总调用）出现
- [ ] 硬熔断在第 6 次近似重复（第 7 次总调用）出现，handler 不执行（抛错证伪）
- [ ] 显著不同参数清零重武装
- [ ] 工具独立计数
- [ ] 线程（thread_id）隔离
- [ ] 异步 awrap_tool_call 与同步一致
