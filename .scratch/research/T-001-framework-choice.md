# T-001 研究：原生 GUI 框架选型（Python/Windows）

> 工单：`.scratch/gui-wayfinder/tickets/T-001-framework-choice.md` · 研究代理 · 2026-10-26
> 检索方式：2026-10-26 在线搜索（GitHub/官方文档/社区，链接均真实）；个别未单独在线验证的条目标注**【离线推断、未验证】**。

## TL;DR 推荐

**PySide6（base 包，仅 QtWidgets；禁用 PySide6-Addons）+ Nuitka 打包，与 deepagents harness 同进程共存。**

- 中文 IME：Qt Windows 原生 IME（组合输入事件）成熟，中文输入开箱可用（唯一硬性维度，Kivy/DearPyGui 直接出局，Tkinter 历史弱）。
- Markdown 流式：QTextBrowser/QTextEdit 自 Qt 5.14 起原生 Markdown，用 append 式增量追加 + 尾部自动滚动，避免全量重绘。
- 拖选/复制/右键：Qt 原生零成本。
- 打包：Nuitka standalone 社区实测 Qt 应用单 exe 约 40MB 量级；Nuitka 误报率显著低于 PyInstaller（PyInstaller 误报根因 = 其 bootloader 是恶意软件共性组件）；**必须代码签名**。
- 许可：PySide6 base = LGPLv3（可选商业许可），Qt 官方许可变更页截至 6.12 **无 GPLv3 迁移**，LGPL/AGPL 结构未变；AGPL 风险集中在 PySide6-Addons（QtQuick/QtWebEngine），**不依赖该包即无 AGPL 传染**。
- 测试：pytest-qt 官方支持 PySide6，Windows 可 offscreen 无头测试。
- C#/Rust 宿主 + Python 边界（pyo3 内嵌 / Tauri sidecar）技术成熟但维护成本翻倍，**本期不做，列 P2**（Jan v0.6.0 Electron→Tauri 即此类演进先例）。

## 先例清单（必查 4 项 + 补充）

| 产品 | 仓库/链接 | GUI 技术栈 | 打包方式 | 可抄的点 |
|---|---|---|---|---|
| LM Studio | https://github.com/lmstudio-ai/lmstudio-bug-tracker （闭源产品，公开 bug tracker；Electron 证据见其 Electron 类 issue） | Electron（桌面）；推理后端后移 Rust | Electron 安装包（NSIS 类） | 「GUI 宿主 + 独立高性能引擎」分层；LLM 客户端 UX 面（模型管理/聊天/流式） |
| Jan | https://github.com/janhq/jan · Tauri 迁移公告：https://www.reddit.com/r/LocalLLaMA/comments/1lf5yog/jan_got_an_upgrade_new_design_switched_from/ | **v0.6.0（2025-01）Electron → Tauri**（Rust `tauri-plugin-llamacpp`）；AGPL-3.0（佐证：https://huggingface.co/datasets/jan-hq/jan_docs 「[Jan Framework] (AGPLv3)」） | Tauri 单包（前端走系统 WebView） | 本地 LLM + GUI 宿主分层；「Electron 太重→Tauri 瘦身」的业界共识（社区实测安装包缩小 ~70%【离线推断：常见报道口径】） |
| ChatBox | https://github.com/chatboxai/chatbox | Electron（React + Mantine + Vite）；GPL-3.0 | Electron 安装包 | **用户自配 LLM 端点/密钥（OpenAI 兼容）的设置模型**——与 Jarvis「LLM 各人自配」完全同构，设置页可直接参考 |
| AnythingLLM | https://github.com/Mintplex-Labs/anything-llm | Electron 桌面（Win/Mac/Linux）+ Docker 服务端双形态；仓库 MIT（桌面版另有 ToS） | Electron 安装包 / Docker | 「桌面 + 服务端」双形态打包经验；自带 embedding/RAG 的捆绑方式 |
| （补充）pyo3/pyoxidizer | https://github.com/pyo3/pyo3 · https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_rust_generic_embedding.html | Rust 宿主内嵌 CPython | 原生单 exe | C#/Rust 宿主 + Python 边界路线的成熟先例（PyOxidizer「Generic Python Embedding」） |
| （补充）pythonnet | https://github.com/pythonnet/pythonnet | .NET 宿主内嵌 CPython | MSBuild | C# 宿主路线先例 |

