# 07 — 可观测 ops 事件 + 诊断（sanitize JSONL，测试断言）

Status: ready-for-agent
Blocked by: 04, 06

## What to build

1. `src/profiles/observability.py` + `src/profiles/diagnostics.py`：
   - `ops_event(kind, **fields)` JSONL 写 `~/.jarvis/ops/events.jsonl`（§19 事件族：profile loaded/validation failed、runtime created、cache hit/miss、skills resolved、tools resolved、memory recall、memory candidate created/promoted/rejected、tool permission denied、approval requested/approved/rejected、worker started/completed/failed/cancelled、checkpoint resumed）；
   - sanitize 由测试断言（日志/事件不含敏感记忆内容、凭据、完整 prompt、PII）；
   - run-record 与 agent_runs 生命周期打通；
   - diagnostics：`list_profiles()`、`validate_profile(id)`、`memory_namespace_view(ns)`、`skill_manifest_report(profile_id)`、`permission_diagnose(profile, tool)`；
   - 入口：`python -m src.main --profiles [id] [--validate]` + TUI `/profiles`（经 commands.py，CLI+TUI 共享）+ GUI 安全 no-op。
2. 测试：`tests/test_profile_ops.py`（事件族覆盖、sanitize 断言、诊断报告、/profiles 分发文案）。

## Acceptance

- [ ] 目标套件全绿；
- [ ] 相关套件（commands/tui）vs 基线无新增失败；
- [ ] 全量 vs 基线无新增失败；
- [ ] commit（UTF-8 message 文件；7 张工单全部完成后出中文总汇报）。
