# 04 — 收官：全量回归 + AGENTS.md + 工单勾验 + push

**What to build:**
- 全量 `pytest`（`--ignore=tests/test_rag.py --ignore=scratch`）对照**预存失败基线**（本地 609 passed + 3× test_config 已知坏；CI 基线 593 passed, 4 skipped；本批新增必须 0 失败 0 新错）；锚点族全绿（test_tui / test_tui_modals / test_tui_completion / test_commands / test_ime_shim / test_input_probe）。
- AGENTS.md 加「**TUI 体验十三**（`tui-ux13`，<日期>，输入框多行内换行 + 中文输入三层自诊断）」条目，密文风格对齐 tui-ux10/tui-ux12 段：
  - Bug1 语义变化清单：shift+enter 不再进缓存区 → 框内 `
`；continuation 全套删除面（栈/面板/Backspace 弹回/`/` 首行禁换行 notify）；粘贴全量多行（原只取首行）；`/` 多行门禁文案「/ 命令请放一行」；`#input` 1→5 行自适应 + 内部滚动 + gutter 隐藏 + 顺带消解灰选态（TextArea 无 select_on_focus）；补全/`/use`/`@` 光标行投影（纯函数 `line_projection`/`apply_suggestion_on_line`，内核不动）；`JarvisSubmitted` 自定义消息契约（勿复用 Input.Submitted）；TextArea 事件源（DocumentUpdated 实证）；`build_submission` 纯函数；`PasteTextArea` 基类上提（ModalTextArea 继承收敛）。
  - Bug2 三层闭环：L1 `ime_shim.ensure()`/`shim_status()` 三态 + TUI 低频复检一次性 notify；L2 `input_probe.summarize_session` 三态判定 + /doctor 输入通道 2 行（shim 状态 + 终端类型 conhost/WT/pipe）；L3 Ctrl+. 面板 + ime_hint 兜底；**红线：绝不自动 SetConsoleCP**（仅告警）。
  - 附 commit 号。
- 四张工单文件 `Status:` 改 done + 验收项逐条勾选 + Done 行（主 commit）；spec.md Status 改 done + 结尾「收官（待填）」字段填实。
- commit（中文 conventional：`feat(tui-ux13): 输入框多行内换行 + 中文输入三层自诊断闭环`）+ push main（失败重试 ≤3 次间隔 20s；**频繁失败 → 停下等用户消息**，用户 GitHub 网络不稳）。
- CI 轮询至新 head 绿：GHO token（用户本地提供，不入仓）、repo `newkicar/truly-jarvis`、列 runs 取 `$r.workflow_runs`（**单数**）+ `@(...)` 防解包、job 日志 `.../jobs/<job_id>/logs`、30s 间隔；若红且仅预存已知问题 → 向用户报备不阻塞。

**Type:** chore
**Status:** done
**Blocked by:** 01, 02, 03

## 验收
- [x] 全量 pytest 对照基线无新增失败（634 passed + 仅预存 3× test_config；0 新增）
- [x] AGENTS.md【TUI 体验十三】条目落盘（Bug1 语义变化 + Bug2 三层闭环 + 红线记录；commit 占位 `80315be` docs commit 回填）
- [x] 四张工单 done + 勾选；spec.md Status done + 收官字段填实
- [x] commit + push main；CI 状态检查（绿，或仅预存已知红且已向用户报备）
**Done:** 2026-10-22（全量回归 634 passed + 仅预存 3× test_config；AGENTS.md 条目落盘 + spec 收官填实 + 工单 01–03 勾验完成；主 commit `80315be`（docs commit 回填）；2026-10-22 CI 绿（run 39703698698 @ `209f5e8`）验收项补勾完毕）
