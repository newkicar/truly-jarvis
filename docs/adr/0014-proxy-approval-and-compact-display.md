# ADR-0014: 替我审批 /proxy + 压缩非破坏性展示基线 + 压缩继续任务

**状态:** 已接受（2026-11-24）

## 背景

GUI 实使用 5 问题批次（①②④⑤ 本 ADR 承载；③ undo 闪退的 `_tid_locks` 线程锁已在 HEAD，
`gui_main.py` 的 `faulthandler.enable()` 留栈随本批提交）：

1. **压缩后历史空白**：`/compact`（或自动压缩）把检查点历史截断为一条延续性摘要后，
   切到别的对话再切回来，聊天面板从检查点重建 → 只见摘要、旧记录全空。对标 codex：
   token 可以压缩，但历史对话记录仍在屏幕上显示。
2. **缺「替我审批」**：HITL 默认 `ask` 每次审批，用户希望放行安全审批、拦住危险审批
   （对标 codex auto-approval 的安全半区），并像 `/yolo on` 一样一个开关启动；
   与 YOLO（全放行含危险）不同，这是「确定性规则表内放行、规则表外留人类」的半自动区。
3. **压缩中断任务**：压缩摘要写回后模型停下等用户指令，长任务被打断。
4. **自动压缩无提示**：会话被压缩后侧边栏无标记，用户不知情。
5. **原生崩溃无栈**：CPython 退出期 PySide6 析构 SIGSEGV（CI 已知容错 rc=139）在本机
   无栈可查；`gui_main.py` 加 `faulthandler.enable()` 让 C 层崩溃打 stderr。

## 决策

1. **压缩展示基线 = 文件快照 + 基线/live 合并重建**（问题 1、4）：
   - 新模块 `src/gui/compact_baseline.py`：`<project_root>/.jarvis/compact_baselines/<tid>.json`
     存压缩前 `replay.Record` 列表（JSON 整表覆盖；tid 消毒 `[^0-9A-Za-z_-]` → `_`）。
     `load_baseline` 对缺失/损坏/非 list 一律 `[]`——纯展示增强，不炸主流程。
   - `replay.compact_probe(agent, tid)` = 一次 `get_state` 返回 `(展示记录, 截断前消息总数)`，
     供自动压缩的回合前快照使用；手动 `/compact` 前 GUI 用 `thread_record` 快照、成功后
     `save_baseline(旧基线 + pre)` 追加 + `session_registry.set_compacted(tid, True)`
     （registry 新增 `compacted` 标志，复用 `_set_flag`）。
   - `MainWindow._merged_display_records(tid)` = 基线 + 当前 live，`_rebuild_pane` /
     冷建 pane 两处改走合并（旧路径裸 `thread_record` 删除）。
   - 侧边栏行标签 `_session_row_label` 在 arch 之后、会话名之前插 `🗜 `（is_compacted 时）。
   - 并发边界：`_execute_slash` 中 `/compact` 遇 `gate.is_running(tid)` 直接拒绝
     （「正在执行中，请等回合结束后再 /compact」）——压缩与活动回合并发时覆盖压缩边界不确定。
   - **/undo 到空白清基线**：`_on_undo` 成功且 live 无 user/ai 记录时
     `clear_baseline` + `set_compacted(False)`（undo 是撤销压缩，防屏幕残影）。
