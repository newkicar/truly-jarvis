# TUI 体验十三（tui-ux13）：输入框多行内换行 + 中文输入不挑电脑

**Type:** bugfix (两个输入框相关 bug)
**Status:** done
**Blocked by:** 无

## Problem Statement

用户（原话）：「又发现 2 个问题，都是关于输入框的。**Bug 1**：shift+enter 会把对话放到缓存区（continuation buffer），而不是在输入框内换行——这样已缓存信息无法修改；正常应在**输入框内换行**。**Bug 2**：同事安装 jarvis 后在他的电脑上**无法在输入框输入中文**——要修到「不挑电脑」（跨终端 / 跨 IME / 跨环境鲁棒，不能只修本机单点）。

现状锚点（代码侦察结论，2026-10-21）：

- **Bug 1 根因**：tui-ux6 定案时主输入框是单行 `PasteInput(Input)`（src/tui.py L88），
  多行靠 `#continuation` 续行缓冲（L987 栈 + L1107 dim 面板 + L1670-1715
  `action_continuation_newline`/提交 join）。shift+enter 把整行 push 出框、清空输入框——
  已确认行无法再编辑（Backspace 只能整行弹回，不能局部改字），提交在 `on_input_submitted`
  （L1703）用 `\n` 拼接。这正是用户说的「放到缓存区、无法修改」。
- **Bug 2 现状**：ime_shim（src/ime_shim.py，tui-ux5 #11）已修 Textual win32 驱动丢
  UNICODE/IME 记录的主病；但它**只在 main.py L247 安装一次**（Textual 版本改形时静默
  漂移 → 仅启动行警告）、`/doctor` 输入通道行（input_probe.doctor_input_channel_line）
  只看 CP + stdin 句柄类型，**不报 shim 安装/漂移状态**，`input_probe` 跑完只记录不总结——
  同事环境失败时没有任何自动定位手段，修「不挑电脑」缺的正是**分层自诊断 + 兜底闭环**。

## 定案决策（grill 结论，不再追问）

1. **Bug 1 = 输入框内真实换行**（用户已拍板「在输入框内换行」）：主输入框换成
   TextArea 系控件（Textual 8.2.8 无 TextAreaInput 类，实证 `widgets/_text_area.py`
   只有 `TextArea`；已有 `ModalTextArea`（tui-ux10）先例可继承 OS 粘贴做法）。
   已确认行 = 框内可编辑文本，自由改字、光标自由移动；删掉 continuation 栈与
   `#continuation` 面板（含空框 Backspace 弹回、`/` 首行禁换行 notify 等旧语义）。
2. **键位**：`Enter` = 提交整框（保留框内 `\n`）；`shift+enter` = 框内插 `\n`；
   `ctrl+j` 保留为换行退路键（ConPTY shift 透传不保证，tui-ux6 遗留待实测项——
   顺带在本批用探针收掉）。Ctrl+Z 原生行内撤销保留。
3. **提交语义**：多行消息 = 完整文本发模型（strip 尾随空行/尾空白）；
   **`/` 命令必须整条单行**（含 `\n` 的 `/` 输入 → 提示「/ 命令请放一行」不提交，
   与 tui-ux6「命令不支持换行」一脉相承但语义升级：不是禁换行，是命令不允许多行）。
   非 slash 多行消息按普通消息进门控（tui-ux7 turn gate 语义不变）。
4. **补全锚点**：`/`、`@`、`/use` 触发判定与 Tab/Enter 接受**只看光标所在行**
   （`value.splitlines()` 取 cursor 行 + 列投影）；接受建议只改光标行，重建全文。
   `resolve_overlay_state` / `apply_suggestion`（src/tui_completion.py）内核不动，
   只换调用侧投影。
5. **粘贴**：多行文本全量入框（现状 `_apply_paste` 只取首行 L135——语义升级）；
   图片路径探测（首行像路径 → `[Image #N]`）与图片剪贴板路径不变。
