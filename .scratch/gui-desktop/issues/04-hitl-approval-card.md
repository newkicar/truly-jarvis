# 04 — HITL 审批卡片（内联卡片 + 表单 + diff 三件套）

**What to build:** codex 式聊天流内联审批卡（用户裁定，非模态框）：工具名 + 参数预览（execute 命令预览 / write 全量 diff / edit unified diff / delete 极简卡，复用 permission_preview）+ 四按钮（放行[主按钮默认焦点] / 永久放行[前缀可编辑] / 拒绝 / 编辑参数）+「放弃本轮」显式标注（放弃≠取消任务）；编辑参数 = 卡片内展开表单（原值只读展示行 + 编辑框，execute 单行、write/edit 多行、留空保留原值——「看得见改」平移）；多中断 FIFO 一次显一卡；任一结果后焦点回输入框；阻塞语义 = worker `threading.Event` 等卡片按钮，结果经 `decision_from_choice`/`collect_interrupt_decisions` 出同构 dict（resume 契约 `{"decisions":[...]}` 零内核改）。形状来自原型 CardSession/ask_action（过稿验证过）。

**Blocked by:** 01（GUI 运行时骨架）

**Status:** ready-for-agent

- [ ] 四按钮 + 编辑表单 offscreen 全流程（approve/reject/always/edit/abandon 各出同构 dict，对照 TUI/CLI 契约断言）
- [ ] write_file 卡出 diff 预览；execute 卡出命令预览（长命令截断规则复用）
- [ ] 永久放行写回 jarvis.json 前缀规则（`git *` 类），下一轮同前缀不再弹卡
- [ ] 卡片在聊天流就地出现（不遮挡历史），决策后卡片锁定态 + 结果行
- [ ] 焦点：卡片打开默认焦点=放行；任意结果后焦点回输入框
