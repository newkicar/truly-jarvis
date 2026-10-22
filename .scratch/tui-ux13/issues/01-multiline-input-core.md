# 01 — 多行输入框内核（Bug 1：输入框内换行）

**What to build:**
- `PasteTextArea(TextArea)` 新基类（src/tui.py，L388 ModalTextArea 的 OS 粘贴做法上提）：`action_paste` 覆盖——`run_worker`(exclusive) 读 OS 剪贴板 `read_os_clipboard`、空则回落 `app.clipboard`；`_replace_via_keyboard + move_cursor` 尊重选区（空选区=光标处插入）；widget 级 `ctrl+shift+v` / 屏级 `ctrl+shift+enter` 退路。`ModalTextArea` 改继承它（收拢重复，EditParams/Prefix modal 行为零变化）。
- `JarvisTextArea(PasteTextArea)` 主输入控件（`id` 仍 `#input`，CSS/查询 id 零改动）：覆盖私有 `_on_key`（Textual 8.2.8 `widgets/_text_area.py` L1818-1828 键映射实证）——无修饰 `enter` → `prevent_default` + 发自定义消息 `JarvisSubmitted`（Textual Message，**勿复用** `Input.Submitted`，类型不匹配）；`shift+enter` + `ctrl+j`（ConPTY shift 透传不保证的退路键）→ 原生插 `
`；Ctrl+Z 行内撤销保留。
- 提交语义（纯函数 `build_submission(raw: str) -> tuple[str|None, str|None]` 放 src/commands.py，返回 (提交文本|None, notify 文案|None)，可单测）：多行消息 = 完整文本（strip 尾随空行/尾空白）进模型；`/` 开头且含 `
` → notify「/ 命令请放一行」**不提交**；非 slash 多行按普通消息进 tui-ux7 turn gate（语义零变化）。
- 补全按**光标行**投影（src/tui_completion.py 新增纯函数，`use_query`/`resolve_overlay_state`/`apply_suggestion` 内核**不动**）：`line_projection(text, cursor) -> (line_value, line_cursor)`（text 按 `
` 分段、cursor 行/列投影）+ `apply_suggestion_on_line(text, cursor, at_index, line_at_index, insert) -> (new_text, new_cursor)`（只改光标行再重建全文）。调用侧迁移：`_refresh_suggestions`(L1602)、`action_accept_suggestion`(L1627)、`on_input_changed`(L1643，事件源 `Input.Changed` → TextArea 侧事件名实现时以 Textual 8.2.8 实证，`DocumentUpdated` 候选)。
- 粘贴全量多行：`_apply_paste` L135 现状只取首行 `text.splitlines()[0]` → 全量入框；图片路径探测（首行像路径→`[Image #N]`）与图片剪贴板路径零变化。
- **删 continuation 全套**（tui-ux6 旧语义全作废）：`_continuation`(L987)、`_cmd_newline_hinted`(L988)、`#continuation` CSS(L893-904)、compose `Static("", id="continuation")`(L1107)、`action_continuation_newline`/`_refresh_continuation`/`on_input_submitted`(L1670-1715)、`on_event` 空框 Backspace 弹续行(L153-170 相关段)、PasteInput BINDING `shift+enter`/`ctrl+j`(L107-108)——全仓 grep `_continuation` 零命中；提交处理改 Screen 层 `on_jarvis_submitted`（提交后清空用 TextArea API（`document`/`text`）而非 `value=`）。
- API 迁移调用面（全清单）：`query_one("#input", Input)` → TextArea 类型——L1110 compose / L1268 / L1484 / L1542 / L1808 / L1833 focus；L1296 提交后清空；L1434-1438 `/undo` 回显（`value=`/`cursor_position=` → TextArea 文档/光标 API，属性名实现时实证）；`_insert_punctuation`(L1820-1827) `selection`/`replace`/`insert_text_at_cursor` → `selection + _replace_via_keyboard + move_cursor`（ModalTextArea L420 同款），`PunctPanelModal` 的 `self._app._insert_punctuation(char)` 调用点(L775) 零改动。
- CSS：`#input` `height: 1`(L941-952) → 1 行起步、随内容长高、上限 5 行后 `overflow-y: auto` 内部滚动；gutter 行号隐藏（`.text-area--gutter` 选择器或 TextArea 构造参数，以探针为准）；光标常驻可见。TextArea 无 `select_on_focus`（tui-ux10 实证：点击聚焦=光标就位无灰选）——顺带消解主输入框灰选态，无需额外处理。
- 测试：test_tui pilot 键序列（pilot 驱动：无修饰 enter 提交 / shift+enter 插 `
` / ctrl+j 退路 / 换行后旧行改字 / slash 多行不提交 notify / 粘贴多行全量 / 提交后清框 / undo 回显多行文本）；test_tui_completion（`line_projection`/`apply_suggestion_on_line` 纯函数表 + `/use` 光标行触发）；test_commands（`build_submission` 表：多行 strip / slash 多行拒 / 普通单行零变化）。

**Type:** bugfix
**Status:** done
**Blocked by:** 无

## 验收
- [x] `PasteTextArea`/`JarvisTextArea` 落地，`ModalTextArea` 继承收敛（EditParams/Prefix modal 行为零回归，test_tui_modals 64 条不新增失败）
- [x] 键位契约：Enter 提交整框；shift+enter + ctrl+j 框内插 `
`；Ctrl+Z 撤销保留
- [x] 换行后旧行可编辑、光标可自由移动（continuation 缓存区语义彻底移除，grep `_continuation` 清零）
- [x] 提交语义：多行 = 完整文本（strip 尾随空行）；`/` 多行 notify 不提交；turn gate 语义不变
- [x] 补全/`/use`/`@` 只看光标行；接受建议只改光标行；纯函数全单测
- [x] 粘贴多行全量入框；图片路径/图片剪贴板路径零变化
- [x] `#input` 1→5 行自适应 + 内部滚动 + gutter 隐藏 + 光标常驻
- [x] `_insert_punctuation` / undo 回显 / focus 调用面（L1110/1268/1296/1434/1484/1542/1808/1833）API 迁移完成
- [x] test_tui / test_tui_completion / test_commands 新增全绿；全量 pytest 无新增失败（对照基线 609 passed + 预存 3× test_config）

**Done:** 2026-10-22（实现 + 测试全绿：test_tui 49 / test_tui_modals / test_tui_completion / test_commands 锚点族通过；grep `_continuation` 清零（src/tests；AGENTS.md tui-ux6 历史条目保留，由 tui-ux13 条目显式覆盖）；全量回归 0 新失败（仅预存 3× test_config 已知坏））
