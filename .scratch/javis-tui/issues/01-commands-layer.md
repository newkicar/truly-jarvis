# 01 — 抽取 commands.py 公共命令层

**What to build:** 把 `src/main.py` 里的命令分发与会话管理纯逻辑搬到新建的 `src/commands.py`，CLI 与未来 TUI 共用。这是 TUI 落地的前提——没有公共层，命令逻辑会被复制两遍（shotgun 症状）。

**Blocked by:** None — 可以立即开始

**Status:** done

- [ ] 新建 `src/commands.py`，迁移以下函数（签名保持「接收 agent/thread_id → 返回文本」）：`dispatch_command`、`list_sessions`、`list_history`、`resolve_checkpoint_id`、`boundary_checkpoints`、`replay`、`fork`、`snapshot`、`list_snapshots`、`rollback`、`last_human_text`、`checkpoint_short_id`、`current_permissions`、`project_root`
- [ ] `src/main.py` 改为从 `src.commands` import，行为零变化（纯搬移，不改签名）
- [ ] `tests/test_main.py` 的 6 个现有测试迁移到 `tests/test_commands.py`，import 目标改为 `src.commands`，断言不变
- [ ] `tests/test_commands.py` 补充 `dispatch_command` 分发测试（/sessions /history /replay /fork /snapshot /rollback /reload-schedules /未知命令）
- [ ] `tests/test_commands.py` 补充 `current_permissions` 序列化测试
- [ ] 全量 pytest 全绿（原 94 + 新增）