# tui-ux14 spec —— 4 项 TUI 需求（2026-10-22）

## 用户需求原文（4 条，勿缩小范围）
1. 「把 ctrl+. 输入标点符号这个功能去掉」
2. 「当用户输入 /yolo on 激活 yolo 模式以后，加入强提示，在输入框最右侧显示 YOLO 标志，做的醒目一点。同时注意用户可能开启了 yolo 模式以后，切换了对话（或新建了其他对话），当用户切回到这个已经开启 yolo 模式的对话时，右侧 YOLO 标志要正确显示」
3. 「任务执行的持久性：如果我切到了新的对话、或新建了对话，焦点已经转移到了其他的对话，那么是否会影响 AI 的工作呢？我的要求是：如果开启了 YOLO 模式，则不影响，任务还要继续执行下去，直到用户切回对话，并按下 esc 键或 ctrl+c 键主动中断。如果用户未开启 YOLO 模式，那么当用户切换到其他对话的时候，任务中断。」
4. 「执行任务时，如果用户发送了新的对话内容，要加载到缓存区，并支持用户通过『左键』把已经存放到缓存区但未提交给模型处理的对话撤回（移出缓存区，回到输入框中）。已加载到缓存区的对话内容，在代理当前调用的工作执行完成后『插队』发送给 AI，不必等到代理执行完整个任务才能发送。」

## 设计定案

### 01 删 Ctrl+. 标点面板
全仓删除 PunctPanelModal / action_punct_panel / _insert_punctuation / Binding("ctrl+.") / PUNCT_ITEMS；
tui_punct.py 保留 ime_hint_line / ime_hint_markup（改写文案，去 Ctrl+. 句）/ is_conhost_like（/doctor 终端判定仍在用）。
相关文案同步：input_probe.py 判定行、main.py 启动警告、tui.py drift notify。
ime_hint 配置行（tui.py on_mount 与 _ime_hint_mode）保留。

### 02 YOLO 徽章（composer 最右 + 切回联动）
- #editor_frame（Horizontal：#prompt + #input）内 #input 之后插 Static("", id="yolo_badge")。
- CSS 仿 #todo_panel：#yolo_badge{display:none} + #yolo_badge.-active{display:block}（$error 系醒目色，内容 [b]⚠ YOLO[/b]）。
- _refresh_yolo_badge()（NoMatches 守卫）判 yolo_active(self.permission_state, self.thread_id)；
  挂 _update_sub_title() 末尾 —— on_mount / _apply_command_result / _adopt_thread / _switch_session 全调用链覆盖，切回 YOLO 会话自动正确显示。

### 03 YOLO 后台任务持久
- self._worker → self._workers: dict[str, Worker]（thread_id 为键）；6 处 spawn 点方法开头捕获 tid = self.thread_id 作键。
- cancel 路径（_cancel_stream_worker / action_cancel）按 self._workers.get(self.thread_id) 取。
- _leave_current_thread(old)：yolo_active(state, old) 为真 → 不 cancel、不 finalize，old 入 self._bg_turns: set[str]（HITL choreography 保留）；非 YOLO 维持现状（cancel + finalize + 作废旧队列 + notify）。
- _release_turn_gate(tid)：tid in _bg_turns → 保留该 thread 队列（不作废不 notify）+ 移出 _bg_turns；其余维持现有作废语义。
- _switch_session adopt 后：该 thread 门已释放且 registry 有消息 → 重投队首。
- tui_turn.py：__init__ 捕获 self.thread_id；相关 live self.app.thread_id 引用改读 self.thread_id（修切换后误绑）；_hide_spinner → _hide_spinner_if_idle()（有未 finished worker 不隐藏）。
- 中断语义：YOLO 线程用户切回后按 Esc/ctrl+c = 现有 action_cancel 路径；「任务继续执行到用户主动中断」= 后台 worker 不受 leave 影响。

### 04 插队消息队列（消息缓存区）
- 新 src/jump_in_queue.py：
  - JumpInRegistry：dict[str, deque[str]] + threading.Lock；push/pop_first/pop_item(tid, idx)/drain(tid)/items(tid)/clear(tid)/has(tid)/count(tid)/on_change。
  - thread-local：set_current_thread_id(tid) / get_current_thread_id()。
  - MessageQueueJumpInMiddleware(AgentMiddleware)（before_model/abefore_model）：
    tid = get_current_thread_id() or (self.permission_state or {}).get("thread_id")；None → 返回 None；
    drain(tid) 非空 → {"messages": [HumanMessage(m) for m in msgs]}（append 语义）。
- 注入时机 = 当前工具步完成后、下一模型步之前（before_model hook）；drain 即删 → 与门释放 FIFO 重投并存无双发。
- streaming.run_agent_turn：入口 sync_permission_context 后 set_current_thread_id(thread_id)；finally 清除。
- agent.build_agent(..., jump_in_registry=None)：middleware 列表 inbox_snapshot 之后 append MessageQueueJumpInMiddleware，仅主代理。
- main.py：构造 JumpInRegistry，传 build_agent + JarvisApp（JarvisApp 缺省自建）。
- tui.py：
  - #message_queue 面板（compose #todo_panel 之后；CSS 仿 todo_panel；每行 Static 截断）。
  - 旧 self._queued_messages 并入 registry 单一事实源；保留 app._queued_messages 只读 property（[(tid, text)]，兼容 test_tui_turn_gate）。
  - 排队点 → registry.push(self.thread_id, text) + 刷面板 + notify「任务执行中，已放入消息缓存 N 条，当前步骤完成后自动发送；左键点击可撤回编辑」。
  - 面板行 on_click → pop_item + 回填 #input（_apply_undo_result 范式：text + cursor_location + focus）+ 刷新面板。
  - 刷新点：push / 门释放 / 切 thread / registry.on_change（call_from_thread）；UI 写路径 NoMatches 守卫。

### 05 回归 + 文档 + 交付
- 分片回归对比 baseline（.ci_tmp/baseline_ux14.txt；预存 test_config×3 与 tmp_path 环境问题忽略）。
- AGENTS.md 追加「TUI 体验十四」条目。
- commit：feat(tui-ux14)（src+tests）→ docs(tui-ux14)（AGENTS.md）→ push（失败>3 次停下等用户）→ CI 轮询至绿 → 全中文汇报。

## 正交不动（测试证明零改）
VaultWriteGuard / StepBudgetMiddleware / DoomLoopMiddleware / PlanModeMiddleware / SanitizeHistoryMiddleware /
HITL 审批 modal 四按钮 / /use 模糊补全 / PasteTextArea OS 粘贴。

## 已知边界（记录不解决）
- 共享 permission_state["thread_id"] 可被并发 sched-turn 覆写（与既有 permission hooks 同源），竞态方向 fail-safe。
- app 退出（ctrl+q）不逐一 cancel 后台 worker（进程退出自然终止）。
- /fork、/delete-session 不触发 YOLO bg 语义（保持现状）。
- 插队兜底 = 门释放 FIFO 重投 + before_model drain 双保险。