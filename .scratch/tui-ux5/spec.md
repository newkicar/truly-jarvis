# TUI 体验五（tui-ux5）

**Type:** enhancement
**Status:** open

## 背景（用户报告 5 项 + 讨论定稿决策）

1. **撤回 / time travel**：输入一半误按回车发出后无法撤回；codex 多次按 Esc 可回退消息，opencode 有 /undo。定稿：消息层 `/undo [N]` + TUI 空闲态双 Esc（1.5s prime）；纯消息层不动文件/Inbox；可撤到空白（head 外科式 RemoveMessage，as_node="model"）；HITL 悬挂随回退作废；空闲单 Esc 不再退出。
2. **弹窗过长按钮被遮**：EditParamsModal 当前零 CSS（事故主因）；PermissionModal 内容长时按钮行被推出可见区。定稿：统一 Modal 布局规约（内容容器 width:80%; height:auto; max-height:70%；body overflow-y:auto；按钮行固定底部）+ 24 行短终端测试。
3. **永久放行区分命令类型**：现在 execute 永久放行 = 整工具 allow。定稿：execute 写回前缀规则 `"<prefix> *": allow`（前缀=首 token，shell 包装两级提取，Modal 可编辑）；文件工具保持整工具放行；只读启发式表内置，`permissions.heuristics` 默认 false。
4. **disable-model-invocation skill**：SKILL.md frontmatter 标注 `disable-model-invocation: true` 时，该 skill 只允许用户手动 /use 调用，模型不可自动调用、system 也不注入其介绍。定稿：`JarvisSkillsMiddleware` 子类（agent.py 停传 skills=）；新命令 `/use <skill> [说明]` + `/skills`（manual 打 [manual]）。
5. **git bash 中文标点/引号/破折号录不进**：definitive 修复需先探测真实输入记录形态。定稿两步：① `src/input_probe.py` 探测（用户在 git bash 跑一次回传输出）② ime_shim KEY_EVENT NUL-uChar 重建（MapVirtualKeyW，仅无修饰键+非控制键+结果非 ASCII 才并入字符流）+ CP 告警（不自动 SetConsoleCP）。验收：`" ' — … ，。、` 全进框。

## ADR
- docs/adr/0005-undo-message-layer.md
- docs/adr/0006-approval-prefix.md
- docs/adr/0007-manual-only-skill.md

## 方案（工单 01–12，实施顺序即编号；08/09 同一簇，先 09 后 08）

### 01–02 Modal 布局规约（01, 02）
- 规约：内容容器 `width: 80%; height: auto; max-height: 70%`；body `overflow-y: auto`；按钮行固定模态底部。
- EditParamsModal（零 CSS，事故主因）按规约重写：可滚动输入列表 + 按钮行固定底部。
- PermissionModal preview 改弹性（min-content → max 12 行）；PunctPanel（list h14）/ CopyPicker（list h6）审计；新 PrefixModal（04）同规约。
- 测试：24 行短终端 mount 各 modal，断言按钮行可见可点。

### 03–05 审批前缀与启发式（03, 04, 05）
- `permissions.extract_command_prefix(cmd)`：首 token；shell 包装两级（cmd /c、powershell|pwsh -Command|-c、bash|sh -c、wsl -e）。
- `approve_prefix(state, prefix)`：字符串规则先升格 `{"*": 原值}`，再追加 `"<prefix> *": "allow"`（fnmatch 最后匹配胜出不变）。
- `commands.always_approve` 签名 → `(state, tool, args=None)`：execute+args → 前缀路径；文件工具 → 原整工具；无 args 保持旧行为。CLI on_always_approve 传 args。
- PrefixModal：单 Input 预填提取前缀 + 说明行「将写回: "<prefix> *": allow」+ 确认/取消；PermissionModal 永久放行 execute → PrefixModal，文件工具 → 原流程。
- 启发式：`HEURISTIC_SAFE_COMMANDS` 小写元组（get-date/whoami/hostname/get-location/pwd/ls/dir/get-childitem/get-content/git status/git log/git diff/get-process/tasklist/echo），匹配=命令小写前 1–2 token 命中；`_action_for_args` 尾段 action=="ask" 且 tool=="execute" 且 state.heuristics 且命中 → "allow"；`build_permission_interrupts` 读 `permissions.get("heuristics", False)` 入 state；`current_permissions` 仅 True 时带该键（dump_permissions_json 是整体替换 data["permissions"]，勿吞用户配置）。

