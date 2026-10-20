# TUI 体验十（tui-ux10）：编辑参数对话框「看得见改 + 多行输入」

**Type:** bugfix + feature（用户报告：审批弹窗「编辑参数」对话框里「像是输入框的东西」无光标、点击不亮、打字/ctrl+v 都不显示，看起来只读；后续批次要求看得见原文 + 可多行修改）
**Status:** ready-for-agent
**Blocked by:** 无（EditParamsModal 三期 HITL 已落地；本批是 Modal 内部件重构 + 输入通道）

## Problem Statement

`EditParamsModal`（src/tui.py L363，ModalScreen）逐 key 用 1 行 `Input(str(v), id=f"param_{k}")` 预填参数。
用户症状（tui-ux9 收官后连续两轮截图反馈）：打开编辑参数弹窗后——

1. 点「输入框」立刻整框变灰、无光标；打字不显示；ctrl+v 粘贴不显示；看起来只读。
2. 输入框只有 1 行高，execute 类参数（多行命令/脚本）根本改不了。

根因（diagnosing-bugs 六阶段，探针实证，Textual 8.2.8）：

- **灰色 + 首键替换**：`Input.select_on_focus=True` 是默认值（widgets/_input.py L368；点击聚焦时
  L736-740 触发 select-all）→ 点击即全文选中（灰底 = `$input-selection-background` #403f3c），
  随后第一下按键**整值替换**。用户以为「没打进去」，其实原文全没了——症状 1 的统一根因。
- **无光标观感**：全文选中态下光标与选中块重合，终端渲染看不出可输入的样子。
- **改不了多行**：Input 单行 + 旧 `modal_edit_result` 对值做 `.strip()`——多行值先天不可表达。
- 同族病灶：`PrefixModal` 的 `#prefix_input`（Input，select_on_focus 默认 True）与
  `#perm_box/#edit_box/#prefix_box` 三个 VerticalScroll 容器（`can_focus=True`，DOM 顺序上
  先于按钮/输入框，是 tui-ux8 焦点族病灶的同款结构）。

## Solution

三张实施工单（01 结构重构 / 02 输入通道 / 03 PrefixModal 对齐）+ 一张收官工单（04 回归+文档+push）：

1. **01 看得见改 + 多行**：EditParamsModal 每 key 两行——只读展示 `Label(f"{k} = <原文>")`
   （超长 500 字截断 + 尾注，**看得见**原值）+ 下方 `ModalTextArea`（TextArea 子类）多行编辑框
   预填完整原值（**改得了**，Enter 原生插 \n = 多行通道）。`modal_edit_result` 新语义：
   全空白 → 回落原值；非空白 → 原样使用（**不 strip**，保留多行尾换行）。模态标题
   `编辑参数 · {tool_name}`，有 path 加 `目标: {path}` 行。灰态在结构上消解：TextArea
   无 select_on_focus、聚焦不选中（仅 F7 显式全选）——点击框 = 光标就位，无灰选区。
2. **02 输入通道**：`ModalTextArea.action_paste` 覆盖（run_worker 读 OS 剪贴板
   `read_os_clipboard`，UI 线程 `_replace_via_keyboard` + move_cursor，空则回落原生
   app.clipboard 语义；widget 绑定 ctrl+shift+v，原生 ctrl+v 同走覆盖路径）+
   EditParamsModal 屏级 `ctrl+shift+enter` → `action_newline`（聚焦编辑框插 \n）+
   `#edit_box/#perm_box/#prefix_box` CSS 全加 `can-focus: no`（容器不再夺焦点）。
3. **03 PrefixModal 对齐**：`AUTO_FOCUS="#prefix_input"` + `Input(select_on_focus=False)`
   + `#prefix_box can-focus: no`——前缀框打开即聚焦、无灰选区。
4. **04**：全量 pytest 对照基线 → AGENTS.md「TUI 体验十」段 → 四张工单勾验收+done → docs commit → push main。

## User Stories

1. 作为用户，审批点「编辑参数」后**看见原命令全文**（Label 展示行），直接在下方多行编辑框里
   改；改完按「确认」，改动的参数（含多行）原样生效。
2. 作为用户，编辑框里 Ctrl+V / Ctrl+Shift+V 可粘贴系统剪贴板内容（含多行），
   Ctrl+Shift+Enter 可换行。
