# 01 — YOLO 内核：permissions 层 yolo_threads + _action_for_args 短路

**What to build:** YOLO 模式的权限层内核（零 agent 重建、live 生效）：

- `build_permission_interrupts`（src/permissions.py L186，state dict L205-212）初始化
  新增 `"yolo_threads": set()`（与 `default/tools/hooks/thread_id/project_root/heuristics`
  平级；`build_permission_interrupts_from_state` L216 复用路径保证键存在，缺键 `setdefault`）。
- 新增纯函数 helper（同文件，便于单测）：
  - `yolo_on(state, thread_id)`：`thread_id` 非空时 `state["yolo_threads"].add(...)`，返回 True；
    空串/None → no-op 返回 False。
  - `yolo_off(state, thread_id)`：discard，幂等；空串 no-op。
  - `yolo_active(state, thread_id) -> bool`：成员判定；`thread_id` 空串 → False；
    state 缺 `yolo_threads` 键（旧引用防御）→ False。
- **单 seam 短路**：`_action_for_args`（L111）函数体**最顶部**（hook 解析 L116 之前）插入：
  `if yolo_active(state, str(state.get("thread_id") or "")): return "allow"`。
  效果（grill 定案 1）：`when` 谓词（L160 `_build_when`，ask→interrupt）与
  `PermissionDenyMiddleware.block`（L281，deny→拦截）双路汇入此处 → ask 弹窗与 deny 拒绝
  同时消失；hook（permission hooks）也 bypass（「最高权限」语义）；`state["tools"]`
  规则、jarvis.json、interrupt_on dict **全部不动**（off = 从集合移除，原规则原样）。
- 正交不动项零代码改动（以断言证明）：`VaultWriteGuardMiddleware`（vault 写地板）、
  `StepBudgetMiddleware`（预算提醒）、`DoomLoopMiddleware`（5 次熔断）、
  `PlanModeMiddleware`（Plan 写门）均不读 `yolo_threads`。
- 测试（tests/test_permissions.py 追加；禁 tmp_path/tempfile.mkdtemp，自建目录）：
  - 默认 ask：`yolo_on` 后 `_action_for_args` 对 execute/write_file/edit_file/delete 全返 "allow"
    （含原本规则为 "deny" 的工具 → 也 allow，bypass 语义）；
  - off 恢复：`yolo_off` 后 deny 工具回 "deny"、ask 工具回 "ask"（原规则未被动过，断言
    `state["tools"]` 前后不变）；
  - 线程隔离：线程 A on、线程 B（state["thread_id"]="b"）仍按原规则；
  - hook bypass：配 hook 规则 + yolo → 短路优先于 hook；
  - `yolo_active` 纯函数组（空串 / 缺键 state / 成员 / 非成员）；
  - vault 正交：tests/test_vault_guard.py 追加 1 条（yolo_threads 含当前 thread 时 vault
    写拦截行为不变）。

**Type:** feature
**Status:** done
**Blocked by:** 无

## 验收
- [x] `build_permission_interrupts` 返回的 state 含 `yolo_threads: set()`
- [x] `_action_for_args` 顶部 yolo 短路（ask 与 deny 双路同时 bypass，hook 之前）
- [x] 上述测试全绿；锚点回归（既有 test_permissions 全量）绿
- [x] `state["tools"]` 规则与 jarvis.json 在 on/off 前后零 diff（测试断言）

**Done:** 2026-10-21，主 commit `1e7ff0c`。