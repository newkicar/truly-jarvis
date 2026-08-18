# 10 — TUI 真模型冒烟场景（手动）

**What to build:** `smoke_test.py` 增补 `--tui` 场景：真实模型跑一轮触发 HITL 的对话，文档说明如何手动验证 Permission Modal 与 resume。该脚本**不进 CI**，与现有 smoke 约定一致。

**Blocked by:** 09 — 命令分发与 CLI 审批单测补全

**Status:** ready-for-agent

- [ ] `smoke_test.py --tui` 或子参数可启动 TUI 并执行预设 prompt（需 execute 或 write Inbox 的用例）
- [ ] README 或 smoke 内注释：依赖 `.env` 真模型、手动点 Modal
- [ ] 不将真模型 TUI 步骤加入 GitHub Actions / CI 配置