6. **尺寸**：`#input` 1 行高起步、随内容长高、上限 5 行后内部滚动（`overflow-y: auto`）；
   gutter 行号隐藏（`TextArea` CSS `gutter: none` 或 padding 归零，实现时以探针为准）；
   光标常驻可见（Input 的焦点闪烁语义由 TextArea 光标接管）。
7. **Bug 2 = 三层闭环**（「不挑电脑」不靠猜，靠分层定位 + 兜底）：
   - L1 **自动层**：ime_shim 安装从「main.py 一次」升级为「TUI 装配前必检 + 周期漂移
     复检」；漂移/未装 → **可见 notify 提示面板兜底**（不再静默 startup line）。
   - L2 **手动层**：`/doctor` 输入通道扩 2 行（shim 状态 + 终端类型：conhost/WT/ConEmu/
     pipe-CP 告警聚合）；`input_probe` 结束追加**总结段**（观察到的记录类型直方图：
     KEY/UNICODE/IME/SIZE 各几条 + 中文确认形态判定 + 「下一步怎么办」指引文案）。
   - L3 **兜底层**（已有，补入口提示）：Ctrl+. 标点快插面板 + `tui.ime_hint` 自动提示，
     保证最坏情况也能把常用中文标点插进去。
8. **不自动 SetConsoleCP**（ConPTY 65000→65001 破坏 IME 的既有红线，input_probe 文档
   已定案）——CP 异常只诊断告警，不自动修。

## Solution

四张工单（顺序执行；01/02 独立可并行，03 依赖 01/02 全部完成）：

1. **01 多行输入框内核（Bug 1）**：`PasteTextArea(TextArea)` 基础类（OS 剪贴板粘贴 +
   全量多行 paste，`ModalTextArea` 改继承它收拢重复）；主输入框 `#input` 换
   `JarvisTextArea`；键位（Enter 提交 / shift+enter + ctrl+j 换行）；补全按光标行投影；
   提交语义（多行发模型 / slash 单行门禁）；删 continuation 全套；`#input` CSS 1→5 行
   自适应 + 光标可见 + gutter 隐藏。纯逻辑（补全投影、提交构造）放
   `src/tui_completion.py` / `src/commands.py` 可单测函数。
2. **02 IME 通道鲁棒化 + 诊断扩展（Bug 2 L1/L2）**：`ime_shim` 漂移复检 + 可见告警
   （纯函数 `shim_status() -> ("installed"|"drifted"|"absent")` 可单测）；
   `input_probe` 总结段（记录类型直方图 + 判定 + 指引，纯函数可单测）；`/doctor`
   扩 2 行。
3. **03 中文输入不挑电脑验收门禁（Bug 2 L3 + 回归面）**：本机全环境走查
   （conhost / Windows Terminal / PowerShell ConPTY 三端点：输入法确认汉字 + 全角标点
   可达）；同事复现路径 = 一份「两步自诊断」清单（`/doctor` 输入通道 2 行 +
   `python -m src.input_probe` 回传）；探针收掉 shift+enter 在 ConPTY 可达性
   （tui-ux6 遗留 `scratch/probe_shift_enter.py` 未实测项）。无新增主代码（诊断/兜底
   在 01/02 已就位），产出 = 走查记录 + 回传清单 + 工单验收。
4. **04 回归 + 文档 + 收官**：全量 pytest 对照基线（609 passed + 预存 3× test_config）→
   AGENTS.md「TUI 体验十三」条目 → 四张工单 done + 勾选 → docs commit → push main →
   CI 轮询绿 → 中文汇报（含 Bug1 换行语义变化 + Bug2 三层闭环说明 + 需用户/同事实测
   回传项单列不阻塞）。

## User Stories

1. 作为用户，我按 shift+enter，输入框**当场**多出一行且框长高（1→5 行内），已写的
   前一行可以光标移回去改字。
