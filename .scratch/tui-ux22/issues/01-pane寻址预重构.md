# 01 — pane 寻址预重构（resolve_panes 纯 helper）

**What to build:** 抽出 pane 寻址纯 helper，为双 pane 布局打底（用户不可见）：
- 新增 `resolve_panes(permission_state, active_tid, focus)`：只读
  `permissions.side_active` / `side_parent`，返回 mainline_tid / side_tid /
  焦点 pane / tid→pane 归属（纯函数，无 UI 依赖）；
- `_refresh_side_badge`（L1233-1243）/ `_refresh_yolo_badge` 族改走该 helper，
  显示效果零变化（`#side_badge` L1315、`[SIDE]→<parent8>` L1208-1212 文案与
  出现时机不变）；
- `NoMatches`（在 `textual.css.query`）/ ScreenStackError 守卫保留。

**Blocked by:** 无

**Status:** ready-for-agent

- [x] `resolve_panes` 纯函数四态矩阵测试（无 side / 有 side / 焦点左 / 焦点右）
- [x] 改走 helper 后既有 badge 测试全绿
- [x] NoMatches / ScreenStackError 守卫仍在
- [x] 全量 pytest 无新增失败（预存 test_config×3 除外）