**先例结论**：LLM 桌面客户端主流 = Electron/Tauri（web 技术栈）。但 Jarvis 约束是 **Python 3.12 + deepagents 同进程 + 单机 exe**；Electron/Tauri 都意味着 UI 与 Python agent 核心跨进程 IPC（流式 token、HITL 中断、checkpoint 状态同步复杂化）。纯 Python 原生 GUI 里 **PySide6 生态最成熟、最接近生产**，且 pythonguis 官方文档有 Nuitka+Qt 专章（https://www.pythonguis.com/faq/how-to-compile-pyqt6-or-pyside6-code-with-nuitka%20copy/ ）。
## 候选对比表（工单 6 维度）

图例：★=强 ✔=可用 ⚠=弱/有坑 ✖=不满足

| 维度 | PySide6/Qt | Tkinter | Kivy | DearPyGui | C#/Rust 宿主+Python 边界 |
|---|---|---|---|---|---|
| ① 中文 IME | ★ Qt Windows 原生 IME 成熟；自绘控件/补全弹层上的组合窗定位需在原型复核 | ⚠ 历史弱：SO 长期问题（https://stackoverflow.com/questions/28747976/is-it-possible-to-input-chinese-text-into-tk-text-and-entry-widgets-with-tkinter ，11 年未根治）；Win10/11 默认环境基本可用、组合窗行为不稳定【离线推断、未验证】 | ✖ kivy/kivy#434（2012，Windows 中文 IME 失效）、#8444（2023，I18N 仍是开放 meta issue） | ✖ issue #1571（Windows IME 输入 3~4 字符/秒）、#2532（中日输入变 `?`，真实 bug）（https://github.com/hoffstadt/DearPyGui/issues/1571 、 /issues/2532 ） | 取决于宿主：Tauri（系统 WebView）★ / egui（有 IME 支持但早期） / WinForms(.NET)★ |
| ② Markdown 流式 | ★ QTextBrowser/QTextEdit 原生 Markdown（5.14+，https://doc.qt.io/qt-6/qtextedit.html ）；append 增量 + 自动滚动；代码高亮 QSyntaxHighlighter（官方自带 highlighters） | ⚠ 无原生 Markdown；Text widget 手工插字 + 自写高亮（可做增量，无富文本渲染） | ⚠ 无原生 Markdown，label 重排成本高 | ✔ dearpygui 有 Markdown widget；流式场景全量重绘代价高【离线推断】 | Tauri/WebView = web 全生态（streaming-markdown 类库直接可用）；egui 需自研 |
| ③ 拖选/复制/右键 | ★ 原生零成本 | ✔ 原生（观感旧） | ⚠ 事件模型自研，右键菜单手工 | ⚠ 即时模式 UI，选择语义弱，需手工 | 取决于宿主（WebView ★） |
| ④ 单 exe 打包 | ★ Nuitka standalone：社区实测 Qt6 应用 **~40MB 单 exe**（https://www.reddit.com/r/Python/comments/1je94cf/pyside6_nuitka_is_very_impressive_some_numbers/ ）；Nuitka 误报率低于 PyInstaller（官方 FAQ：Nuitka 编译为 C→原生 exe，https://www.pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/ ）；PyInstaller 误报根因 = bootloader 是恶意软件共性组件（https://github.com/pyinstaller/pyinstaller/issues/6754 官方答复）；**代码签名是终极解法** | ★ 体积最小（stdlib，exe 10~30MB 级【离线推断、未验证】）；PyInstaller/Nuitka 均可 | ⚠ 依赖多（SDL2 全家），打包坑多，误报未知【离线推断、未验证】 | ✔ C 后端单文件小；维护活跃度下降【离线推断、未验证】 | ★ Tauri sidecar ~10-20MB【离线推断、未验证】；pyo3 内嵌 = 原生单 exe 但构建链最重 |
| ⑤ 社区成熟度/Windows 质量 | ★ Qt 30 年标准件；PySide6 = Qt 官方出品，随 Qt 更新；pythonguis 生态活跃 | ✔ 30+ 年存在但外观/交互老旧，非原生观感 | ⚠ 重心转移动端；Windows 桌面 SDL2 渲染观感差、模糊 | ⚠ 曾活跃（GPU 渲染高 FPS），长期更新放缓【离线推断、未验证】 | ★（Tauri/pyo3 生态强）但双语言栈 |
| ⑥ 与 pytest 栈契合 | ★ pytest-qt 官方支持 PySide6（https://github.com/pytest-dev/pytest-qt ）；offscreen platform 支持 Windows 无头测试；纯逻辑层沿用现有 200+ 单测 | ⚠ 无成熟 pytest-qt 类生态，需自建 | ✖ 无 | ✖ 无 | ⚠ UI 测试另起炉灶（Playwright for Tauri 等） |