### 06–07 撤回（06, 07）
- `commands.undo(agent, tid, n=1)`：history=get_state_history（旧→新）；input_idxs=source=="input"；k 次：idx=input_idxs[-1-k]，idx>0 → `agent.update_state(thread_config(tid, 父 checkpoint), None)`（_rollback 同款原语）；idx==0（撤到空白）→ head 消息末条 HumanMessage 起全部 RemoveMessage，`update_state(thread_config(tid), {"messages": [...]}, as_node="model")`（fork 先例）。
- TUI：`/undo [N]` 特判 → worker 跑 undo → call_from_thread transcript 重建（log.clear() + render_session_text + 结果横幅）。
- 双 Esc：`_esc_primed_at`，空闲双按（≤1.5s）触发 /undo 1（含 _bump/_mark_hitl_resolved 舞蹈）；空闲单 Esc 不再退出（退出保持 ctrl+q / ctrl+c）；worker 活跃 Esc 取消语义不变。

### 08–09 manual-only skill（09 先 08 后，一簇一 commit）
- skill_discovery：SkillMeta 加 `manual_only: bool`、`fs_path: Path`（frontmatter `disable-model-invocation: true` → manual_only；层覆盖与原生 last-one-wins 对齐）。
- `/use <skill> [说明]`：`build_skill_use_message(config, name, extra)` 读 fs_path utf-8、剥 frontmatter（复用 _FRONTMATTER_RE）→ 本轮 user 消息 `[skill:name] 全文+任务`；查无 → None，调用方列可选名。TUI 特判 + CLI 输入循环前置拦截。`/skills` 清单（[manual] 标记，模型可见的也能 /use）；/doctor skills 表加列；slash_completion 补 /undo /skills /use。
- `src/jarvis_skills.py`：`JarvisSkillsMiddleware(SkillsMiddleware)`，`__init__(backend, sources, flagged)`；modify_request：flagged 空 → super()；否则复刻 base 模板填充但 skills_metadata 先按名过滤（_format_* 复用）；agent.py 停传 skills=、middleware 追加子类（backend 取一次共享）。副作用：GP 子代理失去 skills 注入（ADR-0007 注明可接受）。

### 10–11 输入通道探测与中文标点（10, 11）
- `src/input_probe.py`：`python -m src.input_probe [out.txt]` dump 每条 INPUT_RECORD 全字段（KEY/UNICODE/IME 事件类型 + uChar + 修饰/扩展键）+ GetConsoleCP/osfhandle；/doctor 加输入通道诊断行。**用户需在 git bash 跑一次回传输出**。
- ime_shim：fold_input_records 加 KEY_EVENT NUL-uChar 重建（MapVirtualKeyW(VK,0)，仅无修饰键+非控制键+结果非 ASCII 才并入字符流）+ CP 告警（不自动 SetConsoleCP，ConPTY 65001 会破坏 IME）。**11 的最终形态以 10 的探测结果定稿**；若 NUL-uChar 重建未命中实际记录形态，按探测调整。

### 12 文档与回归（12）
- AGENTS.md 新增「TUI 体验五」段：/undo（双 Esc 语义 + 空闲单 Esc 不退）、/use //skills、permissions.heuristics + 规则集示例 `{"execute":{"*":"ask","git *":"allow"}}`、jarvis_skills、input_probe、modal 布局规约。
- 测试批回归：A（backend/路由 ~95）/ B（TUI/UX ~259）/ C1（config 48 绿 + 3 既有失败勿修）/ C2+C3（RAG 前 2 例）。

## 验收
- [ ] 12 张工单全 done
- [ ] 测试批全绿（C1 三处既有失败除外）
- [ ] 用户在 git bash 跑 `python -m src.input_probe` 回传输出；中文标点实测进框
- [ ] 不合并 main（用户明确「先不并回 main」）