2. 作为用户，我写多行消息后按 Enter，整段（含 `\n`）作为一条消息发出，尾随空行被裁。
3. 作为用户，我在多行消息的某一行里打 `/`，补全建议基于**光标所在行**出现；Tab
   接受只替换该行的触发片段，其他行不动。
4. 作为用户，我粘贴一段多行文本，整段进框（不再是只取首行）。
5. 作为用户，我打 `/use` 后换行再打说明文字——合法：提交后 `/use` 行 + 说明行合并为
   一条多行消息（`/use` 本身仍须在其单行内写全 skill 名；多行时 `/use` 门禁提示）。
   （细则：`/` 开头且含 `\n` = 不提交并提示，与决策 3 一致。）
6. 作为用户，输入框超过 5 行后继续打，框内滚动而布局不炸；光标所在行始终可见
   （TextArea 原生 focus 滚动）。
7. 作为用户（同事环境），我在他的电脑上打开 TUI，若 IME 通道异常，**启动即见**
   「中文输入可能异常 + Ctrl+. 快插」提示，而不是输入半天发现进不去再盲猜。
8. 作为用户，我在异常环境跑 `/doctor`，输入通道段落直接告诉我：shim 是
   installed/drifted/absent + 终端类型 + CP，不用开源码猜。
9. 作为用户，我跑 `python -m src.input_probe` 打完几个汉字，结尾看到总结：
   「IME 确认字符经 UNICODE_EVENT/IME_EVENT 下发 N 次，通道正常」或「只看到
   KEY_EVENT(NUL-uChar)，疑似 ConPTY/IME 组合，按指引 xxx」。
10. 作为用户，即使中文输入彻底进不去，Ctrl+. 标点面板仍能把 ，。！？“” 等常用
    标点插进输入框（最坏兜底）。
11. 作为维护者，Textual 升级改形时 ime_shim 周期复检会再次出声（notify 而非日志），
    静默漂移面收敛。
12. 作为维护者，continuation 栈 / `#continuation` 面板 / 空框 Backspace 弹回 /
    `/` 首行禁换行 notify 全部删除，无遗留死代码（全仓 grep 清零）。

## Implementation Decisions

- **控件选型**：Textual 8.2.8 无 `TextAreaInput`（探针实证 widget 类清单只有
  `Input` / `TextArea`），故 `JarvisTextArea(TextArea)` 直接继承；`ModalTextArea`
  升级为继承新的 `PasteTextArea(TextArea)`（OS 粘贴 + 全量 paste 逻辑上提，
  tui-ux10 既有行为零回归）。
- **键位覆盖**：TextArea 原生 `_on_key` 把 `enter` 映射为插 `\n`
  （`widgets/_text_area.py` `_on_key` L66695 实证）→ `JarvisTextArea` 覆盖
  `_on_key`：`enter`（无修饰）→ prevent_default + 发 `JarvisSubmitted`（或回调
  `app` action）；`shift+enter` / `ctrl+j` → 原生插 `\n`；printable 字符走原生。
  `tab` 仍由 app 级 `on_key` 拦截（补全活跃 → 接受建议；否则 `toggle_mode`）——
  现状 `on_key` 拦截在 Screen 层，控件换成 TextArea 后拦截链不变（实证
  L1640-1666 `on_key` 对 down/up/escape/tab 的处理挂在 JarvisApp）。
- **补全投影（01 核心纯逻辑）**：新增 `src/tui_completion.py::
  line_projection(text: str, cursor: tuple[int,int]) -> tuple[str, int]`
  （cursor 行文本 + 该行内列）与 `apply_suggestion_on_line(text, cursor, at_index,
  line_at_index, insert) -> tuple[str, int]`（改光标行、列回算）。
  `resolve_overlay_state` 入参改为 (line_value, line_cursor)；`/use` 的
  `use_query`（L71）只在光标行内匹配。
