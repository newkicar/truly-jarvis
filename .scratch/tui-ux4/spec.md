# TUI 四项 UX 问题（tui-ux4）

**Type:** enhancement
**Status:** ready-for-agent

## 背景（用户报告 + 根因取证）

1. **对话区内容难复制**：拖选复制依赖 Win32 SetClipboardData 一次性写入（tui_log.copy_text_to_system_clipboard，失败即止、无重试），CMD/conhost 下成功率低；流式开始时选区被清除。codex 的做法是「程序化复制为主」：Ctrl+O 复制最近 AI 回复、/copy picker 选整条/代码块、剪贴板写入多级级联（arboard→PowerShell→OSC52）。
2. **输入框中文标点不全**：，。、可输入是 IME 直接 commit 的字符；省略号/引号/书名号等需 IME 候选窗，raw mode（Textual）+ conhost 下候选窗不可用。Textual 无 IME composition 支持（codex 同为零 IME 代码，靠 grapheme 边界 + 保留 AltGr）。结论：不造 IME，用「快捷标点面板 + 环境提示」补缺口。
3. **输入框不能粘贴图片**：PasteInput 粘贴走 read_os_clipboard() 只读文本；run_agent_turn 的 user_input 是纯字符串，无多模态结构。codex 做法：剪贴板有图片时读剪贴板图像→落盘临时 PNG→输入框插 [Image #N] 原子占位符→提交时读文件→（>2048px 缩放）→base64 data URL 注入。
4. **@ 引用带 /workspace/ 前缀有时不可用**：deepagents 仓库层剥前缀（/workspace/x→项目根锚定），文件工具一直通；两个断点——a) shell_backend._virtual_prefix_error 守卫报错不给真实路径映射；b) 用户复制出的 /workspace/... 是虚拟路径，Windows 磁盘上不存在。方案：不改路由，做「映射可见化 + 双路径呈现」。

## 方案（按票拆分，实施顺序 01 → 04 → 03 → 02）

### 01 复制（copy）
- C1 程序化复制：/copy 命令（TUI 走 picker；CLI 给 TUI 提示）+ 快捷键 Ctrl+Shift+Y 打开 CopyPickerModal（OptionList）：①最近 AI 回复（复用 commands.last_ai_text）②最近代码块（新增 commands.last_code_block 纯函数，取最后一个三反引号围栏）③整段会话（新增 commands.render_session_text）。
- C2 剪贴板写入级联：copy_text_to_system_clipboard 拆为 Win32（重试 2 次）→ PowerShell Set-Clipboard 两级级联；CopyableRichLog.copy_selection_to_clipboard 与 JarvisApp._copy_to_clipboard 统一走级联。
- C3 copy_on_select 默认 True：JarvisApp._copy_on_select() 的 fallback False→True（与 config.GLOBAL_DEFAULTS、项目 jarvis.json 现状对齐）。
- 文案：_HELP_COMMANDS / TUI_HELP / 欢迎语补 /copy 与 Ctrl+Shift+Y。

### 04 路径前缀（at-reference）
- P4-1 路径锚点行：提交消息含虚拟前缀时，用户消息下方追加 dim 行「路径锚点: /workspace/x → D:\...\x」（纯函数 commands.path_anchor_lines(text, mapping)；mapping 来自 commands.virtual_path_mappings(config)）。
- P4-2 守卫报错补映射：InheritedEnvShellBackend 新增 prefix_map 构造参数（agent._make_backend 传入各前缀真实根目录）；_virtual_prefix_error 报错追加「该前缀对应真实目录：<root>，shell 里请改用项目根相对路径或真实路径」。
- P4-3/P4-4 @ 补全双路径：新配置 tui.at_reference_style（virtual/dual/real，默认 dual）：dual=标签虚拟路径 + hint 真实路径；real=标签与插入值均为真实路径（#10 起文件工具本就接受任意真实路径）；virtual=现状。在 tui_completion.resolve_overlay_state 内按 style 转换（新参数 path_mapping + at_reference_style，缺省保持旧行为，既有测试不动）。

