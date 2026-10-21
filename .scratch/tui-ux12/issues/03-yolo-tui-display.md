# 03 — TUI 呈现：Header [YOLO] 标记 + on/off notify

**What to build:** TUI 侧的 YOLO 状态可见性（UI 薄壳，逻辑全在 01/02）：

- `JarvisApp._update_sub_title`（src/tui.py L1032，现有 parts：项目名 + thread_id + `MCP:N` L1037，
  拼接 L1047）：当前 thread 处于 yolo（`yolo_active(state, 当前thread_id)`）时 parts 尾部
  追加 `[YOLO]`；非 yolo 不加。刷新点全覆盖——`/sessions` 切换（L1484/L1536 既有调用点）、
  新建会话、`/replay`（新 thread → 标记消失）、on/off 后即时刷新（命令返回后触发一次）。
- on/off notify（Textual `app.notify`，UI 线程 `call_from_thread` 驱动，既有 NoMatches 防御
  纪律适用）：
  - 开：`YOLO 已开启：本会话免审批（vault 写保护与步数/熔断仍生效，/yolo off 关闭）`；
  - 关：`YOLO 已关闭：恢复原审批规则`（幂等场景沿用 02 的「已开启/已关闭」简短版，
    不重复长句）。
- Header 样式：`[YOLO]` 用醒目但非告警色（`$success` 粗体，或主题无关的 bright yellow——
  实现时取其一，测试只断言文本存在性不锁样式）。
- 测试（tests/test_tui.py，Textual pilot；modal 查询纪律不适用；禁 tmp_path/tempfile.mkdtemp）：
  - yolo 会话 Header sub_title 含 `[YOLO]`；切到非 yolo 会话（`/sessions`）标记消失；
  - on/off 各触发一条 notify（pilot 断言 message 文本，幂等措辞与 02 一致）；
  - 锚点回归：既有 `_update_sub_title` 相关测试（MCP:N 拼接）全绿。

**Type:** feature
**Status:** done
**Blocked by:** 02（标记本身只依赖 01；保持线性以缩小集成面，软阻塞）

## 验收
- [x] 当前 thread yolo 时 Header 显示 `[YOLO]`，非 yolo 不显示；会话切换/replay 联动正确
- [x] on/off notify 一条（幂等场景短措辞）
- [x] 测试全绿 + 锚点回归绿

**Done:** 2026-10-21，主 commit `1e7ff0c`。