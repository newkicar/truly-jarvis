# 04 — Shift+Enter 多行输入（continuation buffer）

**What to build:** 输入框当前单行、无任何换行能力（Textual `Input`）。定稿 continuation buffer 方案（对标 codex/opencode 终端 composer）：

- `src/tui.py`：
  - `PasteInput.BINDINGS` 增 `Binding("shift+enter", "newline", "换行", show=False)` 与 `Binding("ctrl+j", "newline", "换行(退路)", show=False)`；新增 `action_newline()`。
  - `JarvisApp`：`self._continuation: list[str] = []`；composer 区（`#input` 上方）加 `#continuation` Static，dim 堆叠显示已确认续行，空则隐藏。
  - `action_newline`：当前值非空 → 压栈 + 清框聚焦 + 刷新显示；当前值空且有栈 → 弹末条回框；`/` 开头（首行）→ 不换行，notify「命令不支持换行」一次。
  - `on_input_submitted`：提交值 = `"\n".join([*_continuation, value])`（首行空则只拼续行）；`/` 开头或提交后清空续行缓冲。
  - 空输入框 Backspace → 弹回末条续行（Input 的 backspace 在空值时走 `action_newline` 同款弹栈逻辑）。
  - 粘贴多行取首行旧行为（`_apply_paste`）**本票不动**。
- pilot 探针 `scratch/probe_shift_enter.py`：`app.run_test()` + `pilot.press("shift+enter")` 验证 **Textual 层**修饰键可达 + 换行动作触发。真实 ConPTY/PowerShell 是否透传 shift 修饰符**无法本机自动验证** → Ctrl+J 常绑作退路，最终汇报注明待用户实测。
- 测试（并入 `tests/test_tui.py`，run_test + pilot，参照既有 `_type_and_enter`）：两行提交拼接 / ctrl+j 同义 / `/undo`+shift+enter 不换行（直接提交）/ 空框 Backspace 弹回末条续行。
- AGENTS.md 加「TUI 体验六（tui-ux6）」段（Shift+Enter 多行 + drain 语义 + /undo 无参 + checkpoint_ns 一行带过）。

**Type:** feature
**Status:** done (2026-10-18, commit 903ed3c)
**Blocked by:** 无

## 验收
- [x] shift+enter / ctrl+j 压续行、提交 `\n` 拼接（log 与发给模型的消息含换行）
- [x] `/` 命令首行禁换行（notify 提示 + 直接提交）
- [x] 空框 Backspace 弹回末条续行；续行 dim 堆叠显示
- [x] pilot 探针通过（Textual 层）；4 场景测试绿
- [x] 全量 pytest 无新增失败

## Comments
用户原话：「输入框不能通过 shift+enter 换行——现在就没有换行能力」。真实终端 Shift+Enter 透传性需用户实测回传；Ctrl+J 为常绑退路。
