# 02 — TUI 骨架 + 命令路由

**What to build:** 一个可启动、可交互的 JARVIS TUI 骨架：顶部状态栏、中部消息区、底部输入框、底部功能键栏。用户在输入框输入 `/` 开头命令时，走 `commands.py` 分发并把结果显示到消息区；输入普通文本时先占位显示（流式对话在 03 实现）。

**Blocked by:** 01 — 命令分发逻辑（抽取 commands.py 公共命令层）

**Status:** done

- [ ] `src/tui.py` 新建 `JarvisApp(App)`：Header（标题 + 会话 id + MCP 工具数）+ 消息区（RichLog，wrap）+ 输入框（Input，底部）+ Footer（键位提示）
- [ ] 输入框 Enter 提交：`/` 前缀 → 调用 `commands.dispatch_command` → 结果显示到消息区；非命令 → 消息区占位提示「（流式对话将在下一阶段接入）」
- [ ] 消息区支持展示用户消息与命令结果，用户消息带左侧粗竖线样式（对标 opencode：secondary 色）
- [ ] 键位：`ctrl+c` 退出、`Tab` 焦点在输入框/消息区/Footer 间切换
- [ ] 用 `async with app.run_test()` 冒烟：app 能启动、输入 `/sessions` 后消息区出现会话列表、app 能退出
- [ ] `requirements.txt` 加 `textual>=0.40.0`