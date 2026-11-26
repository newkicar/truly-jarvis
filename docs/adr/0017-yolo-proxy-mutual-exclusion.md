# ADR-0017: YOLO `/yolo` 与 替我审批 `/proxy` 互斥（后开者为准）

**状态:** 已接受（2026-11-26，Issue #9）

## 背景

- `/yolo`（YOLO）与 `/proxy`（替我审批，ADR-0014）是两条并行的免审批通道：
  YOLO 在 `_action_for_args` 最顶部短路「全放行」（含危险操作）；
  proxy 是「安全项按确定性规则表自动放行、危险项仍留人类审批」的半自动区。
- 此前两者可在同一 thread 同时为 on：YOLO 的顶部短路先于 proxy 规则表命中，
  proxy 的「拦住危险项」语义被**静默覆盖**——用户以为危险操作有守门，实际没有。
- GUI 开关、TUI/CLI 的 `/yolo` 与 `/proxy` 各自读各自的状态面，双开时三处表面
  状态可与内核实际生效语义不一致。

## 决策

1. **内核层互斥，后开者为准**（限同 thread）：
   - `permissions.yolo_on` 返回前自动 `proxy_off(state, tid)`；
     `proxy_on` 返回前自动 `yolo_off(state, tid)`（纯 state-dict 函数，零 agent 重建）。
   - `yolo_off` / `proxy_off` 保持独立：关一个不影响另一个。
   - `yolo_threads` / `proxy_threads` 集合本就是 thread 级，互斥天然不跨会话。
   - 修在内核 = 单一真源：GUI 开关、TUI/CLI dispatch 都汇入同一对纯函数，
     状态面自动一致，UI 层零分支。
2. **回复文案显式化自动关闭**：`yolo_command_text` / `proxy_command_text` 在开启前
   捕获对方状态（`was_proxy` / `was_yolo`）；互斥实际关闭了对方时，首开回复文案
   追加「，替我审批已随之关闭」/「，YOLO 已随之关闭」；幂等重复 on 与
   无互斥发生的文案与改动前**逐字不变**（既有断言不受影响）。
3. **GUI 开关同步**：`_on_yolo_toggled` 开启前捕获 `was_proxy`，状态栏文案同注；
   `_refresh_mode_badges` 本就同时读 `yolo_active` + `proxy_active`，自动一致无需改。

## 测试

- `tests/test_permissions.py` +5：双向互斥（开 yolo 关 proxy / 开 proxy 关 yolo）、
  off 独立性、互斥矩阵（正向 on→on→off→off 与反序全轨迹）、线程隔离。
- `tests/test_commands.py` +2：dispatch 级互斥回复文案（断言「随之关闭」+ 事后内核
  状态断言），覆盖两个方向。
- 全部纯内存 state-dict 测试，无 tmp_path（本机 temp 目录 WinError 5 中毒纪律）。

## 后果与边界

- 不允许双开即无需优先级仲裁：连续两次「on」的终态由顺序决定（后开者为准）。
- 不改 `_action_for_args` 短路顺序（YOLO 短路仍在 hook 解析之前），
  不改正交地板（VaultWriteGuard、步数预算、熔断、Plan 模式门）。
- 重启全关的既有语义不变；互斥不引入任何持久化。