**评分小结**：PySide6 在 6 维度全部 ★/✔ 无硬伤；Tkinter 全维度「可用但不够」（IME⚠ + 无 Markdown + 观感旧）；Kivy ①✖⑤⚠；DearPyGui ①✖（真实 issue 实证）；跨语言方案 ④★ 但 ⑥⚠ 且维护成本出圈。

## 对 Jarvis 的可落地建议

1. **框架 = PySide6（base，仅 QtWidgets）**。
   - 依赖只用 `PySide6`（LGPLv3），**不用 `PySide6-Addons`**（AGPL：QtQuick/QtWebEngine 等）。
   - 链接方式：Nuitka 下默认可选动态/静态；为彻底规避 LGPL 静态链接「提供目标文件」义务，发布形态建议 **Qt DLL 与 exe 同目录动态共存**（LGPL 可自由修改替换豁免），且本场景无 SaaS 网络分发，LGPL 义务面很小。发布前建议过一道法务确认（见风险 §3）。
2. **打包 = Nuitka（首选）→ PyInstaller onedir（备选）→ cx_Freeze（第三备）**。
   - 发布形态建议：Nuitka **standalone（目录）+ Inno Setup 安装包**（与 Jan/ChatBox/LM Studio 实际发布姿势一致）；「真·单文件 onefile」作为权衡项——onefile 自解压启动慢（Nuitka 亦有 >1min 极端案例：https://stackoverflow.com/questions/78878245/experiencing-horrendous-startup-times-for-nuitka-standalone-apps ），体积收益有限。
   - **代码签名证书**（OV/EV，【离线推断：商业 OV ~50-100 美元/年 量级，未验证】）是杀软误报的根治项；发布附 SHA-256 + VirusTotal 自查流程。
   - 体积控制：RAG 依赖 chromadb 会带入 onnxruntime 等原生大包（体积可能 100MB+ 级【离线推断、未验证】）——**RAG/Ollama 作为可选依赖不入基础 exe**，需要时引导用户装 wheel 或外部 Ollama 服务（与 AGENTS.md「Ollama 不可用自动回落」语义一致）。
3. **TUI→GUI 控件映射**（presenter 模式，逻辑层不动）：
   - 对话区 = `QTextBrowser`：AI 流式 = 按 token 块 `append`（或定时合批）+ `verticalScrollBar` 钉底；消息头/工具行用富文本块着色（对应 `tui_format` 样式：用户 secondary / AI 粗竖线 / 工具 muted / 子代理黄）。
   - HITL 审批 = `QDialog`（对应 `PermissionModal`：放行/永久放行/拒绝/编辑参数 四按钮；**默认焦点=放行**——抄 TUI tui-ux8 的实证经验；EditParams 用 `QPlainTextEdit` 多行编辑，抄 tui-ux10「看得见改」语义：原值只读展示行 + 编辑框）。
   - 输入框 = `QPlainTextEdit` 多行：**Enter 提交 / Shift+Enter 换行**，提交语义直接复用 `commands.build_submission` 纯函数（tui-ux13 契约：/ 开头多行 → 提示不提交）。
   - `@`/`/` 补全 = `QCompleter` 或自绘 popup；内核**零改动复用** `tui_completion.line_projection` + `skill_discovery.fuzzy_filter_skills`（纯函数、框架无关）。
   - 侧边栏会话/todo 面板 = `QListWidget` + `QTreeWidget`；主题 = QSS + 明暗 palette（`watch_theme` 写回机制不变）。
   - 取消/排队 = 状态行 banner + thread 级 turn gate（tui-ux7 语义原样搬到 GUI 线程模型：agent 跑 worker 线程，UI 写必须经信号回主线程）。
4. **架构纪律**（对齐 map.md「架构学 opencode 解耦」）：`commands.py`/`streaming` presenter/`permissions`/补全内核保持框架无关；GUI 与 TUI/CLI 是同一 presenter 契约下的**三个渲染端**——这是 T-005（共存策略）能落地的前提，也是测试可复用 200+ 单测的关键。
5. **测试栈**：新增 `pytest-qt`；GUI 层测试 = qtbot + `QT_QPA_PLATFORM=offscreen`（Windows 下同样可用 offscreen）；逻辑层 200+ 单测原样跑。注意沿用本仓测试纪律（不用 tmp_path，自建目录）。
6. **原型验证顺序**（喂给 T-006）：先做最小原型一次性验证 ①Windows 中文字符 IME 进 QLineEdit/QPlainTextEdit ②QTextBrowser 流式 Markdown 追加 ③选区复制 + 右键菜单 ④Nuitka 打包 + 签名 + VirusTotal；四项绿再写 spec 定稿。
## 风险与未决

