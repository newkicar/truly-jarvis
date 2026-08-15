# 11 — 事件流式输出（event streaming）

**What to build:** 一期 CLI 用 `agent.invoke()` 一次性同步返回，检索类问题（researcher 多轮工具调用）耗时 1-3 分钟且全程静默，用户无法分辨「正在运行」还是「卡住」。二期改用事件流式输出：实时打印主代理/子代理步骤、工具调用与最终回答，让输出更友好、更易 debug。

**Blocked by:** —（二期独立；依赖一期 researcher 管道定型）

**Status:** resolved

## 背景与动因（2026-08-15 实测）

- 一期 `python -m src.main` 问「这个月国产AI大模型有什么最新消息」等 3 分钟无输出，最终成功返回完整报告。结论：**是「慢」不是「卡」**——CLI 用 `invoke()` 全程静默，进度被吞掉，是打印/反馈不友好的问题。
- 需求拆解：①用户能实时看到「在干嘛」；②debug 时能看到工具调用/子代理状态/报错；③最终回答流式打字机效果。

## 技术方案（已核实 deepagents 0.7.6 + langchain-core 1.5.5 + langgraph 1.2.11 支持）

推荐 **event streaming（新 API，`agent.stream_events(..., version="v3")`）**，而非老的 `agent.stream(stream_mode="updates", subgraphs=True)`。官方 event-streaming 文档开头 Tip 明确：新应用推荐 event streaming——typed-projection 可独立消费每类输出，不用手动解析 chunk。

### 类型化投影（key）

| 投影 | 内容 | JARVIS 用途 |
|---|---|---|
| `stream.subagents` | 每个委派子代理：`.name` / `.status`(started/completed/failed) / `.messages` / `.tool_calls` / `.output` | 打印「[researcher] 开始/完成」 |
| `stream.tool_calls` | 工具执行生命周期：`.tool_name` / `.input` / `.output_deltas` / `.output` / `.error` | 打印「🔧 grep / tavily_search(...)」+ 成败 |
| `stream.messages` | 每次 LLM 调用，message 有 `.text` / `.reasoning` / `.tool_calls` | 最终回答逐字流式打印 |
| `stream.values` | agent 状态快照 | （可选） |
| `stream.output` | 最终状态 | 落库 / 取最终结果 |

### 关键代码形态（参考官方 event-streaming 示例）

```python
stream = agent.stream_events(
    {"messages": [{"role": "user", "content": user_input}]},
    version="v3",
    config={"configurable": {"thread_id": thread_id}, "recursion_limit": 30},
)

for subagent in stream.subagents:
    print(f"[{subagent.name}] {subagent.status}")

for call in stream.tool_calls:
    print(f"🔧 {call.tool_name}({call.input}) -> {call.error or 'ok'}")

for message in stream.messages:
    for delta in message.text:
        print(delta, end="", flush=True)

final_state = stream.output
```

### 注意点

- **reasoning 拿不到**：`message.reasoning` 只在模型暴露 reasoning block 时有值；`deepseek-v4-flash` 是普通对话模型，大概率无，别依赖。
- **checkpoint 不受影响**：stream 同样写 checkpoint，`thread_id` 照传；`/replay` `/fork` 走各自 invoke 路径，无需流式。
- **顺序**：同步消费时协调器与子代理输出交错，要精确时序用 `stream.interleave("messages", "subagents")`；CLI 用 interleave 或直接依需访问各投影即可。
- **工具并发/嵌套**：`subagent.subagents` 支持嵌套子代理递归（二期 fan-out 后可直接复用）。
- **同步 vs 异步**：同步用 `stream_events`；并发/UI 用 `astream_events` + `asyncio.gather`。

## 顺带修复（一期已发现隐患，一并处理）

- `src/tools.py` `tavily_search` 里 `client.search(...)` 未传 `timeout`（`TavilyClient.search` 签名支持 `timeout` 参数）——无超时会挂起；补 `timeout=30`。

## 验收标准

- [ ] `python -m src.main` 问调研类问题，实时看到主代理/子代理步骤、工具调用、最终回答流式输出
- [ ] 长时间静默可定位到具体步骤（而非黑盒）
- [ ] 工具调用失败能看到 `.error`
- [ ] checkpoint / `/sessions` `/history` `/replay` `/fork` 不受影响
- [ ] `tavily_search` 有 `timeout=30`
- [ ] 单测（fake 模型）锁住 `stream_events` 不抛错且能产出最终文本