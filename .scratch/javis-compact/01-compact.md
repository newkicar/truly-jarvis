# 01 /compact 实现工单

- [x] commands.py：compact() + dispatch 分支 + _HELP_COMMANDS / TUI_HELP 行
- [x] tui.py：/compact、/dream 门控分支 + _gate_command_worker（模式同 _undo_worker：
      dispatch → _apply_command_result → _release_turn_gate，异常 → 「命令失败: …」）
- [x] slash_completion.py：SlashCommand("/compact", "/compact [提示]", "压缩当前会话上下文为延续性摘要（可选文字提示引导方向）")
- [x] tests/test_commands.py：fake agent + fake model 五场景
