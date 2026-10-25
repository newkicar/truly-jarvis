# 停滞防御 StagnationGuard —— 设计 spec

状态：设计与外部调研已定案；本 spec 是落地蓝图。日期 2026-10-25。

## Problem（问题）
用户问「长春今明两天逐小时天气」，代理对 quick_search 连发 ~27 次**全部成功**的调用，
每次 query = 上一次 + 追加 1 个关键词（逐词膨胀），直到 StepBudget(200) 耗尽才停。

根因（已实证，行号 @ c5d071e）：
- DoomLoopMiddleware（src/resilience.py L293-380）按**精确** (工具名, 规范化 JSON 参数) 签名去重，
  且**只统计失败**（status=="error" 或 execute 退出码 != 0）。
- 本例全部成功 + 参数每次只变一词 → 签名永不重复 + 成功即清零 → DoomLoop 全程哑火。

外部方案调研（强制先查开源，避免闭门造车）：
- opencode：DOOM_LOOP_THRESHOLD=3，同工具 + 完全相同 JSON.stringify(input) → HITL 提示。
  即 opencode 也只认「精确重复」，对「近似成功循环」同样未覆盖（同根因）。
- codex：无语义检测器，靠步数预算 + 上下文压缩 + 更强模型。
- langchain ToolCallLimitMiddleware：按 工具/线程 的生硬计数——对本例「合法批量工作」会误伤，
  且引入 langchain 版本耦合。**刻意不用它做兜底**；保持 resilience.py 纯 stdlib、版本无关。
  分层 DoomLoop + StagnationGuard + StepBudget 已足够。（此决策记录在 spec。）

## Solution（方案：泛化的「停滞」检测，不是生硬限流）
新增 StagnationGuardMiddleware（纯 stdlib、版本无关，追加到 src/resilience.py DoomLoop 之后）：
- 把每次工具调用的参数 token 化（ASCII 字母数字段 + CJK 双字），对滑动窗口内调用做 Jaccard 相似度；
  「近似重复」= 相似度 >= 0.7。
- 两级处置（沿用「提示词是建议，代码才是边界」）：
  - 连续 3 次近似重复 -> 软引导（成功结果尾部追加「别逐词追加，换方法类别/用已有信息作答/报告卡点」）；
  - 连续 6 次近似重复 -> 硬熔断（执行前拦截，返回 error ToolMessage，物理切断原路径）。
- 作用域 = thread_id（每会话独立计数互不串扰）；工具独立（不同工具各自计 streak）。
- 合法批量工作不误伤：窗口只覆盖最近 6 次；真正不同的参数（相似度 < 0.7）立即清零重算。

为什么这样（以小见大）：死循环本质不是「重复同一调用」，而是「在同一方法类别里原地膨胀、
无新信息增益」。近似重复 + 成功 = 模型在死磕一条路。软引导教会它「3 次近似就该换挡」，
硬熔断给弱模型兜底。检测器只认「参数高度相似且近期连续」，不限制绝对次数 -> 不误伤 fan-out/批量。

## User Stories
1. 问「长春逐小时天气」，代理搜 3-4 次发现搜不出更细数据后，要么改用已有信息作答、要么换方法类别、
   要么明确报告卡点，而不是把同一 query 逐词膨胀 27 次烧穿步数预算。
2. 「批量处理 100 个文件 / fan-out 20 个子任务」这类合法高频相似调用，系统不误报、不掐断
   （窗口 + 相似度 + 工具独立 三重隔离）。
3. 维护者读 resilience.py 时，StagnationGuard 与 DoomLoop 同构（wrap_tool_call 预检 + 两级处置 + reset），
   一眼看懂，且无需依赖 langchain 版本细节。

## Implementation Decisions（落地要点，散文级）
辅助纯函数（纯 stdlib，可单测）：
- arg_tokens(args) -> frozenset[str]：args 先做规范化 JSON（ensure_ascii=False, sort_keys=True）再小写，
  抽 ASCII 字母数字 >=2 段 + CJK（\u4e00-\u9fff）字符双字（单字 CJK 段贡献该字符本身）。
  CJK 双字是「长春」类中文 case 的关键。None/空 -> frozenset()。
- token_similarity(a, b) -> float：Jaccard；双空->1.0，一空->0.0。

中间件常量：STAGNATION_WINDOW=6（deque maxlen）、STAGNATION_SOFT=3、STAGNATION_HARD=6、
STAGNATION_JACCARD=0.7。实例状态：_windows[scope][tool]=deque(maxlen=6)、_streaks[scope][tool]=int。
scope 从 request 防御式取 thread_id（支持对象属性与 dict 两种 request，缺省 "default"）。

wrap_tool_call 算法（awrap 镜像）：
  1. new_tokens=arg_tokens(args)；定位 scope/thread；window=本工具窗口；streak=本工具计数。
  2. near = 窗口内任一 Jaccard(new, w) >= 0.7。
  3. 若 near：streak+=1；否则 streak=0（显著不同的调用清零，不同工具互不影响）。
  4. streak >= 6（HARD）-> 返回 error ToolMessage（STAGNATION_HARD_BREAK，保留原 tool_call id/name，
     status="error"，惰性 import ToolMessage，同 DoomLoop._hard_break），不执行 handler、不写窗口。
  5. 否则执行 handler，写入窗口；若 streak >= 3（SOFT）且结果是字符串，尾部追加 STAGNATION_SOFT_GUIDANCE。
  reset() 清空两个 dict。

接桩：
- src/agent.py：import 追加 StagnationGuardMiddleware；在 StepBudget 之后、DoomLoop 之前 append 一个
  **全新实例**（DoomLoop 保持最内层，更精确的「精确重复失败」消息优先）；
  JARVIS_HARNESS_SUFFIX 追加「搜索停滞」铁律（逐词追加同一查询无新信息；连续 ~3 次近似 -> 换方法类别/
  用已有信息/报告卡点；harness 会拦截第 6 次近似）。
- src/subagents.py：build_researcher 的两个 middleware 分支各加一个**全新** StagnationGuardMiddleware()
  （有状态，绝不共享）；RESEARCHER_PROMPT 追加一行搜索停滞纪律；knowledge_keeper 不需要。

## Testing Decisions
全部追加到 tests/test_resilience.py（复用既有 _tool_request 工厂 L173；ToolMessage 已在文件内 import）：
约 10 个用例（详见 issues）：arg_tokens CJK+ASCII/None；Jaccard 边界；合法轮询不误伤；
软引导第 3 次近似（=第 4 次总调用）；硬熔断第 6 次近似（=第 7 次总调用）；显著不同参数清零重武装；
工具独立；线程隔离；异步 awrap 镜像；长春天气回归（逐词膨胀序列，第 4 次软、第 7 次硬）。
跑法：& D:\python_env\python.exe -m pytest tests/test_resilience.py -q（只跑本文件批，不跑全量）。

## Out of Scope
- 不引入 langchain ToolCallLimitMiddleware（生硬计数误伤合法批量 + 版本耦合）。
- 不改 DoomLoop / StepBudget 既有行为；不引入向量/LLM 语义相似度（保持纯 stdlib、可单测、版本无关）。
- 不做跨工具的全局速率限制（工具独立计数已足够）。
