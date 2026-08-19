# ADR-0003: 系统上下文（日期 / 时间 / 位置）

**状态:** 已修订（2026-08-20，原 2026-08-19 决策部分 supersede）

## 背景

启动时把「完整 datetime」或「用户所在地」写进主代理 `system_prompt` 会秒级过期，且污染常驻上下文。
把地址写进 `javis.json` 也不合适：用户可能在不同地点，不能写死单一坐标。

此前代理在简单问答（如「现在几点、我在哪」）上曾出现：混用宿主机绝对路径与虚拟路径、误读
`javis.json` 找 location、委派 researcher 跑本地脚本、以及把问题扩成写 `/vault/Reports/` 的报告任务。

中间版本曾用 `get_system_context` 工具 + `system-context` skill 作为唯一合法路径，导致与 OpenCode/Cline 等
成熟代理相比「问时间也要走专项能力」，模型反而更窄、更易拒绝回答。

## 决策（2026-08-20 修订）

1. **主 system prompt 结果导向 + 适度放松流程**：目标 → 工作方式 → 完成标准 → 约束 → 输出（见 `src/agent.py` 的 `MAIN_SYSTEM_PROMPT`）。多步任务允许计划→执行→核对→失败换手段；护栏聚焦**落盘**与 **HITL**，不再用「能答立刻停」「必须派 researcher」作总开关。
2. **会话日期注入**：启动时在 system prompt **仅注入当天日期 + 星期**（不含时分秒，避免秒级过期）。见 `build_main_prompt()` / `session_date_line()`。
3. **精确时间与城市**：主代理用通用 `execute` 读取本机（如 `Get-Date`、curl IP 定位），**不**提供专用 `get_system_context` 工具，**不**维护 `system-context` skill。
4. **禁止行为（仍有效）**：不写 `javis.json` location；不读 `/memories/user-profile.md` 找所在地；简单事实问答不自动写 Reports / 不委派 researcher。
5. **Skills 虚拟路径**（见 ADR-0004 扩展）：`/workspace/skills/`（项目）、`/skills/`（`~/.javis/skills/` 用户全局）、`/builtin-skills/`（安装目录默认）；禁止模型使用 `E:/...` 探路。

## 被否决的选项

- **启动时注入完整 datetime 到 system prompt**：秒级过期。
- **`javis.json` 的 `location` 字段**：把移动用户写死在机器配置里。
- **在 profile 预填默认地址**：用户移动时地址会变。
- **专用 `get_system_context` + system-context skill 作为唯一路径**（2026-08-19，已 supersede）：过度特殊化，模型反而不走 `execute`。
- **委派 researcher 执行本地时间脚本**：易触发无关检索/报告。

## 影响

- 删除：`src/system_context.py`、`skills/system-context/`。
- 新增/维护：`session_date_line()`、`~/.javis` 用户全局目录（见 `project_paths.user_home()`）。
- `Config` 与 `javis.json` **无** `location` 字段。
