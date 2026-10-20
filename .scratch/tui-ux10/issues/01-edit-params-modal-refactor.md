# 01 — EditParamsModal 重构：看得见改 + 多行（Label 展示 + ModalTextArea）

**What to build:** EditParamsModal（src/tui.py L363）逐 key 1 行 `Input(str(v), id=f"param_{k}")`
预填——select_on_focus=True 全文选中灰态 + 首键整值替换（「点就变灰、打字不显示」根因），
且单行框改不了多行参数。重构为每 key 两行：

- `Label(f"{k} = {_param_display(v)}", classes="param_show", markup=False)`：只读展示原值，
  `_param_display(v, limit=500)` 超长截断 + `…（截断，共 N 字符）` 尾注（**看得见改**）。
- `ModalTextArea(str(v), placeholder=k, id=f"param_{idx}", classes="param_edit")`：TextArea
  子类（本票先建类，工单 02 加粘贴通道；**省略 theme 参数**——8.2.8 `_BUILTIN_THEMES`
  仅 5 个内置，`theme="text"` 抛 `ThemeDoesNotExist`，默认 "css"）。CSS `.param_edit { height: 5; }`。
- id 净化：`#param_{idx}` + `self._key_idx = {k: i for i, k in enumerate(self.args)}`
  （原 `#param_{k}` 把 key 当 CSS 选择器，key 含特殊字符即坏）。
- 构造器 `EditParamsModal(args, *, tool_name: str | None = None, path: str | None = None)`；
  标题 `编辑参数 · {tool_name}`（无 tool_name 回落旧文案「编辑参数（留空使用原值）」），
  有 path 加 `Label(f"目标: {path}", id="edit_path", markup=False)`。
- `AUTO_FOCUS = "#param_0" if self.args else "#btn_ok"`（沿用 tui-ux8 实例级模式）。
- `modal_edit_result` 新语义：`text = str(values.get(k, ""))` → `text if text.strip() else args[k]`
  （全空白回落原值；非空白不 strip，保留多行尾换行）。
- `PermissionModal.action_edit_params`（L264-269）改传
  `EditParamsModal(self.inv.args, tool_name=self.inv.name, path=self.inv.path)`。
- `on_button_pressed` 取值改 `self.query_one(f"#param_{self._key_idx[k]}", ModalTextArea).text`。
- 多行通道：TextArea `_on_key` 原生 `enter → "\n"`（_text_area.py L1827-1828 实证），
  编辑框直接可换行；`streaming.py` edit 结果 `handle_interrupt(edited=...)` JSON 回注多行无碍，
  CLI 编辑路径不动。
- 测试（tests/test_tui.py + tests/test_tui_modals.py）：
  - 既有 `test_edit_params_modal_typing_writes_to_input` L1071 `#param_command` Input →
    `#param_0` ModalTextArea `.text`（import 同步）；
  - 新增：Label 展示行含 "whoami"（`lbl.content` 断言，Label markup=False → Static.content
    存原始 str；8.2.8 无 `Widget.plain` 属性）；`modal_edit_result` 纯函数组
    （多行保留 `{"command": "ls\npwd"}` / 全空白 `{"command": "  \n "}` 回落 / 短串原样）；
    空编辑框确认回落原值（既有 L55-57 断言在新语义下须仍绿）；Enter 插 \n round-trip。

**Type:** feature
**Status:** done (2026-10-20, commit aee155e)
**Blocked by:** 无

## 验收
- [x] 既有红灯 `test_edit_params_modal_typing_writes_to_input` 改查 `#param_0` 后绿
- [x] 新增断言全绿（Label 展示 / modal_edit_result 纯函数组 / Enter 多行 / 短屏按钮可见）
- [x] 锚点回归绿（test_edit_params_modal_typing_writes_to_input + test_permission_modal_enter_approves_directly）
- [x] 全量 pytest 无新增失败（对照预存基线）

## Comments
改动清单/结果：EditParamsModal 每 key 两行（Label 只读展示原值（_param_display 截断 500）+ ModalTextArea 多行编辑框，id 索引化 #param_{idx} + self._key_idx）；modal_edit_result 纯函数（全空白回落原值、非空白不 strip 保多行）；API 实证：8.2.8 theme 仅 5 内置（theme="text" 抛 ThemeDoesNotExist 用默认 css）、Widget 无 call_from_thread、Label 无 plain 用 Static.content；新增测试全绿 + 锚点回归绿。见 commit aee155e。