- **提交构造（01 核心纯逻辑）**：`commands.build_submission(raw: str) ->
  tuple[str, str|None]`：返回 (payload, error)；payload = 去尾随空行/尾空白；
  error 非空时 TUI 只 notify 不提交（`/` 含 `\n` → 「/ 命令请放一行」。CLI 不受影响）。
- **`/` 门禁位置**：`_handle_user_message`（L1278）前 —— `on_input_submitted`
  等价入口改在 `JarvisApp` 侧消费 `JarvisSubmitted`；slash 判定沿用
  `text.startswith("/")` + `is_virtual_path_reference`（虚拟前缀路径可多行不受限，
  与现状一致）。
- **`#input` 调用面清单（01 全量，实测 grep）**：L1110 compose（换类）、
  L1268/L1484/L1542/L1808/L1833 focus、L1296 提交后清空（改 TextArea 清空 API）、
  L1434 undo 回显（改 text 赋值）、L1603/L1627/L1674 补全/continuation（删/改投影）、
  L1822 `_insert_punctuation`（`selection`/`replace`/`insert_text_at_cursor` →
  TextArea `selection` + `_replace_via_keyboard` + `move_cursor`，同 ModalTextArea
  L420 做法）。类型标注 `query_one("#input", Input)` → `JarvisTextArea`（或
  `PasteTextArea` 基类）全部替换。
- **continuation 删除面（01）**：`_continuation`（L987）、`_cmd_newline_hinted`
  （L988 语义并入 slash 门禁提示，可删可留由实现定，工单要求全仓 grep 清零
  `_continuation`）、`#continuation` CSS（L893-903）与 compose L1107、
  `action_continuation_newline` / `_refresh_continuation`（L1670-1697）、
  `on_input_submitted` join 逻辑（L1703-1715）、PasteInput.on_event 空框 Backspace
  弹回（L153-170）。`/use` 补全（tui-ux9）与双 Esc undo、turn gate、NoMatches
  兜底**语义不变**。
- **ime_shim 鲁棒化（02）**：`install()` 语义扩展为 `ensure() -> str`
  （"installed"/"drifted"/"absent"，幂等 + 漂移检测复用既有 `inspect.getsource`
  签名校验）；`shim_status()` 纯函数读 `mod.EventMonitor` 属性；main.py L247
  与 TUI 装配前各调一次；漂移 → TUI `notify`（一次性）+ 启动行保留；
  `JarvisApp` 侧低频复检（如每 30s 一次 set_interval 或模态打开时，实现自选，
  测试以纯函数 + 一次调用时序为准）。**不改** `fold_input_records` 既有折叠规则。
- **input_probe 总结段（02）**：`summarize_session(records) -> str`（纯函数）：
  记录类型直方图（KEY/UNICODE/IME/SIZE 计数）+ NUL-uChar 计数 → 判定
  「通道正常（UNICODE/IME 有确认流）」/「疑似 KEY-only 形态（对照 tui-ux5 #11
  重建条件）」/「无输入记录」三态 + 下一步指引（跑 /doctor、切终端、Ctrl+. 兜底）。
  `main` 退出前打印；`channel_line`/`doctor_input_channel_line` 现状不动，
  `/doctor` 新增 2 行（shim 状态行 + 终端类型行，终端类型复用
  `tui_punct.is_conhost_like` 思路扩 WT_SESSION/ConEmu/pipe 三态）。
- **测试纪律**：新测试禁 `tmp_path`/`tempfile.mkdtemp`（自建目录）；Textual 8.2.8
  modal 激活时 `app.screen.query_one`（本批 modal 不动，主要防 01 的
  `#input` 查询回归）；Textual pilot 键盘序列：shift+enter、ctrl+j、enter 提交、
  Tab 接受补全、粘贴多行（monkeypatch `read_os_clipboard`）。

## Testing Decisions

