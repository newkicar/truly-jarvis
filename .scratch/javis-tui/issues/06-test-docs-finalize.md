# 06 — TUI 测试 + 文档 + 冒烟收尾

**What to build:** TUI 完整交付的收尾：测试补齐、冒烟增补、文档同步、架构决策记录。让后续会话/团队能快速理解 TUI 的落地与设计权衡。

**Blocked by:** 05 — 主入口 --tui/--cli 分支

**Status:** done

- [ ] `tests/test_tui.py`：TUI 冒烟测试集合——app 启动/退出、输入提交路由、权限 Modal 弹出/关闭（配合 02/03/04 已落的测试，不重复）
- [ ] `smoke_test.py` 增补 TUI 场景：真实模型跑一轮带审批的对话，验证 Modal 交互 + resume
- [ ] `AGENTS.md` / `CLAUDE.md` 更新：交付清单加 `tui.py`、`commands.py`；分期加 TUI 阶段；测试数更新；关键决策补 TUI 段（对标 opencode、commands.py 公共层、流式 worker、权限 Modal 四按钮）
- [ ] `docs/specs/2026-08-15-javis-design.md` 同步：§11 项目结构加 `tui.py`/`commands.py`；交互形态从「纯 CLI」更新为「TUI 默认 + CLI fallback」；验收标准补 TUI 条目
- [ ] 新建 ADR（`docs/adr/`）：TUI 技术选型（Textual 对标 opencode Bubble Tea）、commands.py 公共层、权限 Modal 四按钮语义
- [ ] 全量 pytest 全绿；git 提交