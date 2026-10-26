# 10 — 命令体系与补全（斜杠菜单 · @路径 · /use 模糊 · 主题 · MCP · 定时任务）

**What to build:** 小白友好的命令与能力面板（spec「斜杠命令收纳进命令菜单」）：命令菜单（列全部斜杠命令，搜索框可筛）替代裸输入斜杠；`@` 路径补全（workspace 优先，虚拟前缀降级快捷方式语义不变）；`/use` skill 手动注入 + 名称模糊补全（复用 skill_discovery.fuzzy_filter_skills 纯函数，`/use` 执行内核与 CLI 不变，manual-only skill 语义保持）；`/` 命令补全；明暗主题切换 + 写回持久化（ctrl+t 对应 GUI 菜单，theme 字段回写 jarvis.json）；MCP 工具（jarvis.json `mcps.servers` 即插即拔、单 server 失败跳过+警告、工具名带前缀出现在工具行/详情）；定时任务面板（schedules/ 目录增删=加删文件、热重载、启用时同 app 单 scheduler——遗留 d：后启动者检测 runtime 已存在不双开）。

**Blocked by:** 03（对话区与输入区）、05（会话侧栏与命名）

**Status:** ready-for-agent

- [ ] 命令菜单列全量斜杠命令 + 搜索筛选；`@`/`/`/`/use` 补全在输入框可用（Tab 接受/Enter 发送语义）
- [ ] `/use <skill>` 注入成功（manual-only 可手动调用），skill 模糊补全命中规则与 TUI 一致
- [ ] 主题切换 + 持久化（重启恢复）
- [ ] MCP 工具出现在工具行与详情（server 前缀）；单 server 连接失败=警告不崩
- [ ] 定时任务面板：增删文件即增删任务、热重载生效；未启用时 scheduler 不启动（遗留 d）
