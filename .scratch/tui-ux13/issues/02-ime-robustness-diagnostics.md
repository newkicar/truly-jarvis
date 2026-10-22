# 02 — IME 通道鲁棒化 + 诊断扩展（Bug 2：中文输入不挑电脑，L1/L2 层）

**What to build:**
- L1 自动层（src/ime_shim.py，170 行现状：`install()` L183 仅 main.py L247-254 装一次，Textual 改形静默漂移只留启动行）：
  - 新纯函数 `shim_status() -> str`：返回 "installed" / "drifted" / "absent"——读 `EventMonitor._jarvis_ime_shim`(L207) 与 `_jarvis_ime_drift`(L204) 属性；非 win32 / 模块缺失 → "absent"；可单测（fake 模块属性表）。
  - 新幂等入口 `ensure() -> str`：drifted → 清 `_jarvis_ime_drift` 后重跑 `install()`（签名校验 `ReadConsoleInputW`）；返回新状态。main.py L247 装配点 `install()` → `ensure()`（成功不追加启动行，语义不变；absent 才保留现状启动行）。
  - `JarvisApp` 低频复检：TUI 装配前 + 权限 modal 打开时（实测低成本点）调 `shim_status()`；状态从 installed 翻转 → 一次性 notify「输入通道漂移，中文输入可能受影响；Ctrl+. 标点快插面板仍可用，详见 /doctor」（一次性 flag，不刷屏）。
- L2 手动层（src/input_probe.py，现状：`run()` 尾部只有原始 counts 行「汇总: KEY=n ...」，**无判定**且非纯函数）：
  - 新纯函数 `summarize_session(counts: dict[int, int], nul_u_char_count: int, cp: int, ended_by: str) -> list[str]`：记录类型直方图（KEY/UNICODE/IME/SIZE）+ 三态判定——UNICODE 或 IME 记录存在 →「中文确认通道可达」；仅 KEY 且 NUL-uChar 计数 > 0 →「中文依赖 NUL-uChar 重建（ime_shim），请核对 shim 状态（/doctor）」；无 CJK 记录 →「未观察到中文输入，请确认输入法与终端」；每态附「下一步怎么办」指引文案（shim 状态 + CP 告警 + Ctrl+. 兜底）。
  - `run()` 尾部改为调用 `summarize_session` 打印判定行（原始 counts 行保留）；`main` 退出路径不变；NUL-uChar 计数在记录循环内顺手统计（`format_key_event` 已有 <NUL> 标记，计数加一变量即可）。
  - `/doctor` 输入通道扩 1 行 → 2 行：① 现状 `doctor_input_channel_line()`(L62，CP + stdin 类型 + Ctrl+. 提示) 追加 shim 状态（复用 `shim_status()`）；② 新终端类型行：conhost / Windows Terminal / pipe 三态（conhost 复用 src/tui_punct `is_conhost_like()` L52 思路；WT 查 `WT_SESSION` env；pipe = GetFileType PIPE → 与 CP 告警聚合）；commands.py doctor 命令调用点同步。
- L3 兜底入口确认（无新主代码）：Ctrl+. 标点面板（`action_punct_panel` L1804 / `PunctPanelModal`）+ `tui.ime_hint`（`ime_hint_line` L76 auto 模式）——仅确认提示可达（/doctor 行已覆盖），不新增行为。
- 红线不变：**绝不自动 SetConsoleCP**（ConPTY 65000→65001 破坏 IME 的既定定案），CP 异常只诊断告警。
- 测试：test_ime_shim（`shim_status` 三态表 + `ensure` 幂等：drifted→重装配 success、absent→install、installed→no-op）；test_input_probe（`summarize_session` 三态判定表 + 指引文案断言）；/doctor 2 行断言（非 Windows 平台 n/a 分支保持）。

**Type:** bugfix
**Status:** done
**Blocked by:** 无

## 验收
- [x] `shim_status()` 三态纯函数 + `ensure()` 幂等重装配；main.py 装配点改用 `ensure()`
- [x] TUI 低频复检：installed→drifted/absent 翻转时一次性可见 notify（不再静默启动行）
- [x] `summarize_session` 纯函数三态判定 + 指引；`run()` 尾部输出含判定行（原始汇总行保留）
- [x] `/doctor` 输入通道 2 行（shim 状态行 + 终端类型三态行）
- [x] 不自动 SetConsoleCP 红线不变（CP 异常仅告警）
- [x] test_ime_shim / test_input_probe / doctor 断言全绿；全量 pytest 无新增失败（对照基线 609 passed + 预存 3× test_config）

**Done:** 2026-10-22（shim_status/ensure + summarize_session + /doctor 2 行全绿：test_ime_shim / test_input_probe 通过；L1 低频复检调用点收敛为 JarvisApp 侧（启动初焦 / 权限 modal 打开 / 标点面板 / 复制面板），PermissionModal 内部 2 处误插调用已移除（test_tui_modals 回归绿）；红线「绝不自动 SetConsoleCP」不变）
