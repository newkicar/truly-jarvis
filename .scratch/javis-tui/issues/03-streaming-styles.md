# 03 — 流式输出 + 消息样式

**What to build:** TUI 里跑真实对话：用户输入普通文本 → 后台 worker 消费 `agent.stream_events(v3)` → AI 回答逐字实时出现在消息区，工具调用 / 子代理状态即时显示，Esc 可取消当前轮次。消息样式对标 opencode：AI 回答左侧 primary 粗竖线 + 末尾模型名与耗时、工具调用 muted 色 `工具名(参数摘要)` + 结果预览 ≤10 行、子代理黄色标题嵌套缩进。

**Blocked by:** 02 — TUI 骨架 + 命令路由

**Status:** done

- [ ] `@work(thread=True)` 后台线程消费 `stream_events(v3)`，`get_current_worker().is_cancelled()` 支持 Esc 中断
- [ ] 用 `call_from_thread` 逐步写入 RichLog：AI 文本逐字出现（消息区跟随滚动）
- [ ] 工具调用显示 `✓/✗ 工具名(参数摘要)`，结果预览截断到 ≤10 行
- [ ] 子代理显示 `[researcher] running` 黄色标题，内部工具调用嵌套缩进
- [ ] AI 回答末尾追加 muted 文本 `模型名 (耗时)`（对标 opencode 的 `mimo-v2.5 (2.3s)`）
- [ ] 用户消息 secondary 色、AI 回答 primary 色、工具调用 muted 色，均带左侧粗竖线
- [ ] Esc 中断当前轮次后 worker 正常回收、不崩溃，可继续输入下一轮
- [ ] 用 `run_test` 冒烟：输入普通文本 → 消息区出现 AI 占位/流式内容；Esc 中断无异常