- `tests/test_tui.py`（01 主战场）：
  - shift+enter 框内插 `\n`（pilot 键序列 → `#input` text 含换行、控件长高）；
  - ctrl+j 同语义（退路键）；
  - Enter 提交多行（`_handle_user_message` 收到完整 `\n` 文本、尾空行被裁）；
  - `/` 多行被门禁（notify 文案 + 不进门控不发消息）；
  - 补全：光标在第 2 行打 `@`/`/use` → overlay 出现、Tab 接受只改第 2 行、
    第 1 行原样（投影函数单测覆盖纯逻辑，pilot 覆盖 UI 链路）；
  - 粘贴多行全量入框（mock `read_os_clipboard` 返回 3 行 → 框内 3 行）；
  - continuation 面清零：全仓 grep `_continuation`/`#continuation` 无残留（工单自查项）。
- `tests/test_tui_completion.py`：`line_projection` / `apply_suggestion_on_line`
  纯函数组（光标在首/中/末行、行内列 0/中/尾、插入含空格建议）。
- `tests/test_commands.py`：`build_submission` 纯函数组（空行裁剪、`/` 门禁、
  虚拟前缀多行放行）。
- `tests/test_ime_shim.py`（02）：`shim_status()` 三态（mock `EventMonitor`
  属性组合）；漂移复检调用时序（monkeypatch install 计数）。
- `tests/test_input_probe.py`（02）：`summarize_session` 三态判定 + 直方数字段；
  `/doctor` 新 2 行渲染（终端三态：conhost/WT/pipe 各一）。
- 全量回归基线：本地 **609 passed + 预存 3× test_config 失败**（勿新增失败）；
  CI **593 passed, 4 skipped**。

## Out of Scope

- CLI 模式（`--cli`）：本就无输入框/无 IME 问题，零改动。
- 自动 SetConsoleCP / 自动切 ConPTY 编码（既定红线，仅告警）。
- 子代理（`task` 生成器）与 scheduler 线程的输入路径（不经 TUI 输入框）。
- EditParamsModal / PrefixModal 内部件（01 只把 `ModalTextArea` 改继承
  `PasteTextArea`，行为零变化）。
- 中文输入法本身（Windows IME/系统层）的修复——那是 OS 行为，本批只做
  应用层通道鲁棒化 + 诊断 + 兜底。
- Mac/Linux 输入路径（本项目 Windows-only 部署，`ime_shim` 非 win32 直接
  返回 True 的现状保持）。

## Further Notes

- 命名：新类 `PasteTextArea`（粘贴基类）+ `JarvisTextArea`（主输入框，id 仍 `#input`）；
  提交消息 `JarvisSubmitted`（Textual Message，widget 自定义，避免碰
  `Input.Submitted` 类型系统）。
- `#input` 保持 id 不变（CSS 选择器、侧边栏、所有 `query_one("#input", ...)` 的 id
  引用零改动，只换类型标注与 API 调用）。
- 5 行上限值（决策 6）可在实现时探针微调（4/5/6），以「短屏（24 行终端）+
  modal 按钮行可见性」回归不炸为准（tui-ux10 布局规约同源）。
- 收官（2026-10-22）：
  - 工单 01/02/03 全 done + 验收全勾；工单 04 验收项 1–3 勾选，CI 项待绿后补勾。
  - 全量回归：本地 634 passed + 仅预存 3× test_config 失败（0 新增）；CI 基线 593 passed / 4 skipped。
  - 探针：`scratch/probe_shift_enter.py` 4/4 PASS（Textual 层）；真实终端 3 项（a) 三端点中文走查 2 汉字 + 1 全角标点；b) 同事两步自诊断回传；c) ConPTY shift+enter 透传 + ctrl+j 退路实测）留用户/同事实测，不阻塞。
  - AGENTS.md「TUI 体验十三」条目落盘（密文风格对齐 tui-ux10/tui-ux12）。
  - 实现 commit `80315be`（docs commit 回填）。