3. 作为用户，点进任何编辑框 = 光标就位（不整框变灰、不静默清空原文）；想清空重写要显式选中。
4. 作为用户，PrefixModal（execute 永久放行）打开即聚焦前缀框，可直接改前缀。
5. 作为用户，编辑框全部留空/全空白时确认 = 放弃修改用原值（旧语义保留），不会把参数清空成空串。

## Implementation Decisions

- **TextArea 而非 Input**：Input 的 select_on_focus 灰态无法配置关闭（8.2.8 无该参数暴露点），
  结构消解 > 参数规避。TextArea 自带 5 行高编辑区、原生 enter 插 \n（_on_key L1827-1828
  `"enter": "\n"`）、原生 ctrl+v→action_paste（L387）、`selection` 2-tuple（L1848）、
  `.text` 属性 get/set（L1632/1637）。
- **theme 省略**：`_BUILTIN_THEMES` 仅 `css/monokai/dracula/vscode_dark/github_light`，
  `theme="text"` 未知主题 → `_set_theme` 抛 `ThemeDoesNotExist`（widgets/_text_area.py
  L86/L1005）——ModalTextArea 不传 theme，用默认 "css"。
- **粘贴走 OS 剪贴板**：Textual 默认 action_paste 只读 app.clipboard（仅 app 内复制内容，
  外部复制永远粘空——PasteInput 同款病因）；照 PasteInput（src/tui.py L88-135）
  `run_worker(thread=True, exclusive=True)` + worker 内 `self.app.call_from_thread(...)`
  （`call_from_thread` 只在 App，widget.py 8.2.8 无）；UI 回调 `is_mounted` 守卫。
  空剪贴板回落原生 app.clipboard 语义（与 _text_area.py L2661-2667 同构）。
- **id 净化为索引式**：原 `id=f"param_{k}"` 把 key 当 CSS id（key 含 `.`/`-` 即坏选择器，
  且 `#param_command` 类硬引用散落测试）；改 `#param_{idx}` + `_key_idx` 映射，
  模态内引用全部走映射，测试同步改。
- **留空语义**：`modal_edit_result` 由 `str(values.get(k,"")).strip() or args[k]` 改为
  「全空白（含多行空白）→ 回落原值；非空白 → 原样（不 strip）」。旧行为是其子集
  （`"  "` → 原值仍成立），唯一变化是尾部空白/换行不再被剥。
- **can-focus: no**（textual/css/constants.py L68 实证属性存在）：三个 VerticalScroll 容器
  去可聚焦，焦点链路只剩「显式 AUTO_FOCUS / 输入部件 / 按钮」，消解 tui-ux8 焦点族结构根因。
- **CLI 不动**：`_handle_interrupts` CLI 编辑路径（streaming.py L242-247）与 `/use` 内核零改动；
  多行字符串经 `{"decisions": [...]}` JSON 回注无碍。

## Testing Decisions

- 锚点回归（每票跑）：`tests/test_tui.py::test_edit_params_modal_typing_writes_to_input`
  （L1071 改查 `#param_0` ModalTextArea `.text`）+ `test_permission_modal_enter_approves_directly`。
- 01 新增：Label 展示行含原值（`"whoami" in label.content`，Label 构造 `markup=False` →
  `Static.content` 属性存原始 str，8.2.8 无 `Widget.plain`）；`modal_edit_result` 纯函数
  多组（多行保留/全空白回落/短串）；Enter 插 \n round-trip（多行通道验证点）；
  短屏 12 行按钮仍可见（既有 `test_edit_params_modal_short_screen_12_buttons_on_screen`
  在 height:5 编辑框下需仍绿）。
- 02 新增：ctrl+shift+enter 插 \n；monkeypatch `src.tui.read_os_clipboard` 粘多行；
  重聚焦 `selection.is_empty`（灰态消解断言）。
- 03 新增：execute 审批按 `s` → 焦点落 `#prefix_input`。
- 纪律：Textual 8.2.8 modal 内部件一律 `app.screen.query_one`；新测试禁用 tmp_path/
  tempfile.mkdtemp（WinError 5 中毒）；探针放 `scratch/` 不提交；全量对照预存失败基线
  （3× test_config + drain flaky + tmp 中毒族，`--ignore=tests/test_rag.py`）。