### 03 图片粘贴（clipboard-image）
- J1 读剪贴板图片：新模块 src/clipboard_image.py。Windows 走 PowerShell Get-Clipboard -Format Image + System.Drawing 存 %TEMP%\jarvis-clipboard-<ts>.png（零新依赖）；macOS/Linux 尽力（xclip/wl-paste -t image/png）。失败返回 None。
- J2 占位符 + 附件登记：粘贴时剪贴板无文本但读到图片 → 输入框插 [Image #N] 原子占位符，app 登记 index→temp_path；粘贴文本若为已存在的图片文件路径（J5）同样登记转占位符。提交后清空登记。
- J3 多模态 content：run_agent_turn 的 user_input 放宽为 str | list | None（content 透传，OpenAI 兼容端点收 image_url data URL）；TUI 提交时 build_multimodal_content(text, attachments) 生成 text + image_url parts；显示仍用原始占位文本。
- J4 能力门：新配置 model.image_input（auto/on/off，默认 auto）：off=占位符替换为「图片路径引用」纯文本；on=直接发；auto=首发多模态，API 报 image/vision 类错误时自动以「图片路径引用 + 说明」重发一次（TurnPresenter 层重派发，不写历史）。
- 不做：图片缩放（无 Pillow 依赖；>4MB 直接提示过大）。

### 02 标点（punctuation）
- I1 conhost 提示：tui.ime_hint（auto/on/off，默认 auto）：启动时探测终端（Windows 无 WT_SESSION/ConEmu* 环境变量 ≈ conhost）→ 写一行 dim 提示「conhost 下部分中文标点 IME 候选不可用，按 Ctrl+. 快插」。
- I2 标点快插面板：Ctrl+. 打开 PunctPanelModal（OptionList，约 24 个高频标点，Enter 插入当前输入框、Esc 关闭）。
- I3 按键审计：Ctrl+. 与 Textual/终端默认、微软拼音 IME、既有绑定（ctrl+v/tab/ctrl+insert…）无冲突；AltGr 保留给文字输入（不入绑定）。

## 新增配置键（全部进 jarvis.json，缺省值在 config.GLOBAL_DEFAULTS / 代码 fallback）
| 键 | 默认 | 票 |
|---|---|---|
| tui.copy_on_select | true（fallback 改 True） | 01 |
| tui.at_reference_style | "dual" | 04 |
| model.image_input | "auto" | 03 |
| tui.ime_hint | "auto" | 02 |

## 非目标
- 不造 IME composition（Textual 无支持，conhost 无候选窗——与 codex 同一限制）
- 不改 deepagents 虚拟前缀路由（#10 已定：前缀=快捷方式，映射可见化即可）
- 不做图片缩放/压缩（零新依赖原则）
- 不动 CLI 的文本流式输出（图片/标点面板为 TUI 能力；CLI 只保留 /copy 降级提示）

## 回归门
- 每票实现后跑相关单测 + 受影响模块单测；全量单测以逐文件基线为准（已知全量跑会触发 ThreadPoolExecutor 原生 AV——AGENTS.md 既有已知问题），不允许引入新的文件级失败。
- 测试基线：逐文件记录于 tmp/baseline_perfile.txt（实施当天生成）。

## 参考
- codex（本地快照 D:\Python Project\mine_codex + 上游 openai/codex 同源）：paste_image_to_temp_png（arboard→PowerShell 兜底、tempfile keep、[Image #N] 原子占位符、>2048px 缩放）；复制级联（Ctrl+O / /copy picker / OSC52 100KB 上限 / tmux DCS）；IME 零代码（grapheme 边界 + keymap.rs 保留 AltGr）。
- 本项目既有机制：#07 CopyableRichLog 方案 2、#10 路径放开、TUI 粘贴 PasteInput（src/tui.py）、虚拟前缀守卫（src/shell_backend.py）、TurnPresenter（src/tui_turn.py）。

## Comments
- 2026-10-14：方案经用户确认，落盘 + 拆票执行（01→04→03→02）。