1. **杀软误报**：Nuitka 显著低于 PyInstaller 但非零；**签名 + 发布渠道教育（SHA-256/VT 链接/白名单指引）是必配**；PyInstaller 备选路线误报面更大。
2. **Nuitka 启动/构建成本**：onefile 自解压慢（存在 >1min 极端报告）→ 采用 onedir+安装包；Nuitka 编译耗时长（分钟级 vs PyInstaller 秒级）→ CI 缓存 C 扩展产物【离线推断、未验证】。
3. **Qt 许可**：确认事实——Qt 官方许可变更页（https://doc.qt.io/qt-6/license-changes.html ）截至 6.12 仅三方组件版本更新，**无 GPLv3 迁移**；LGPL 风险面 = 静态链接义务（动态共存规避）+ 修改 Qt 源码需提供修改源（本项目不修改 Qt）。发布前过法务确认（未决）。
4. **IME 细节**：Qt 原生 IME 成熟为「大体确认」，但组合窗在我们自定义补全弹层/小尺寸控件上的定位需 T-006 原型复核【离线推断、未验证】。
5. **流式 Markdown 解析**：append 只是渲染层；未闭合代码块/表格的增量解析需选策略（token 级流式解析器 vs 每 N token 全量重渲染 QSyntaxHighlighter），T-006 出数据。
6. **跨语言方案 P2**：pyo3/PyOxidizer 内嵌、Tauri sidecar 均有成熟先例；若后续追求极致体积/原生观感可重启评估（本期不投入）。
7. **GUI/TUI 共存并发**（SqliteSaver 锁竞争、turn gate 共享）属 T-005 范围，本票不扩。
8. **PySide6 与 Python 3.12 wheel 兼容性、chromadb 原生包入包行为**：需打包实测（未决，进 T-006 验证清单）【离线推断、未验证】。

## 链接总表（均 2026-10-26 在线检索所得）

- 先例：Jan https://github.com/janhq/jan ｜ Jan Tauri 迁移 https://www.reddit.com/r/LocalLLaMA/comments/1lf5yog/jan_got_an_upgrade_new_design_switched_from/ ｜ ChatBox https://github.com/chatboxai/chatbox ｜ AnythingLLM https://github.com/Mintplex-Labs/anything-llm ｜ LM Studio bug tracker https://github.com/lmstudio-ai/lmstudio-bug-tracker
- PySide6/Qt：许可 https://doc.qt.io/qtforpython-6/licenses.html ｜ 许可变更页 https://doc.qt.io/qt-6/license-changes.html ｜ QTextEdit https://doc.qt.io/qt-6/qtextedit.html ｜ QTextBrowser https://doc.qt.io/qt-6/qtextbrowser.html
- 打包：Nuitka FAQ(PySide6) https://www.pythonguis.com/faq/how-to-compile-pyqt6-or-pyside6-code-with-nuitka%20copy/ ｜ AV 对比 FAQ https://www.pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/ ｜ PyInstaller 误报根因 https://github.com/pyinstaller/pyinstaller/issues/6754 ｜ Nuitka Qt ~40MB 实测 https://www.reddit.com/r/Python/comments/1je94cf/pyside6_nuitka_is_very_impressive_some_numbers/ ｜ Nuitka 启动慢案例 https://stackoverflow.com/questions/78878245/experiencing-horrendous-startup-times-for-nuitka-standalone-apps
- 测试：pytest-qt https://github.com/pytest-dev/pytest-qt
- 反例/弱项：Kivy IME https://github.com/kivy/kivy/issues/434 、https://github.com/kivy/kivy/issues/8444 ｜ DearPyGui IME https://github.com/hoffstadt/DearPyGui/issues/1571 、https://github.com/hoffstadt/DearPyGui/issues/2532 ｜ Tkinter 中文输入 https://stackoverflow.com/questions/28747976/is-it-possible-to-input-chinese-text-into-tk-text-and-entry-widgets-with-tkinter
- 跨语言：PyO3 https://github.com/pyo3/pyo3 ｜ PyOxidizer 内嵌文档 https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_rust_generic_embedding.html ｜ pythonnet https://github.com/pythonnet/pythonnet