2. **替我审批 = 线程级确定性规则表 + 共享 state 零重建**（问题 2）：
   - `permissions.py` 新增 `PROXY_THREADS_KEY="proxy_threads"` 与纯函数三件套
     `proxy_on / proxy_off / proxy_active`（yolo_threads 同惯例：纯内存、不落盘、重启全关、
     幂等；`build_permission_interrupts` / `_from_state` setdefault 空集合）。
   - `proxy_auto_allow(tool, args, state)` 规则表（确定性、可单测、无模型参与）：
     | 工具 | 自动放行条件 |
     |---|---|
     | execute | 仅命中 `HEURISTIC_SAFE_COMMANDS` 只读表（与 heuristics 特性同源，经 `heuristic_safe(command(args))`） |
     | write_file / edit_file | 目标路径（file_path/path/pattern/command 首个 str 参）resolve 后 `is_relative_to(project_root)`；相对路径以 `state["project_root"]`（回落 cwd）为基准；异常 → 不放行 |
     | delete 及其他 | **绝不**自动放行（留给人类 HITL） |
   - `_action_for_args` 尾部（heuristics 块之后）：`action=="ask"` 且该 thread 在
     proxy_threads 且 `proxy_auto_allow` → `"allow"`。**deny 已在规则解析阶段定案、
     绝不被 proxy 覆盖**；函数体顶部的 yolo 短路仍最先执行（yolo > proxy > heuristics
     > 规则表）。
   - 命令面：`commands.proxy_command_text`（None state 不崩；on/off 幂等四态文案 +
     裸查询 + 非法参数用法行）、`dispatch_command` 分支、`_HELP_COMMANDS` 行、
     `slash_completion` 补全项。三前端共用同一 commands 层（GUI 本批只接
     `[PROXY]` 徽标 + `sync_modes`：`_refresh_mode_badges` 在 `[YOLO]` 后追加
     `[PROXY]`（ok 色），`_execute_slash` 的 badge 同步触发条件扩为
     `first in ("/yolo","/proxy")`）。
3. **undo 闪退留栈**（问题 3）：`gui_main.py` 顶部 `faulthandler.enable()`——
   原生崩溃（SIGSEGV/SIGABRT）打 C 栈到 stderr；根因侧的 `_tid_locks` 线程锁
   已在 HEAD（并行会话提交），本条只补留栈可查性。
4. **压缩后继续任务**（问题 5）：`commands.compact` 的 role prompt 追加
   「必须额外写明『未完成任务』一节：当前进行到哪一步、下一步具体做什么（可执行指令
   形态）；摘要之后代理将立即继续执行未完成任务，不得停下等待新指令」。
   提示词层约束（非代码边界）——与韧性层「提示词是建议、代码才是边界」同纪律，
   本条接受提示词层实现：续跑由下一回合模型自驱，harness 不代跑。
5. **自动压缩标签提示**：自动压缩路径经 `replay.compact_probe` 快照 + registry
   `compacted` 标志 → 侧边栏 🗜（与手动 `/compact` 同标记；自动路径的快照接线在
   自动压缩触发侧，本批先落基线设施与标记语义）。

## 基准

- **codex**：压缩 = token 层，历史显示记录保留在屏幕上（本 ADR ①④ 对标其显示语义）；
  auto-approval = 按安全类别半自动放行（本 ADR ② 对标其「放行安全、拦住危险」分界，
  规则表为本项目确定性替代）。
- **deepagents 上游**：HITL 只给 `interrupt_on`（approve/reject/edit 决策 + allowed
  decisions），无「替我审批」类半自动层——规则表 + `interrupt_on` 复用 = 本项目边界，
  零重造轮子（proxy 命中安全区时等价于自动 approve，走 langchain 原生 resume 路径）。
- GitHub 调研结论（前序会话已记录）：deepagents/langgraph 上游无等价物，opencode
  的 external_directory 权限模型亦无「线程级半自动」层；规则表形态参考 opencode
  permission 规则集「最后匹配胜出」的确定性纪律（本项目 fnmatch 同款）。

## 残余风险

- 基线 JSON 由 worker 线程写（`_execute_slash._run` 内）：单写者 + 整表覆盖原子度
  依赖 `write_text` 单系统调用语义；读侧对损坏一律 `[]`，最坏残影 = 多显示旧记录。
- `proxy_auto_allow` 的 `resolve()` 会跟随符号链接：符号链接逃逸出项目根按
  `is_relative_to` 判定（接受，记录在案）；Windows 下路径分隔由 `Path` 归一。
- 共享 `state["thread_id"]` 可被并发 sched-turn 覆写（与既有 yolo/permission hooks
  用法同源，竞态方向 fail-safe = 不放行），列为未来加固项。
- ④ 的「继续任务」是提示词层约束：模型仍可能停下；代码层保证只在下一回合，
  不自动代跑（与韧性层纪律一致）。
- CPython 退出期 PySide6 析构 AV 非本批根治（faulthandler 仅留栈；CI 已有
  rc=139 容错同款）。