# 02 — `/yolo` 命令端到端：dispatch + 幂等文案 + help + slash 补全

**What to build:** CLI+TUI 共用的 `/yolo` 命令（commands.py 内核，UI 零分叉）：

- `dispatch_command`（src/commands.py L1082）新增 `/yolo` 分支（紧邻 `/use` L1049 风格）：
  - `/yolo on`：`yolo_on(state, thread_id)`；幂等文案——已开 →「YOLO 已开启（本会话免审批；
    vault 写保护、步数预算与熔断仍生效）」，新开 →「YOLO 已开启」+ 同上括注；
  - `/yolo off`：`yolo_off`；幂等——已关 →「YOLO 已关闭（本会话）」，刚关 →「YOLO 已关闭：
    恢复本会话原 permissions 规则」；
  - 裸 `/yolo`：**只查询**——「YOLO 状态：本会话 已开启/已关闭」（不做开关动作）；
  - 非法参数（`/yolo x` 等）：`用法: /yolo on | /yolo off`（照 `/use` L1057 用法行风格）；
  - state 引用从 dispatch 上下文取（agent 装配时注入的共享 permission_state，与
    `always_approve` L1007 取同一引用；取不到 state → 该命令返回错误文本不崩）。
- help 行：`_HELP_COMMANDS`（L30，CLI_HELP L51 / TUI_HELP L57 两处引用自动生效）加
  `/yolo on | off  YOLO 模式开关：本会话所有动作免审批（仅当前会话、重启即关）`；
  `dispatch` 的 slash 命令白名单/unknown 回退（L1157 附近）同步放行 `/yolo`。
- slash 补全：`src/slash_completion.py` 条目表（L18/L31 区域）加
  `SlashCommand("/yolo", "/yolo on | off", "YOLO 模式开关（仅当前会话）")`——
  `/yol` 前缀即出建议，Tab/Enter 接受语义零改动。
- 测试（tests/test_commands.py 追加；补全用例进 test_slash_completion.py / test_tui_completion.py；
  禁 tmp_path，自建目录）：
  - on/off/裸查询/非法参数四条文案断言（含幂等两次 on 的「已开启」措辞）；
  - on 后共享 state `yolo_active` 为 True、off 后 False；裸查询**不改变**状态；
  - help 输出含 `/yolo` 行；补全 `/yol` 命中唯一条目、`/yolo ` 后（带空格）不再命中补全。
- 演示闭环（人工冒烟，不进 CI）：`/yolo on` 后本会话执行 gated 工具（如 `execute whoami`）
  不弹审批；`/yolo off` 后恢复审批。

**Type:** feature
**Status:** done
**Blocked by:** 01（YOLO 内核）

## 验收
- [x] `/yolo on|off`、裸查询、非法参数四态行为与文案符合上表
- [x] 幂等措辞（已开启/已关闭）测试覆盖
- [x] help 行 + slash 补全条目 + 白名单放行，三处齐全
- [x] 测试全绿；CLI 与 TUI 走同一 dispatch 内核（TUI 侧本票无 UI 改动）

**Done:** 2026-10-21，主 commit `1e7ff0c`。